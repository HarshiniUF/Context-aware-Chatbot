"""
=============================================================
WSP PROTOTYPE 2: CHC (CHIRPS-GEFS)
Agricultural Chatbot - Weather Service Provider Integration
=============================================================

SETUP:
  pip install climateserv requests pandas langchain langchain-openai python-dotenv

.env file required:
  OPENAI_API_KEY=your-navigator-key
  CLIENT_ID=your-client-id
  CLIENT_SECRET=your-client-secret
=============================================================
"""

import climateserv
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from wsp_config import get_llm, UNIFIED_PROMPT, LLM_MODEL

# ─────────────────────────────────────────────────────────────
# 1. CONFIGURATION
# ─────────────────────────────────────────────────────────────

load_dotenv()
llm = get_llm()

PROVIDER_NAME     = "CHC CHIRPS-GEFS via ClimateSERV (bias-corrected, 0.05° resolution)"
FORECAST_RANGE    = "1–15 days"
DATASET_TYPE_ID   = 26
RAIN_THRESHOLD_MM = 1.0

# Set to True once to print the raw API response and understand its structure
DEBUG_RESPONSE = False


# ─────────────────────────────────────────────────────────────
# 2. RESPONSE NORMALISER
# ─────────────────────────────────────────────────────────────

def _extract_records(raw) -> list:
    """
    ClimateSERV can return data in several shapes.
    This function normalises any shape into:
        [{"date": "YYYY-MM-DD", "value": <float or dict>}, ...]

    Supported shapes:
      Shape A — list of dicts:
          [{"date": "...", "value": ...}, ...]

      Shape B — JSON string of the above:
          '[{"date": "...", "value": ...}, ...]'

      Shape C — dict with a data/results/features key:
          {"data": [...]}
          {"results": [...]}
          {"features": [...]}

      Shape D — dict with "type":"FeatureCollection" (GeoJSON):
          {"type": "FeatureCollection", "features": [
              {"properties": {"date": "...", "value": ...}}, ...
          ]}

      Shape E — dict whose values are themselves dicts keyed by date:
          {"2026-03-18": {"avg": 3.2}, "2026-03-19": {"avg": 1.1}, ...}
    """

    # ── Shape B: JSON string ────────────────────────────────
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Cannot parse JSON string from ClimateSERV: {e}\nRaw: {raw[:300]}")

    # ── Shape A: already a flat list ───────────────────────
    if isinstance(raw, list):
        normalised = []
        for item in raw:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except Exception:
                    continue
            if isinstance(item, dict):
                normalised.append(item)
        return normalised

    # ── Shape C / D / E: dict ──────────────────────────────
    if isinstance(raw, dict):
        # Shape C — explicit data/results key
        for key in ("data", "results", "records", "timeseries", "values"):
            if key in raw and isinstance(raw[key], list):
                return _extract_records(raw[key])   # recurse with the list

        # Shape D — GeoJSON FeatureCollection
        if raw.get("type") == "FeatureCollection" and "features" in raw:
            records = []
            for feat in raw["features"]:
                props = feat.get("properties", {})
                if "date" in props or "value" in props:
                    records.append(props)
            if records:
                return records

        # Shape E — dict whose keys look like dates
        sample_keys = list(raw.keys())[:5]
        if all(_looks_like_date(k) for k in sample_keys):
            return [{"date": k, "value": v} for k, v in raw.items()]

        # Last resort: check if ANY value in the dict is a list
        for v in raw.values():
            if isinstance(v, list) and len(v) > 0:
                return _extract_records(v)

        raise RuntimeError(
            f"ClimateSERV returned a dict with unrecognised structure.\n"
            f"Keys: {list(raw.keys())}\n"
            f"Sample: {json.dumps(dict(list(raw.items())[:3]), indent=2)}"
        )

    raise RuntimeError(f"ClimateSERV returned unhandled type: {type(raw)}")


def _looks_like_date(s: str) -> bool:
    """Returns True if string looks like YYYY-MM-DD or MM/DD/YYYY."""
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        pass
    try:
        datetime.strptime(s, "%m/%d/%Y")
        return True
    except Exception:
        return False


def _extract_mm(val_field) -> float:
    """Extracts a float mm value from a value field that may be nested."""
    if val_field is None:
        return 0.0
    if isinstance(val_field, (int, float)):
        return max(float(val_field), 0.0)
    if isinstance(val_field, dict):
        # Try common keys in order of preference
        for key in ("avg", "mean", "value", "max", "min", "total", "sum"):
            if key in val_field and isinstance(val_field[key], (int, float)):
                return max(float(val_field[key]), 0.0)
        # Fall back to first numeric value found
        for v in val_field.values():
            if isinstance(v, (int, float)):
                return max(float(v), 0.0)
    if isinstance(val_field, str):
        try:
            return max(float(val_field), 0.0)
        except ValueError:
            pass
    return 0.0


# ─────────────────────────────────────────────────────────────
# 3. WEATHER FETCHER
# ─────────────────────────────────────────────────────────────

def fetch_chirpsgefs_forecast(
    latitude     : float,
    longitude    : float,
    forecast_days: int = 15,
) -> dict:
    """
    Fetches daily CHIRPS-GEFS precipitation forecast via ClimateSERV API.
    """
    today    = datetime.now()
    end_date = today + timedelta(days=min(forecast_days, 15))
    delta    = 0.05

    geometry_coords = [
        [longitude - delta, latitude - delta],
        [longitude + delta, latitude - delta],
        [longitude + delta, latitude + delta],
        [longitude - delta, latitude + delta],
        [longitude - delta, latitude - delta],
    ]

    try:
        raw = climateserv.api.request_data(
            DATASET_TYPE_ID,
            "Average",
            today.strftime("%m/%d/%Y"),
            end_date.strftime("%m/%d/%Y"),
            geometry_coords,
            "", "",
            "memory_object",
        )
    except Exception as e:
        raise RuntimeError(f"ClimateSERV API error: {e}")

    # ── Optional debug: print raw response to understand structure ──
    if DEBUG_RESPONSE:
        print("\n[DEBUG] Raw response type:", type(raw))
        try:
            print("[DEBUG] Raw content (first 1500 chars):")
            print(json.dumps(raw, indent=2)[:1500] if not isinstance(raw, str) else raw[:1500])
        except Exception:
            print(repr(raw)[:1500])

    # ── Normalise into a flat list of records ───────────────
    try:
        records = _extract_records(raw)
    except RuntimeError as e:
        # If structure is unknown, enable DEBUG_RESPONSE to investigate
        raise RuntimeError(
            f"{e}\n\n"
            "TIP: Set DEBUG_RESPONSE = True at the top of this file "
            "to print the raw API response and inspect its structure."
        )

    # ── Build clean daily records ───────────────────────────
    daily_records = []
    for record in records:
        # Extract date
        raw_date = record.get("date", record.get("time", record.get("Date", "")))
        try:
            # Handle both YYYY-MM-DD and MM/DD/YYYY formats
            if "-" in str(raw_date):
                parsed_date = datetime.strptime(str(raw_date), "%Y-%m-%d").strftime("%Y-%m-%d")
            else:
                parsed_date = datetime.strptime(str(raw_date), "%m/%d/%Y").strftime("%Y-%m-%d")
        except Exception:
            parsed_date = str(raw_date)

        # Extract mm value
        val_field = record.get("value", record.get("Value", record.get("data", 0.0)))
        mm = _extract_mm(val_field)

        daily_records.append({
            "date"             : parsed_date,
            "precipitation_mm" : round(mm, 2),
        })

    daily_records.sort(key=lambda d: d["date"])

    return {
        "provider"      : PROVIDER_NAME,
        "dataset_id"    : DATASET_TYPE_ID,
        "latitude"      : latitude,
        "longitude"     : longitude,
        "forecast_days" : forecast_days,
        "daily"         : daily_records,
        "fetched_at"    : datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# 4. RAIN ANALYSIS
# ─────────────────────────────────────────────────────────────

def analyse_rain(forecast: dict) -> dict:
    daily      = forecast["daily"]
    rainy_days = [d for d in daily if d["precipitation_mm"] >= RAIN_THRESHOLD_MM]
    max_day    = max(daily, key=lambda d: d["precipitation_mm"]) if daily else {}
    return {
        "has_rainy_event"        : len(rainy_days) > 0,
        "num_rainy_days"         : len(rainy_days),
        "next_rainy_day"         : rainy_days[0]["date"] if rainy_days else None,
        "total_forecast_rain_mm" : round(sum(d["precipitation_mm"] for d in rainy_days), 2),
        "peak_rain_day"          : max_day.get("date", "N/A"),
        "peak_rain_mm"           : max_day.get("precipitation_mm", 0.0),
        "rainy_days_detail"      : rainy_days,
    }


# ─────────────────────────────────────────────────────────────
# 5. ANSWER GENERATOR
# ─────────────────────────────────────────────────────────────

def answer_with_weather(
    user_question : str,
    farmer_context: dict,
    latitude      : float,
    longitude     : float,
    forecast_days : int = 15,
) -> str:
    try:
        forecast = fetch_chirpsgefs_forecast(latitude, longitude, forecast_days)
    except Exception as e:
        return f"⚠️ Could not fetch CHIRPS-GEFS data: {e}"

    rain = analyse_rain(forecast)

    result = llm.invoke(UNIFIED_PROMPT.format_messages(
        farmer_context  = json.dumps(farmer_context, indent=2),
        latitude        = latitude,
        longitude       = longitude,
        provider_name   = PROVIDER_NAME,
        forecast_range  = f"Next {forecast_days} days",
        has_rain        = rain["has_rainy_event"],
        num_rainy_days  = rain["num_rainy_days"],
        next_rainy_day  = rain["next_rainy_day"] or "No rain in forecast window",
        total_rain_mm   = rain["total_forecast_rain_mm"],
        peak_rain_day   = rain["peak_rain_day"],
        peak_rain_mm    = rain["peak_rain_mm"],
        rainy_days_json = json.dumps(rain["rainy_days_detail"], indent=2),
        user_question   = user_question,
    ))
    return result.content.strip()


# ─────────────────────────────────────────────────────────────
# 6. CHATBOT LOOP
# ─────────────────────────────────────────────────────────────

def run_chatbot():
    farmer_context = {
        "crop"               : "Maize",
        "region"             : "Trans Nzoia, Kenya (Kitale Highlands)",
        "agroecological_zone": "Humid Highland (AEZ IIa)",
        "altitude_m"         : 1890,
        "season"             : "Long Rains (MAM)",
        "year"               : 2025,
        "scale_ha"           : 2.5,
        "irrigation"         : "Rain-fed only",
    }
    lat, lon = 1.0167, 35.0000

    print("=" * 60)
    print("  Agricultural Chatbot — WSP 2: CHC CHIRPS-GEFS")
    print("=" * 60)
    print(f"  Location : {farmer_context['region']}")
    print(f"  Crop     : {farmer_context['crop']}")
    print(f"  LLM      : NaviGator API (UF) | Model: {LLM_MODEL}")
    print(f"  Horizon  : {FORECAST_RANGE} (CHIRPS-GEFS daily, bias-corrected)")
    print("  Type 'quit' to exit.")
    print("=" * 60)

    while True:
        user_input = input("\n🌾 Your question: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye! 🌦️")
            break
        if not user_input:
            continue
        print("\n⏳ Fetching CHIRPS-GEFS forecast and generating answer...\n")
        answer = answer_with_weather(user_input, farmer_context, lat, lon)
        print("─" * 60)
        print(answer)
        print("─" * 60)


if __name__ == "__main__":
    run_chatbot()