"""
=============================================================
SOIL TOOL — get_soil_profile
Coordinates, depth range, properties → soil type, texture,
organic matter (+ any requested iSDAsoil property)
=============================================================

Uses the iSDAsoil v2 REST API (Africa only, 30 m resolution).
Credentials: ISDASOIL_USERNAME / ISDASOIL_PASSWORD in .env
(login + token caching reused from wsp_soil_isda.get_isda_token).

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

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

import requests

from wsp_soil_isda import get_isda_token, ISDA_LAYERS_ENDPOINT, ISDA_SOILPROPERTY_ENDPOINT

SOILGRIDS_WRB_URL = "https://rest.isric.org/soilgrids/v2.0/classification/query"
SOILGRIDS_TIMEOUT_S = 30
VALID_DEPTHS = ["0-20", "20-50"]
DEFAULT_DEPTHS = ["0-20"]
REQUEST_TIMEOUT_S = 20
VAN_BEMMELEN_FACTOR = 1.724  # organic matter ≈ organic carbon × 1.724

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


def get_soil_profile(latitude: float,
                     longitude: float,
                     depths: Optional[list] = None,
                     properties: Optional[list] = None,
                     include_soil_type: bool = True) -> dict:
    """
    Soil profile for a location in Africa.

    Args:
        latitude, longitude: location in decimal degrees
        depths: list of "0-20" and/or "20-50" (cm); default ["0-20"]
        properties: friendly names (see SOIL_PROPERTY_ALIASES) or raw iSDAsoil names;
                    default: texture, sand, silt, clay, organic_carbon, fertility_constraints
        include_soil_type: also query SoilGrids for the WRB soil type (slow, 10-30 s)
    """
    retrieved_at = datetime.now(timezone.utc).isoformat()

    # ── Validate inputs ──
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _error(f"Invalid coordinates: lat={latitude}, lon={longitude}")
    depths = list(dict.fromkeys(depths or DEFAULT_DEPTHS))
    bad_depths = [d for d in depths if d not in VALID_DEPTHS]
    if bad_depths:
        return _error(f"Unsupported depths {bad_depths}. iSDAsoil provides only {VALID_DEPTHS} (cm).")

    try:
        headers = {"Authorization": f"Bearer {get_isda_token()}"}
        catalog = _catalog(headers)
    except Exception as e:
        return _error(f"iSDAsoil authentication/catalog failed: {e}")

    requested = properties or DEFAULT_PROPERTIES
    api_names, unknown = [], []
    for p in requested:
        name = SOIL_PROPERTY_ALIASES.get(p, p)
        (api_names if name in catalog else unknown).append(name)
    if unknown:
        return _error(f"Unknown properties {unknown}. Valid: {sorted(SOIL_PROPERTY_ALIASES)}")
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

    # ── Clean per-depth summary: texture + organic matter ──
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
        "by_depth": by_depth,
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


if __name__ == "__main__":
    import json
    print(json.dumps(get_soil_profile(1.0157, 34.9865, depths=["0-20", "20-50"]), indent=2))
