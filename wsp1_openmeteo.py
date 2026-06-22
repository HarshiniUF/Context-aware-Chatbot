"""
=============================================================
WSP PROTOTYPE 1: Open-Meteo
Agricultural Chatbot - Weather Service Provider Integration
=============================================================

SETUP:
  pip install openmeteo-requests requests-cache retry-requests
  pip install langchain langchain-openai python-dotenv

.env file required:
  OPENAI_API_KEY=your-navigator-key
  CLIENT_ID=your-client-id
  CLIENT_SECRET=your-client-secret
=============================================================
"""

import openmeteo_requests
import requests_cache
import pandas as pd
import json
from datetime import datetime, timezone
from retry_requests import retry
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from wsp_config import get_llm, UNIFIED_PROMPT

# ─────────────────────────────────────────────────────────────
# 1. CONFIGURATION
# ─────────────────────────────────────────────────────────────

load_dotenv()
llm = get_llm()

PROVIDER_NAME     = "Open-Meteo (free, high-resolution daily forecast, ~1 km)"
FORECAST_RANGE    = "1–16 days"
RAIN_THRESHOLD_MM = 1.0


# ─────────────────────────────────────────────────────────────
# 2. WEATHER FETCHER
# ─────────────────────────────────────────────────────────────

def fetch_openmeteo_forecast(latitude: float, longitude: float, forecast_days: int = 16, start_date: str = None) -> dict:
    cache_session = requests_cache.CachedSession(".openmeteo_cache", expire_after=3600)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    client = openmeteo_requests.Client(session=retry_session)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ["precipitation_sum", "precipitation_probability_max"],
        "timezone": "auto",
    }
    # Remember the original requested start_date (provenance)
    orig_requested_start = start_date

    # Provider limits: Open-Meteo supports up to ~16 days per request (provider-dependent)
    PROVIDER_MAX_DAYS = 16
    provider_days = min(forecast_days, PROVIDER_MAX_DAYS)

    # If start_date provided, request a window starting at start_date for provider_days
    try:
        if start_date:
            from datetime import datetime
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            params["start_date"] = sd.strftime("%Y-%m-%d")
        params["forecast_days"] = provider_days
    except Exception:
        params["forecast_days"] = provider_days

    # Try the request; if provider rejects (e.g., start_date out-of-range or invalid forecast_days),
    # first try a reduced window (provider_days already capped), then fall back to no start_date.
    fallback_used = False
    try:
        response = client.weather_api("https://api.open-meteo.com/v1/forecast", params=params)[0]
    except Exception:
        # If first attempt failed and we had requested a larger window, try with provider max days explicitly
        try:
            params["forecast_days"] = PROVIDER_MAX_DAYS
            response = client.weather_api("https://api.open-meteo.com/v1/forecast", params=params)[0]
        except Exception:
            # Final fallback: remove start_date and request the provider's recent window
            try:
                params.pop("start_date", None)
                params["forecast_days"] = PROVIDER_MAX_DAYS
                response = client.weather_api("https://api.open-meteo.com/v1/forecast", params=params)[0]
                fallback_used = True
            except Exception:
                raise

    daily  = response.Daily()
    start  = pd.Timestamp(daily.Time(), unit="s", tz="UTC")
    end    = pd.Timestamp(daily.TimeEnd(), unit="s", tz="UTC")
    dates  = pd.date_range(start=start, end=end,
                           freq=pd.Timedelta(seconds=daily.Interval()), inclusive="left")

    precip_sum  = daily.Variables(0).ValuesAsNumpy()
    precip_prob = daily.Variables(1).ValuesAsNumpy()

    # Build daily records
    daily_records = [
            {
                "date"                         : d.strftime("%Y-%m-%d"),
                "precipitation_mm"             : round(float(precip_sum[i]), 2),
                "precipitation_probability_pct": round(float(precip_prob[i]), 1),
            }
            for i, d in enumerate(dates)
        ]

    # If the caller requested a start_date but provider fell back, trim the returned
    # records to start at the requested date (so we 'start from that date then fetch
    # till where it can fetch'). This returns only the overlapping tail of the
    # provider response that is on/after the requested date.
    if orig_requested_start and fallback_used:
        try:
            from datetime import datetime as _dt
            req_dt = _dt.strptime(orig_requested_start, "%Y-%m-%d").date()
            filtered = [r for r in daily_records if _dt.strptime(r["date"], "%Y-%m-%d").date() >= req_dt]
            daily_records = filtered
        except Exception:
            # If parsing fails, leave daily_records as-is
            pass

    result = {
        "provider"      : PROVIDER_NAME,
        "latitude"      : latitude,
        "longitude"     : longitude,
        "forecast_days" : forecast_days,
        "daily"         : daily_records,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        # Provenance: record original requested start date (even if provider rejected it)
        "requested_start_date": orig_requested_start,
        "fetched_start_date": dates[0].strftime("%Y-%m-%d") if len(dates) > 0 else None,
        "fetched_end_date": dates[-1].strftime("%Y-%m-%d") if len(dates) > 0 else None,
        # Whether the provider actually returned data starting at the requested start_date
        "start_date_honored": (not fallback_used and orig_requested_start is not None and orig_requested_start == (dates[0].strftime("%Y-%m-%d") if len(dates) > 0 else None)),
    }

    return result


# ─────────────────────────────────────────────────────────────
# 3. RAIN ANALYSIS
# ─────────────────────────────────────────────────────────────

def analyse_rain(forecast: dict) -> dict:
    daily      = forecast["daily"]
    rainy_days = [d for d in daily if d["precipitation_mm"] >= RAIN_THRESHOLD_MM]
    max_day    = max(daily, key=lambda d: d["precipitation_mm"])
    return {
        "has_rainy_event"        : len(rainy_days) > 0,
        "num_rainy_days"         : len(rainy_days),
        "next_rainy_day"         : rainy_days[0]["date"] if rainy_days else None,
        "total_forecast_rain_mm" : round(sum(d["precipitation_mm"] for d in rainy_days), 2),
        "peak_rain_day"          : max_day["date"],
        "peak_rain_mm"           : max_day["precipitation_mm"],
        "rainy_days_detail"      : rainy_days,
    }


# ─────────────────────────────────────────────────────────────
# 4. ANSWER GENERATOR
# ─────────────────────────────────────────────────────────────

def answer_with_weather(
    user_question : str,
    farmer_context: dict,
    latitude      : float,
    longitude     : float,
    forecast_days : int = 16,
) -> str:
    try:
        forecast = fetch_openmeteo_forecast(latitude, longitude, forecast_days)
    except Exception as e:
        return f"⚠️ Could not fetch Open-Meteo data: {e}"

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
# 5. CHATBOT LOOP
# ─────────────────────────────────────────────────────────────

def run_chatbot():
    farmer_context = {
        "crop"               : "Maize",
        "region"             : "Trans Nzoia, Kenya (Kitale Highlands)",
        "latitude"           : 1.0167,
        "longitude"          : 35.0000,
        "agroecological_zone": "Humid Highland (AEZ IIa)",
        "altitude_m"         : 1890,
        "season"             : "Long Rains (MAM)",
        "year"               : 2025,
        "scale_ha"           : 2.5,
        "irrigation"         : "Rain-fed only",
    }
    lat, lon = farmer_context["latitude"], farmer_context["longitude"]

    print("=" * 60)
    print("  Agricultural Chatbot — WSP 1: Open-Meteo")
    print("=" * 60)
    print(f"  Location : {farmer_context['region']}")
    print(f"  Crop     : {farmer_context['crop']}")
    print(f"  LLM      : NaviGator API (UF) | Model: gpt-5")
    print("  Type 'quit' to exit.")
    print("=" * 60)

    while True:
        user_input = input("\n🌾 Your question: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye! 🌦️")
            break
        if not user_input:
            continue
        print("\n⏳ Fetching Open-Meteo forecast and generating answer...\n")
        answer = answer_with_weather(user_input, farmer_context, lat, lon)
        print("─" * 60)
        print(answer)
        print("─" * 60)


def run_demo():
    farmer_context = {
        "crop": "Maize", "region": "Trans Nzoia, Kenya (Kitale Highlands)",
        "agroecological_zone": "Humid Highland", "season": "Long Rains (MAM)",
        "scale_ha": 2.5, "irrigation": "Rain-fed only",
    }
    for q in [
        "Can I still add urea to my rice when it has started producing?",
        "Is it safe to spray fungicide this week?",
        "When should I plant my maize seeds?",
    ]:
        print(f"\n{'='*60}\nQ: {q}\n{'='*60}")
        print(answer_with_weather(q, farmer_context, 1.0167, 35.0000))


if __name__ == "__main__":
    import sys
    run_demo() if len(sys.argv) > 1 and sys.argv[1] == "demo" else run_chatbot()