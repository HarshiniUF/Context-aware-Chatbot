"""
=============================================================
SOIL TOOL — get_soil_profile
Coordinates, depth range, properties → soil type, texture,
organic matter (+ any requested iSDAsoil property)
=============================================================

Primary source: iSDAsoil v2 REST API (Africa only, 30 m resolution).
Credentials: ISDASOIL_USERNAME / ISDASOIL_PASSWORD in .env
(login + token caching reused from wsp_soil_isda.get_isda_token).

Fallback source: GHR global soil profiles (ISRIC SoilGrids + HC27, DSSAT
format, ~10 km). Used when the point is outside Africa or iSDAsoil returns
no data (deserts, water bodies, API/auth failure). Local files, read from
GHR_SOIL_DIR (default: this project folder; both data folders are gitignored):
  soil/GHR_cleaned_2.tif  lat/lon → map id (5 arc-min global grid)
  soil/GHR.db             SQLite profile_map(id, profile): map id → site id
  eGHR/<CC>.SOL           DSSAT soil profiles, one file per country code
GHR has no extractable nutrients (P, K, Ca, Mg, S, Zn, Fe, Al), bedrock depth,
slope or fertility constraints; those come back in property_errors. It adds
water-holding properties (wilting point, field capacity, saturation).

Facts verified against the live API (/isdasoil/v2/layers):
  - Depths available: "0-20" and "20-50" cm only (no 50-100).
  - Some properties have a fixed depth: bedrock_depth (0-200), fcc (0-50),
    slope_angle (0) — these are always returned at their own depth.
  - iSDAsoil has NO taxonomic soil type. The WRB soil type (e.g. "Ferralsols")
    comes from ISRIC SoilGrids (global, 250 m, no key). SoilGrids is slow and
    sometimes times out (observed 8-55 s, occasional >60 s), so it runs in
    parallel with iSDAsoil and failure only leaves soil_type.wrb_class empty.
  - iSDAsoil's texture_class is predicted independently of sand/silt/clay and
    can disagree with the class those fractions imply at borderline points.

Never raises: returns {"ok": False, "error": ...} on failure.

Output (dict):
  {
    "ok": bool, "error": str or None,
    "location": {"latitude", "longitude"},
    "depths_cm": ["0-20", ...],
    "soil_type": {"wrb_class", "wrb_probability_pct", "wrb_alternatives",
                  "fertility_capability_classification", "sources"},
    "by_depth": {"0-20": {"texture_class", "sand_pct", "silt_pct", "clay_pct",
                          "organic_carbon_g_per_kg", "organic_matter_pct_est", ...}},
    "properties": {name: {"description", "unit", "values": [{"depth", "value", "range_90pct"}]}},
    "property_errors": {name: message},
    "metadata": {"provider", "resolution", "coverage", "retrieved_at", "notes"},
  }
=============================================================
"""

import mmap
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from wsp_soil_isda import get_isda_token, ISDA_LAYERS_ENDPOINT, ISDA_SOILPROPERTY_ENDPOINT

SOILGRIDS_WRB_URL = "https://rest.isric.org/soilgrids/v2.0/classification/query"
SOILGRIDS_TIMEOUT_S = 30
VALID_DEPTHS = ["0-20", "20-50"]
DEFAULT_DEPTHS = ["0-20"]
REQUEST_TIMEOUT_S = 20
VAN_BEMMELEN_FACTOR = 1.724  # organic matter ≈ organic carbon × 1.724

# Generous box around Africa (incl. Madagascar, Cape Verde, Seychelles, Mauritius).
# Points outside it skip iSDAsoil; points inside that iSDAsoil can't serve still fall back.
AFRICA_BBOX = {"lat_min": -36.0, "lat_max": 38.0, "lon_min": -26.0, "lon_max": 64.0}

GHR_SOIL_DIR = Path(os.getenv("GHR_SOIL_DIR", Path(__file__).resolve().parent))
GHR_TIF_PATH = GHR_SOIL_DIR / "soil" / "GHR_cleaned_2.tif"
GHR_DB_PATH = GHR_SOIL_DIR / "soil" / "GHR.db"
GHR_SOL_DIR = GHR_SOIL_DIR / "eGHR"
GHR_MISSING = -99.0

# Friendly names → iSDAsoil property names (raw iSDA names are accepted too)
SOIL_PROPERTY_ALIASES = {
    "organic_carbon": "carbon_organic",
    "total_carbon": "carbon_total",
    "nitrogen": "nitrogen_total",
    "ph": "ph",
    "sand": "sand_content",
    "silt": "silt_content",
    "clay": "clay_content",
    "texture": "texture_class",
    "cec": "cation_exchange_capacity",
    "bulk_density": "bulk_density",
    "stone_content": "stone_content",
    "bedrock_depth": "bedrock_depth",
    "phosphorus": "phosphorous_extractable",
    "potassium": "potassium_extractable",
    "calcium": "calcium_extractable",
    "magnesium": "magnesium_extractable",
    "sulphur": "sulphur_extractable",
    "zinc": "zinc_extractable",
    "iron": "iron_extractable",
    "aluminium": "aluminium_extractable",
    "fertility_constraints": "fcc",
    "slope": "slope_angle",
}
# Enough for the email's outputs: soil type, texture, organic matter
DEFAULT_PROPERTIES = ["texture", "sand", "silt", "clay", "organic_carbon", "fertility_constraints"]

# Friendly name → (DSSAT .SOL column, factor to iSDA's unit, unit, description).
# sand and texture are derived from clay + silt.
GHR_PROPERTIES = {
    "organic_carbon": ("SLOC", 10, "g/kg", "Carbon, organic (generic HC27 class value, not site-specific)"),
    "nitrogen": ("SLNI", 10, "g/kg", "Nitrogen, total (generic HC27 class value, not site-specific)"),
    "ph": ("SLHW", 1, None, "pH (water)"),
    "clay": ("SLCL", 1, "%", "Clay content"),
    "silt": ("SLSI", 1, "%", "Silt content"),
    "cec": ("SCEC", 1, "cmol(+)/kg", "Cation exchange capacity"),
    "bulk_density": ("SBDM", 1, "g/cm³", "Bulk density"),
    "stone_content": ("SLCF", 1, "%", "Coarse fragments"),
}
GHR_DERIVED = {
    "sand": ("%", "Sand content (100 - clay - silt)"),
    "texture": (None, "USDA texture class (from sand/silt/clay)"),
}
# Always added to the GHR by_depth summary (not available from iSDAsoil)
GHR_WATER_COLUMNS = {
    "wilting_point_cm3_cm3": "SLLL",
    "field_capacity_cm3_cm3": "SDUL",
    "saturation_cm3_cm3": "SSAT",
}

_CATALOG_CACHE: dict = {}


def _error(message: str, **extra) -> dict:
    return {"ok": False, "error": message, **extra}


def _catalog(headers: dict) -> dict:
    """iSDAsoil property catalog (descriptions, units, depths), fetched once per process."""
    if not _CATALOG_CACHE:
        response = requests.get(ISDA_LAYERS_ENDPOINT, headers=headers, timeout=REQUEST_TIMEOUT_S)
        response.raise_for_status()
        _CATALOG_CACHE.update(response.json()["property"])
    return _CATALOG_CACHE


def _fetch_property(prop: str, latitude: float, longitude: float, headers: dict):
    """One property, all depths (the API returns every depth when none is given)."""
    try:
        response = requests.get(
            ISDA_SOILPROPERTY_ENDPOINT,
            params={"lat": latitude, "lon": longitude, "property": prop},
            headers=headers,
            timeout=REQUEST_TIMEOUT_S,
        )
        if response.status_code != 200:
            try:
                detail = response.json().get("detail")
            except Exception:
                detail = None
            return prop, None, detail or f"HTTP {response.status_code}"
        return prop, response.json().get("property", {}).get(prop, []), None
    except Exception as e:
        return prop, None, str(e)


def _fetch_wrb_soil_type(latitude: float, longitude: float) -> dict:
    """WRB reference soil group from ISRIC SoilGrids (most probable class + alternatives)."""
    try:
        response = requests.get(
            SOILGRIDS_WRB_URL,
            params={"lat": latitude, "lon": longitude, "number_classes": 3},
            timeout=SOILGRIDS_TIMEOUT_S,
        )
        response.raise_for_status()
        data = response.json()
        ranked = data.get("wrb_class_probability") or []
        return {
            "wrb_class": data.get("wrb_class_name"),
            "wrb_probability_pct": ranked[0][1] if ranked else None,
            "wrb_alternatives": [{"class": c, "probability_pct": pct} for c, pct in ranked[1:]],
            "error": None,
        }
    except Exception as e:
        return {"wrb_class": None, "wrb_probability_pct": None, "wrb_alternatives": [],
                "error": f"SoilGrids unavailable: {e}"}


def _range_90(entry: dict) -> Optional[list]:
    """90% prediction interval; None when absent or degenerate (API sometimes returns 0-0)."""
    for unc in entry.get("uncertainty") or []:
        if unc.get("confidence_interval") == "90%":
            low, high = unc.get("lower_bound"), unc.get("upper_bound")
            if low is None or high is None or (low == 0 and high == 0):
                return None
            return [low, high]
    return None


def _summarize_by_depth(props: dict, depths: list) -> dict:
    """Clean per-depth summary: texture + organic matter + any other requested property."""
    def value_at(friendly: str, depth: str):
        for v in props.get(friendly, {}).get("values", []):
            if v["depth"] == depth:
                return v["value"]
        return None

    by_depth = {}
    for depth in depths:
        row = {
            "texture_class": value_at("texture", depth),
            "sand_pct": value_at("sand", depth),
            "silt_pct": value_at("silt", depth),
            "clay_pct": value_at("clay", depth),
        }
        oc = value_at("organic_carbon", depth)
        if oc is not None:
            row["organic_carbon_g_per_kg"] = oc
            row["organic_carbon_pct"] = round(oc / 10, 2)
            row["organic_matter_pct_est"] = round(oc / 10 * VAN_BEMMELEN_FACTOR, 2)
        for friendly in props:
            if friendly not in ("texture", "sand", "silt", "clay", "organic_carbon"):
                v = value_at(friendly, depth)
                if v is not None:
                    row[friendly] = v
        by_depth[depth] = {k: v for k, v in row.items() if v is not None}
    return by_depth


def _in_africa(latitude: float, longitude: float) -> bool:
    return (AFRICA_BBOX["lat_min"] <= latitude <= AFRICA_BBOX["lat_max"]
            and AFRICA_BBOX["lon_min"] <= longitude <= AFRICA_BBOX["lon_max"])


def get_soil_profile(latitude: float,
                     longitude: float,
                     depths: Optional[list] = None,
                     properties: Optional[list] = None,
                     include_soil_type: bool = True) -> dict:
    """
    Soil profile for a location: iSDAsoil in Africa, GHR global profiles elsewhere
    (or when iSDAsoil has no data / is unavailable).

    Args:
        latitude, longitude: location in decimal degrees
        depths: list of "0-20" and/or "20-50" (cm); default ["0-20"]
        properties: friendly names (see SOIL_PROPERTY_ALIASES) or raw iSDAsoil names;
                    default: texture, sand, silt, clay, organic_carbon, fertility_constraints
        include_soil_type: also query SoilGrids for the WRB soil type (slow, 10-30 s)
    """
    # ── Validate inputs ──
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _error(f"Invalid coordinates: lat={latitude}, lon={longitude}")
    depths = list(dict.fromkeys(depths or DEFAULT_DEPTHS))
    bad_depths = [d for d in depths if d not in VALID_DEPTHS]
    if bad_depths:
        return _error(f"Unsupported depths {bad_depths}. Only {VALID_DEPTHS} (cm) are available.")
    requested = properties or DEFAULT_PROPERTIES

    if _in_africa(latitude, longitude):
        result = _get_isda_profile(latitude, longitude, depths, requested, include_soil_type)
        if result["ok"] or result.get("input_error"):
            return result
        isda_error = result["error"].rstrip(".")
    else:
        isda_error = "outside iSDAsoil coverage (Africa only)"

    result = _get_ghr_profile(latitude, longitude, depths, requested, include_soil_type, isda_error)
    if result["ok"] or result.get("input_error"):
        return result
    return _error(f"iSDAsoil: {isda_error}. eGHR fallback: {result['error']}",
                  property_errors=result.get("property_errors", {}))


# ─────────────────────────────────────────────────────────────
# iSDAsoil (Africa, 30 m)
# ─────────────────────────────────────────────────────────────
def _get_isda_profile(latitude: float, longitude: float, depths: list, requested: list,
                      include_soil_type: bool) -> dict:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    try:
        headers = {"Authorization": f"Bearer {get_isda_token()}"}
        catalog = _catalog(headers)
    except Exception as e:
        return _error(f"iSDAsoil authentication/catalog failed: {e}")

    api_names, unknown = [], []
    for p in requested:
        name = SOIL_PROPERTY_ALIASES.get(p, p)
        (api_names if name in catalog else unknown).append(name)
    if unknown:
        return _error(f"Unknown properties {unknown}. Valid: {sorted(SOIL_PROPERTY_ALIASES)}",
                      input_error=True)
    api_names = list(dict.fromkeys(api_names))
    alias_of = {v: k for k, v in SOIL_PROPERTY_ALIASES.items()}

    # ── Fetch (in parallel; the slow SoilGrids call overlaps the iSDAsoil calls) ──
    with ThreadPoolExecutor(max_workers=7) as pool:
        wrb_future = pool.submit(_fetch_wrb_soil_type, latitude, longitude) if include_soil_type else None
        results = list(pool.map(lambda p: _fetch_property(p, latitude, longitude, headers), api_names))
        wrb = wrb_future.result() if wrb_future else None

    props, errors = {}, {}
    for api_name, entries, err in results:
        friendly = alias_of.get(api_name, api_name)
        if err:
            errors[friendly] = err
            continue
        # e.g. fcc (0-50), bedrock_depth (0-200), slope_angle (0): keep their single depth
        fixed_depth = not set(catalog[api_name]["depths"]["values"]) <= set(VALID_DEPTHS)
        values = [
            {
                "depth": e.get("depth", {}).get("value"),
                "value": e.get("value", {}).get("value"),
                "range_90pct": _range_90(e),
            }
            for e in entries
            if fixed_depth or e.get("depth", {}).get("value") in depths
        ]
        props[friendly] = {
            "description": catalog[api_name].get("description"),
            "unit": catalog[api_name].get("unit"),
            "values": values,
        }

    if not props:
        # Typically every property fails the same way (e.g. outside Africa)
        return _error(f"No soil data returned: {'; '.join(sorted(set(errors.values())))}",
                      property_errors=errors)

    fcc_values = props.get("fertility_constraints", {}).get("values", [])
    return {
        "ok": True,
        "error": None,
        "location": {"latitude": latitude, "longitude": longitude},
        "depths_cm": depths,
        "soil_type": {
            "wrb_class": wrb["wrb_class"] if wrb else None,
            "wrb_probability_pct": wrb["wrb_probability_pct"] if wrb else None,
            "wrb_alternatives": wrb["wrb_alternatives"] if wrb else [],
            "fertility_capability_classification": fcc_values[0]["value"] if fcc_values else None,
            "sources": "WRB: ISRIC SoilGrids 2.0 (250 m, probabilistic); FCC: iSDAsoil",
            "wrb_error": (wrb or {}).get("error") if include_soil_type else "not requested",
        },
        "by_depth": _summarize_by_depth(props, depths),
        "properties": props,
        "property_errors": errors,
        "metadata": {
            "provider": "iSDAsoil v2 (iSDA Africa)",
            "resolution": "30 m",
            "coverage": "Africa only",
            "retrieved_at": retrieved_at,
            "notes": [
                "Values are model predictions, not field measurements; range_90pct is the 90% prediction interval.",
                "texture_class is iSDAsoil's own USDA class, predicted separately from sand/silt/clay; the fractions "
                "may not sum to 100% and, at borderline points, may imply a different class.",
                f"organic_matter_pct_est = organic carbon % × {VAN_BEMMELEN_FACTOR} (van Bemmelen factor).",
            ],
        },
    }


# ─────────────────────────────────────────────────────────────
# GHR global DSSAT soil profiles (fallback, ~10 km)
# ─────────────────────────────────────────────────────────────
def _ghr_site_id(latitude: float, longitude: float) -> str:
    """TIF pixel → map id → site id (e.g. 'KE04607699')."""
    import rasterio  # imported lazily so iSDAsoil-only use doesn't need it

    with rasterio.open(GHR_TIF_PATH) as src:
        map_id = int(next(src.sample([(longitude, latitude)]))[0])
        if map_id < 0 or map_id == src.nodata:
            raise ValueError("no soil profile at this point (water, ice or no-data cell)")
    with sqlite3.connect(f"file:{GHR_DB_PATH}?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT profile FROM profile_map WHERE id = ?", (map_id,)).fetchone()
    if not row or not row[0]:
        raise ValueError(f"no site id for map id {map_id}")
    return row[0].strip()


def _ghr_profile_text(site_id: str) -> str:
    """The '*<site_id>' block from <CC>.SOL. Files are large (US.SOL ~390 MB) and unsorted,
    so search the memory-mapped bytes rather than iterating lines."""
    sol_path = GHR_SOL_DIR / f"{site_id[:2].upper()}.SOL"
    needle = b"*" + site_id.encode() + b" "
    with open(sol_path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        pos = mm.find(needle)
        while pos > 0 and mm[pos - 1:pos] != b"\n":  # must start a line
            pos = mm.find(needle, pos + 1)
        if pos < 0:
            raise ValueError(f"site {site_id} not found in {sol_path.name}")
        end = mm.find(b"\n*", pos + 1)
        return mm[pos:end if end >= 0 else len(mm)].decode("utf-8", errors="ignore")


def _parse_ghr_profile(text: str) -> dict:
    """Profile header (texture name, profile lat/lon) and layers [{SLB, SLLL, SDUL, ...}]."""
    lines = text.splitlines()
    head = lines[0].split()
    profile = {"site_id": head[0].lstrip("*"),
               "texture_name": head[2] if len(head) > 2 else None,
               "latitude": None, "longitude": None, "layers": []}
    header = None
    for line in lines[1:]:
        tokens = line.split()
        if line.startswith("@"):
            header = line[1:].split()
            continue
        if not tokens or not header:
            continue
        if header[0] == "SITE" and len(tokens) >= 4:
            profile["latitude"], profile["longitude"] = float(tokens[2]), float(tokens[3])
        elif header[0] == "SLB":
            if len(tokens) == len(header) - 1:  # blank master-horizon (SLMH) column
                tokens.insert(1, None)
            layer = {}
            for col, tok in zip(header, tokens):
                if col == "SLMH":
                    continue
                value = float(tok)
                layer[col] = None if value == GHR_MISSING else value
            profile["layers"].append(layer)
    return profile


def _ghr_depth_mean(layers: list, column: str, top: float, bottom: float) -> Optional[float]:
    """Thickness-weighted mean of a layer column over [top, bottom] cm (SLB = layer bottom)."""
    total = weight = 0.0
    layer_top = 0.0
    for layer in layers:
        layer_bottom = layer["SLB"]
        overlap = min(layer_bottom, bottom) - max(layer_top, top)
        layer_top = layer_bottom
        value = layer.get(column)
        if overlap > 0 and value is not None:
            total += value * overlap
            weight += overlap
    return total / weight if weight else None


def _usda_texture_class(sand: float, silt: float, clay: float) -> Optional[str]:
    """USDA soil texture triangle."""
    if silt + 1.5 * clay < 15:
        return "Sand"
    if silt + 2 * clay < 30:
        return "Loamy Sand"
    if (7 <= clay < 20 and sand > 52) or (clay < 7 and silt < 50):
        return "Sandy Loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "Loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "Silt Loam"
    if silt >= 80 and clay < 12:
        return "Silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "Sandy Clay Loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "Clay Loam"
    if 27 <= clay < 40 and sand <= 20:
        return "Silty Clay Loam"
    if clay >= 35 and sand > 45:
        return "Sandy Clay"
    if clay >= 40 and silt >= 40:
        return "Silty Clay"
    if clay >= 40:
        return "Clay"
    return None


def _get_ghr_profile(latitude: float, longitude: float, depths: list, requested: list,
                     include_soil_type: bool, isda_error: str) -> dict:
    retrieved_at = datetime.now(timezone.utc).isoformat()

    alias_of = {v: k for k, v in SOIL_PROPERTY_ALIASES.items()}
    friendly_names, unknown = [], []
    for p in requested:
        friendly = alias_of.get(p, p)  # raw iSDA name → friendly name
        (friendly_names if friendly in SOIL_PROPERTY_ALIASES else unknown).append(friendly)
    if unknown:
        return _error(f"Unknown properties {unknown}. Valid: {sorted(SOIL_PROPERTY_ALIASES)}",
                      input_error=True)
    friendly_names = list(dict.fromkeys(friendly_names))

    with ThreadPoolExecutor(max_workers=1) as pool:
        wrb_future = pool.submit(_fetch_wrb_soil_type, latitude, longitude) if include_soil_type else None
        try:
            site_id = _ghr_site_id(latitude, longitude)
            profile = _parse_ghr_profile(_ghr_profile_text(site_id))
        except FileNotFoundError as e:
            if Path(e.filename).suffix == ".SOL":
                return _error(f"no GHR profile file for this country ({Path(e.filename).name} "
                              f"missing in {GHR_SOL_DIR})")
            return _error(f"GHR soil data not found ({e.filename}); set GHR_SOIL_DIR in .env")
        except Exception as e:
            return _error(str(e))
        finally:
            wrb = wrb_future.result() if wrb_future else None

    # ── Depth-weighted values for each requested depth ──
    layers = profile["layers"]
    per_depth = {}
    for depth in depths:
        top, bottom = (float(x) for x in depth.split("-"))
        row = {name: _ghr_depth_mean(layers, col, top, bottom) for name, (col, *_) in GHR_PROPERTIES.items()}
        row = {name: (v * GHR_PROPERTIES[name][1] if v is not None else None) for name, v in row.items()}
        if row["clay"] is not None and row["silt"] is not None:
            row["sand"] = max(0.0, 100 - row["clay"] - row["silt"])
            row["texture"] = _usda_texture_class(row["sand"], row["silt"], row["clay"])
        per_depth[depth] = row

    props, errors = {}, {}
    for friendly in friendly_names:
        if friendly in GHR_PROPERTIES:
            unit, description = GHR_PROPERTIES[friendly][2], GHR_PROPERTIES[friendly][3]
        elif friendly in GHR_DERIVED:
            unit, description = GHR_DERIVED[friendly]
        else:
            errors[friendly] = "Not available outside iSDAsoil coverage (GHR global profiles lack it)"
            continue
        values = [
            {"depth": depth,
             "value": v if isinstance(v, str) else round(v, 2),
             "range_90pct": None}
            for depth in depths
            if (v := per_depth[depth].get(friendly)) is not None
        ]
        if not values:
            errors[friendly] = "No value in the GHR profile for this location"
            continue
        props[friendly] = {"description": description, "unit": unit, "values": values}

    if not props:
        return _error(f"None of the requested properties are available from GHR: "
                      f"{'; '.join(f'{k}: {v}' for k, v in errors.items())}", property_errors=errors)

    by_depth = _summarize_by_depth(props, depths)
    for depth in depths:
        top, bottom = (float(x) for x in depth.split("-"))
        water = {name: _ghr_depth_mean(layers, col, top, bottom) for name, col in GHR_WATER_COLUMNS.items()}
        if water["wilting_point_cm3_cm3"] is not None and water["field_capacity_cm3_cm3"] is not None:
            water["available_water_mm_per_m"] = (water["field_capacity_cm3_cm3"]
                                                 - water["wilting_point_cm3_cm3"]) * 1000
        by_depth[depth].update({k: round(v, 3) for k, v in water.items() if v is not None})

    return {
        "ok": True,
        "error": None,
        "location": {"latitude": latitude, "longitude": longitude},
        "depths_cm": depths,
        "soil_type": {
            "wrb_class": wrb["wrb_class"] if wrb else None,
            "wrb_probability_pct": wrb["wrb_probability_pct"] if wrb else None,
            "wrb_alternatives": wrb["wrb_alternatives"] if wrb else [],
            "fertility_capability_classification": None,
            "sources": "WRB: ISRIC SoilGrids 2.0 (250 m, probabilistic)",
            "wrb_error": (wrb or {}).get("error") if include_soil_type else "not requested",
        },
        "by_depth": by_depth,
        "properties": props,
        "property_errors": errors,
        "metadata": {
            "provider": "eGHR global soil profiles (ISRIC SoilGrids + HC27, DSSAT format)",
            "resolution": "~10 km (5 arc-minute grid)",
            "coverage": "Global",
            "retrieved_at": retrieved_at,
            "ghr_site_id": profile["site_id"],
            "ghr_profile_location": {"latitude": profile["latitude"], "longitude": profile["longitude"]},
            "notes": [
                f"Fallback source used because iSDAsoil was not available: {isda_error}.",
                "Values are thickness-weighted averages of the DSSAT profile layers (0-5, 5-15, 15-30, "
                "30-60, 60-100, 100-200 cm) over each requested depth; no uncertainty ranges.",
                "organic_carbon and nitrogen come from a few generic HC27 classes (only 3-13 distinct values "
                "per country), so organic matter is a rough class, not a site estimate; clay, silt, pH, CEC, "
                "bulk density and the water limits vary by location.",
                "sand = 100 - clay - silt; texture_class is derived from these with the USDA texture triangle.",
                "Wilting point, field capacity and saturation are volumetric water contents (cm³/cm³); "
                "available_water_mm_per_m = (field capacity - wilting point) × 1000.",
                "Coarse ~10 km grid cell: a regional typical soil, not field-specific.",
                f"organic_matter_pct_est = organic carbon % × {VAN_BEMMELEN_FACTOR} (van Bemmelen factor).",
            ],
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_soil_profile(1.0157, 34.9865, depths=["0-20", "20-50"]), indent=2))
    print(json.dumps(get_soil_profile(40.7, -89.4, depths=["0-20", "20-50"], include_soil_type=False), indent=2))
