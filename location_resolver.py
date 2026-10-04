"""
=============================================================
LOCATION RESOLVER — resolve_location tool
Place name or farm coordinates → coordinates, timezone,
ambiguity, location precision
=============================================================

Uses the GeoNames API (same service as the DSSAT project):
  https://secure.geonames.org/searchJSON     (place search)
  https://secure.geonames.org/timezoneJSON   (timezone for raw coordinates)
Requires a free GeoNames account: GEONAMES_USERNAME in .env

Covers towns, villages, counties/districts, states/provinces, regions
and countries. Matching is STRICT first: only results whose name (or an
official alternate name, ignoring accents and words like "County"/"Region")
equals the requested place are accepted. If nothing matches, a fuzzy
search is tried (catches typos like "Nairobbi") and its results are
returned as match="approximate", to be confirmed by the user.

Output (dict):
  {
    "query": str,                    # what was asked for
    "found": bool,
    "name": str,                     # e.g. "Kitale, Trans Nzoia, Kenya"
    "latitude": float, "longitude": float,
    "country": str, "admin1": str,
    "timezone": str,                 # e.g. "Africa/Nairobi"
    "precision": str,                # "exact point" | "city/town/village" | "district/county" | ...
    "match": str,                    # "coordinates" | "exact" | "approximate"
    "ambiguous": bool,               # True if several different places match
    "candidates": [ {name, latitude, longitude, country, admin1, timezone, precision}, ... ],
    "error": str or None,
  }
=============================================================
"""

import math
import os
import re
import unicodedata
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

GEONAMES_SEARCH_URL = "https://secure.geonames.org/searchJSON"
GEONAMES_TIMEZONE_URL = "https://secure.geonames.org/timezoneJSON"
OPENMETEO_TIMEZONE_URL = "https://api.open-meteo.com/v1/forecast"  # fallback only (e.g. over the ocean)
SEARCH_ROWS = 30          # results fetched per search (filtered down afterwards)
MAX_CANDIDATES = 10
FUZZY_STRENGTHS = (0.8, 0.6)  # GeoNames fuzzy search (1.0 = exact), tried in order only when nothing matches
                              # exactly; 0.6 is the DSSAT project's default
DUPLICATE_RADIUS_KM = 25  # same-name entries this close, in the same region, are one place
REQUEST_TIMEOUT_S = 15

# Feature types a farm can be "in": populated places, administrative areas,
# and a few named regions/landforms. Airports, schools, lakes, streams… are dropped.
PLACE_FEATURE_CLASSES = {"P", "A"}
PLACE_FEATURE_CODES = {"RGN", "AREA", "PLN", "PLAT", "VAL", "MT", "MTS", "HLL"}

# Words that describe an administrative level rather than name the place
_ADMIN_WORDS = {"county", "region", "province", "state", "district", "department",
                "division", "municipality", "prefecture", "governorate", "of", "de", "la", "le", "du"}
_ADMIN_WORDS_IN_QUERY = {"county", "region", "province", "state", "district", "department"}
# Leading filler from free text, e.g. "near Nairobi"
_FILLER_PREFIX = re.compile(r"^(?:near|around|close to|outside(?: of)?|in|at|my farm (?:is )?in)\s+", re.IGNORECASE)
# Common country nicknames → GeoNames country codes
_COUNTRY_ALIASES = {"usa": "US", "us": "US", "united states of america": "US", "america": "US",
                    "uk": "GB", "britain": "GB", "england": "GB", "drc": "CD", "dr congo": "CD",
                    "ivory coast": "CI", "cote d ivoire": "CI"}

# "1.0157, 34.9865" or "lat 1.0157 lon 34.9865" → (lat, lon)
_COORD_PATTERN = re.compile(
    r"(?:lat(?:itude)?\s*[:=]?\s*)?(-?\d{1,3}(?:\.\d+)?)\s*[,;\s]\s*(?:lon(?:gitude)?\s*[:=]?\s*)?(-?\d{1,3}(?:\.\d+)?)",
    re.IGNORECASE,
)


def _coordinate_pair(text: str) -> Optional[tuple]:
    """(lat, lon) if the text looks like a coordinate pair (range not checked), else None."""
    if not text:
        return None
    match = _COORD_PATTERN.fullmatch(text.strip())
    return (float(match.group(1)), float(match.group(2))) if match else None


def parse_coordinates(text: str) -> Optional[tuple]:
    """Return (lat, lon) if the text is a valid decimal coordinate pair, else None."""
    pair = _coordinate_pair(text)
    if pair and -90 <= pair[0] <= 90 and -180 <= pair[1] <= 180:
        return pair
    return None


def _normalize(text: str, drop_admin_words: bool = True) -> str:
    """Lowercase, strip accents and punctuation: 'Région de Thiès' → 'thies', 'Trans-Nzoia County' → 'trans nzoia'."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    if drop_admin_words:
        kept = [w for w in words if w not in _ADMIN_WORDS]
        words = kept or words
    return " ".join(words)


def _precision_from_feature_code(code: Optional[str]) -> str:
    """Map a GeoNames feature code to a human-readable precision level."""
    code = code or ""
    if code.startswith("PCL"):
        return "country"
    if code.startswith("ADM1"):        # ADM1, ADM1H (former province, e.g. Rift Valley)
        return "state/province"
    if code.startswith("ADM2"):
        return "district/county"
    if code == "ADMD":
        return "administrative area"
    if code.startswith("ADM"):
        return "sub-district"
    if code.startswith("PPL"):
        return "city/town/village"
    if code in ("RGN", "AREA", "PLN", "PLAT", "VAL"):
        return "region"
    return "named place"


def _timezone_of(item: dict) -> Optional[str]:
    tz = item.get("timezone")
    return tz.get("timeZoneId") if isinstance(tz, dict) else None


def _format_candidate(item: dict) -> dict:
    parts = []
    for p in (item.get("name"), item.get("adminName1"), item.get("countryName")):
        if p and p not in parts:
            parts.append(p)
    return {
        "name": ", ".join(parts),
        "latitude": float(item["lat"]),
        "longitude": float(item["lng"]),
        "country": item.get("countryName"),
        "admin1": item.get("adminName1") or None,
        "timezone": _timezone_of(item),
        "precision": _precision_from_feature_code(item.get("fcode")),
    }


def _distance_km(a: dict, b: dict) -> float:
    """Approximate great-circle distance between two candidates."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _drop_near_duplicates(candidates: list) -> list:
    """GeoNames often lists one place several times (town + district + region); keep the first of each cluster."""
    kept = []
    for c in candidates:
        if not any(c["country"] == k["country"] and c["admin1"] == k["admin1"]
                   and _distance_km(c, k) < DUPLICATE_RADIUS_KM for k in kept):
            kept.append(c)
    return kept


def _is_place(item: dict) -> bool:
    return (item.get("fcl") in PLACE_FEATURE_CLASSES or item.get("fcode") in PLACE_FEATURE_CODES) \
        and item.get("lat") is not None and item.get("lng") is not None


def _names_of(item: dict) -> set:
    """All normalized names of a GeoNames entry: name, official name, ASCII name, alternate names."""
    names = {item.get("name"), item.get("toponymName"), item.get("asciiName")}
    names.update(a.get("name") for a in item.get("alternateNames") or [] if isinstance(a, dict))
    return {_normalize(n) for n in names if n}


def _matches_qualifiers(item: dict, qualifiers: list) -> bool:
    """True if every qualifier (e.g. 'Kenya', 'Trans Nzoia', 'USA') matches the entry's country/admin fields."""
    fields = [_normalize(item.get(k, "") or "") for k in ("countryName", "adminName1", "adminName2", "adminName3")]
    fields = [f for f in fields if f]
    code = (item.get("countryCode") or "").upper()
    for q in qualifiers:
        nq = _normalize(q)
        if _COUNTRY_ALIASES.get(nq) == code or nq.upper() == code:
            continue
        if not any(nq in f or f in nq for f in fields):
            return False
    return True


class GeoNamesError(Exception):
    pass


def _username() -> str:
    username = os.getenv("GEONAMES_USERNAME", "").strip()
    if not username:
        raise GeoNamesError("GEONAMES_USERNAME is not set. Add GEONAMES_USERNAME=<your username> to .env.")
    return username


def _search(name: str, fuzzy: Optional[float] = None) -> list:
    """GeoNames place-name search (style=FULL for timezone and alternate names)."""
    params = {"name": name, "maxRows": SEARCH_ROWS, "style": "FULL", "username": _username()}
    if fuzzy is not None:
        params["fuzzy"] = fuzzy
    response = requests.get(GEONAMES_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    data = response.json()
    if "status" in data:  # GeoNames reports errors (bad username, credits exceeded…) with HTTP 200
        raise GeoNamesError(data["status"].get("message", "unknown GeoNames error"))
    return [g for g in data.get("geonames", []) if _is_place(g)]


def lookup_timezone(latitude: float, longitude: float) -> Optional[str]:
    """IANA timezone for a coordinate pair (GeoNames; Open-Meteo as fallback, e.g. over water)."""
    try:
        response = requests.get(GEONAMES_TIMEZONE_URL, timeout=REQUEST_TIMEOUT_S,
                                params={"lat": latitude, "lng": longitude, "username": _username()})
        response.raise_for_status()
        tz = response.json().get("timezoneId")
        if tz:
            return tz
    except Exception:
        pass
    try:
        response = requests.get(OPENMETEO_TIMEZONE_URL, timeout=REQUEST_TIMEOUT_S,
                                params={"latitude": latitude, "longitude": longitude, "timezone": "auto"})
        response.raise_for_status()
        return response.json().get("timezone")
    except Exception:
        return None


def _empty_result(query: str, error: Optional[str] = None) -> dict:
    return {
        "query": query, "found": False, "name": None,
        "latitude": None, "longitude": None, "country": None, "admin1": None,
        "timezone": None, "precision": None, "match": None,
        "ambiguous": False, "candidates": [], "error": error,
    }


def resolve_location(place: Optional[str] = None,
                     latitude: Optional[float] = None,
                     longitude: Optional[float] = None) -> dict:
    """
    Resolve a place name or farm coordinates.

    - If latitude/longitude are given (or `place` is a coordinate pair), they are
      passed through untouched (no geocoding) with precision "exact point".
    - Otherwise `place` is looked up in GeoNames. "Name, Region, Country" qualifiers
      after the first comma are used to filter candidates.
    """
    if latitude is None and longitude is None and place:
        pair = _coordinate_pair(place)
        if pair:
            latitude, longitude = pair

    # ── Coordinates given: pass through, no geocoding ──
    if latitude is not None and longitude is not None:
        query = place or f"{latitude}, {longitude}"
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return _empty_result(query, f"Invalid coordinates ({latitude}, {longitude}): latitude must be "
                                        "between -90 and 90 and longitude between -180 and 180.")
        return {
            "query": query, "found": True,
            "name": "Your farm coordinates",
            "latitude": float(latitude), "longitude": float(longitude),
            "country": None, "admin1": None,
            "timezone": lookup_timezone(latitude, longitude),
            "precision": "exact point", "match": "coordinates",
            "ambiguous": False, "candidates": [], "error": None,
        }

    if not place or not place.strip():
        return _empty_result(place or "", "No place name or coordinates given.")

    query = place.strip()
    parts = [p.strip() for p in _FILLER_PREFIX.sub("", query).split(",") if p.strip()]
    if not parts:
        return _empty_result(query, "No place name or coordinates given.")
    name, qualifiers = parts[0], parts[1:]

    try:
        items = _search(name)
        # "Kitale Kenya" (no comma) may return nothing — retry with the last word as a qualifier
        # (not when the last word is "County"/"Region"…, which the admin-word retry below handles)
        if not items and not qualifiers and " " in name \
                and _normalize(name.rsplit(" ", 1)[1], drop_admin_words=False) not in _ADMIN_WORDS:
            head, tail = name.rsplit(" ", 1)
            retry = _search(head)
            if retry:
                items, name, qualifiers = retry, head, [tail]
        if qualifiers:
            items = [g for g in items if _matches_qualifiers(g, qualifiers)]

        # Strict match first (name or an alternate name, ignoring accents / admin words)
        wanted = _normalize(name)
        exact = [g for g in items if wanted in _names_of(g)]
        if not exact:
            # "Trans-Nzoia County" finds nothing in GeoNames, "Trans-Nzoia" does → retry without admin words
            core = " ".join(w for w in name.split() if _normalize(w, drop_admin_words=False) not in _ADMIN_WORDS)
            if core and core != name:
                retry = _search(core)
                if qualifiers:
                    retry = [g for g in retry if _matches_qualifiers(g, qualifiers)]
                exact = [g for g in retry if wanted in _names_of(g)]
        match = "exact"
        for strength in FUZZY_STRENGTHS:
            if exact:
                break
            # Fuzzy search catches typos ("Nairobbi" → Nairobi); the user must confirm these
            # (continent-scale entries like "Western Asia" have no country; useless for a farm)
            exact = [g for g in _search(name, fuzzy=strength) if g.get("countryCode")]
            if qualifiers:
                exact = [g for g in exact if _matches_qualifiers(g, qualifiers)]
            match = "approximate"
    except GeoNamesError as e:
        return _empty_result(query, f"GeoNames error: {e}")
    except Exception as e:
        return _empty_result(query, f"Geocoding service error: {e}")

    if not exact:
        return _empty_result(query, f"No place named '{query}' was found.")

    # "Kaolack Region" / "Trans Nzoia County" → prefer administrative areas over same-named towns
    if set(_normalize(name, drop_admin_words=False).split()) & _ADMIN_WORDS_IN_QUERY:
        exact.sort(key=lambda g: g.get("fcl") != "A")  # stable: keeps GeoNames relevance order otherwise

    candidates = _drop_near_duplicates([_format_candidate(g) for g in exact])[:MAX_CANDIDATES]
    best = candidates[0]  # GeoNames ranks by relevance (name match, population, feature importance)
    return {
        "query": query, "found": True,
        "name": best["name"],
        "latitude": best["latitude"], "longitude": best["longitude"],
        "country": best["country"], "admin1": best["admin1"],
        "timezone": best["timezone"],
        "precision": best["precision"], "match": match,
        "ambiguous": len(candidates) > 1,
        "candidates": candidates,
        "error": None,
    }


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(resolve_location(" ".join(sys.argv[1:]) or "Kitale, Kenya"), indent=2))
