"""
=============================================================
WSP PROTOTYPE 4: NOAA (CPC / GFS)
Agricultural Chatbot - Weather Service Provider Integration
=============================================================

SETUP:
  pip install openmeteo-requests requests-cache retry-requests
  pip install requests pandas xarray netCDF4 langchain langchain-openai python-dotenv

.env file required:
  OPENAI_API_KEY=your-navigator-key
  CLIENT_ID=your-client-id
  CLIENT_SECRET=your-client-secret

DATA SOURCES:
  PRIMARY  — NOAA GFS via Open-Meteo (global, free, no key, up to 16 days)
  ALT (US) — NOAA NWS API (api.weather.gov, US only, 7-day)
  CONTEXT  — NOAA CPC Observed (PSL NetCDF, recent 7 days observed)
=============================================================
"""

import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from wsp_config import get_llm, UNIFIED_PROMPT, LLM_MODEL

# ─────────────────────────────────────────────────────────────
# 1. CONFIGURATION
# ─────────────────────────────────────────────────────────────

load_dotenv()
llm = get_llm()

PROVIDER_NAME     = "NOAA GFS via Open-Meteo (Global Forecast System, ~25 km)"
FORECAST_RANGE    = "1–16 days"
RAIN_THRESHOLD_MM = 1.0


# ─────────────────────────────────────────────────────────────
# 2A. NOAA GFS VIA OPEN-METEO (global — PRIMARY fetcher)
# ─────────────────────────────────────────────────────────────

def fetch_noaa_gfs_forecast(latitude: float, longitude: float, forecast_days: int = 16) -> dict:
    """
    Fetches NOAA GFS daily precipitation forecast via Open-Meteo's GFS endpoint.
    GFS = NOAA's Global Forecast System, runs 4x/day at ~25 km resolution.
    Same underlying model that feeds NOAA CPC operational products.
    """
    try:
        import openmeteo_requests
        import requests_cache
        from retry_requests import retry
    except ImportError:
        raise ImportError("Install: pip install openmeteo-requests requests-cache retry-requests")

    cache_session = requests_cache.CachedSession(".noaa_gfs_cache", expire_after=3600)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    client        = openmeteo_requests.Client(session=retry_session)

    response = client.weather_api("https://api.open-meteo.com/v1/forecast", params={
        "latitude"    : latitude,
        "longitude"   : longitude,
        "daily"       : ["precipitation_sum", "precipitation_probability_max", "rain_sum"],
        "models"      : "gfs_seamless",
        "forecast_days": forecast_days,
        "timezone"    : "auto",
    })[0]

    daily  = response.Daily()
    start  = pd.Timestamp(daily.Time(), unit="s", tz="UTC")
    end    = pd.Timestamp(daily.TimeEnd(), unit="s", tz="UTC")
    dates  = pd.date_range(start=start, end=end,
                           freq=pd.Timedelta(seconds=daily.Interval()), inclusive="left")

    precip_sum  = daily.Variables(0).ValuesAsNumpy()
    precip_prob = daily.Variables(1).ValuesAsNumpy()
    rain_sum    = daily.Variables(2).ValuesAsNumpy()

    return {
        "provider"      : PROVIDER_NAME,
        "model"         : "GFS Seamless (NOAA)",
        "latitude"      : latitude,
        "longitude"     : longitude,
        "forecast_days" : forecast_days,
        "daily"         : [
            {
                "date"                         : d.strftime("%Y-%m-%d"),
                "precipitation_mm"             : round(float(precip_sum[i]), 2),
                "rain_mm"                      : round(float(rain_sum[i]), 2),
                "precipitation_probability_pct": round(float(precip_prob[i]), 1),
            }
            for i, d in enumerate(dates)
        ],
        "fetched_at": datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# 2B. NOAA NWS API (US only — alternative fetcher)
# ─────────────────────────────────────────────────────────────

def fetch_noaa_nws_forecast(latitude: float, longitude: float) -> dict:
    """
    Fetches 7-day forecast from NOAA NWS API. US locations ONLY.
    Note: mm values are estimated from probability (heuristic).
    """
    headers      = {"User-Agent": "AgriculturalChatbot/1.0 (research@example.com)"}
    r            = requests.get(f"https://api.weather.gov/points/{latitude},{longitude}",
                                headers=headers, timeout=15)
    r.raise_for_status()
    forecast_url = r.json()["properties"]["forecast"]

    r2      = requests.get(forecast_url, headers=headers, timeout=15)
    r2.raise_for_status()
    periods = r2.json()["properties"]["periods"]

    daily_records = {}
    for period in periods:
        date_str = period["startTime"][:10]
        if period.get("isDaytime", True):
            prob   = period.get("probabilityOfPrecipitation", {}).get("value") or 0
            est_mm = round(prob * 0.15, 2)
            daily_records[date_str] = {
                "date"                         : date_str,
                "precipitation_mm"             : est_mm,
                "precipitation_probability_pct": prob,
                "short_forecast"               : period.get("shortForecast", ""),
            }

    return {
        "provider"      : "NOAA NWS API (api.weather.gov, US only)",
        "latitude"      : latitude,
        "longitude"     : longitude,
        "forecast_days" : len(daily_records),
        "daily"         : sorted(daily_records.values(), key=lambda d: d["date"]),
        "fetched_at"    : datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# 2B. NOAA CPC SEASONAL OUTLOOK (Probability-based, 1-3 months)
# ─────────────────────────────────────────────────────────────

def fetch_noaa_cpc_seasonal(latitude: float, longitude: float) -> dict:
    """
    NOAA Climate Prediction Center Seasonal Outlooks.
    Returns probability categories (Above Normal / Normal / Below Normal) for rainfall.
    
    Note: CPC issues monthly probabilities, not actual mm values.
    This is interpreted as a seasonal outlook, not a daily forecast.
    """
    # NOAA CPC doesn't have a direct API for probability grids
    # As a heuristic for this demo, we'll return a typical Long Rains outlook
    # In production, you would scrape from:
    # https://www.cpc.ncep.noaa.gov/products/predictions/multi_season/13_seasonal_outlooks/
    
    today = datetime.utcnow()
    current_month = today.strftime("%Y-%m")
    
    # Generate a 3-month seasonal outlook (heuristic for Long Rains)
    seasonal_months = []
    for i in range(3):
        month_date = today + timedelta(days=30*i)
        month_str = month_date.strftime("%Y-%m")
        
        # Heuristic: Long Rains (Mar-May) typically show above-normal rainfall
        if month_date.month in [3, 4, 5]:  # Long Rains season
            seasonal_months.append({
                "month": month_str,
                "category": "Above Normal",  # Long Rains typical
                "below_normal_prob": 25,
                "normal_prob": 33,
                "above_normal_prob": 42,
                "interpretation": "Higher than usual rainfall expected"
            })
        else:
            seasonal_months.append({
                "month": month_str,
                "category": "Normal",
                "below_normal_prob": 33,
                "normal_prob": 34,
                "above_normal_prob": 33,
                "interpretation": "Rainfall expected to be near normal"
            })
    
    return {
        "provider": "NOAA CPC Seasonal Outlook (Probability Categories)",
        "model": "NOAA Climate Prediction Center",
        "latitude": latitude,
        "longitude": longitude,
        "forecast_type": "probability_outlook",  # NOT daily mm values
        "seasonal_months": seasonal_months,
        "note": "These are probability categories (%), not rainfall amounts. For seasonal crop simulation, combine with ERA5 climatology.",
        "fetched_at": datetime.utcnow().isoformat(),
        # Convert to 'daily' key for compatibility with unified handler
        "daily": [
            {
                "date": m["month"],
                "precipitation_mm": 0,  # CPC doesn't provide mm, only probabilities
                "category": m["category"],
                "above_normal_prob": m["above_normal_prob"],
                "normal_prob": m["normal_prob"],
                "below_normal_prob": m["below_normal_prob"],
            }
            for m in seasonal_months
        ]
    }

  
# ─────────────────────────────────────────────────────────────
# 2C. NOAA CPC OBSERVED (recent context, not forecast)
# ─────────────────────────────────────────────────────────────

def fetch_noaa_cpc_observed(latitude: float, longitude: float) -> dict:
    """
    Fetches NOAA CPC Global Unified Gauge-Based observed precipitation
    (recent 7 days). Useful for context alongside GFS forecast.
    """
    try:
        import xarray as xr
    except ImportError:
        raise ImportError("Install: pip install xarray netCDF4")

    year     = datetime.utcnow().strftime("%Y")
    url      = f"https://downloads.psl.noaa.gov/Datasets/cpc_global_precip/precip.{year}.nc"
    tmp_file = Path(f"/tmp/cpc_precip_{year}.nc")

    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(tmp_file, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    ds       = xr.open_dataset(tmp_file)
    ds_point = ds.sel(lat=latitude, lon=longitude % 360, method="nearest")
    recent   = ds_point["precip"].isel(time=slice(-7, None))

    records = []
    for i in range(len(recent.time)):
        mm = float(recent.values[i])
        records.append({
            "date"             : pd.Timestamp(recent.time.values[i]).strftime("%Y-%m-%d"),
            "precipitation_mm" : round(max(mm, 0.0), 2),
        })

    tmp_file.unlink(missing_ok=True)
    return {"provider": "NOAA CPC Observed (recent 7 days)", "recent_days": records}


# ─────────────────────────────────────────────────────────────
# 3. RAIN ANALYSIS
# ─────────────────────────────────────────────────────────────

def analyse_rain(forecast: dict) -> dict:
    daily      = forecast.get("daily", [])
    rainy_days = [d for d in daily if d.get("precipitation_mm", 0) >= RAIN_THRESHOLD_MM]
    max_day    = max(daily, key=lambda d: d.get("precipitation_mm", 0)) if daily else {}
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
# 4. ANSWER GENERATOR
# ─────────────────────────────────────────────────────────────

def answer_with_weather(
    user_question : str,
    farmer_context: dict,
    latitude      : float,
    longitude     : float,
    forecast_days : int = 16,
    use_us_nws    : bool = False,
) -> str:
    if use_us_nws:
        try:
            forecast      = fetch_noaa_nws_forecast(latitude, longitude)
            provider_used = "NOAA NWS API (US only, 7-day)"
        except Exception as e:
            return f"⚠️ NOAA NWS API error: {e}"
    else:
        try:
            forecast      = fetch_noaa_gfs_forecast(latitude, longitude, forecast_days)
            provider_used = PROVIDER_NAME
        except Exception as e:
            return f"⚠️ NOAA GFS fetch error: {e}"

    rain = analyse_rain(forecast)

    result = llm.invoke(UNIFIED_PROMPT.format_messages(
        farmer_context  = json.dumps(farmer_context, indent=2),
        latitude        = latitude,
        longitude       = longitude,
        provider_name   = provider_used,
        forecast_range  = FORECAST_RANGE,
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
        "agroecological_zone": "Humid Highland (AEZ IIa)",
        "altitude_m"         : 1890,
        "season"             : "Long Rains (MAM)",
        "year"               : 2025,
        "scale_ha"           : 2.5,
        "irrigation"         : "Rain-fed only",
    }
    lat, lon = 1.0167, 35.0000

    print("=" * 65)
    print("  Agricultural Chatbot — WSP 4: NOAA (CPC / GFS)")
    print("=" * 65)
    print(f"  Location : {farmer_context['region']}")
    print(f"  Model    : NOAA GFS (global, via Open-Meteo)")
    print(f"  LLM      : NaviGator API (UF) | Model: {LLM_MODEL}")
    print("  Type 'quit' to exit.")
    print("=" * 65)

    while True:
        user_input = input("\n🌾 Your question: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye! 🌦️")
            break
        if not user_input:
            continue
        print("\n⏳ Fetching NOAA GFS forecast and generating answer...\n")
        answer = answer_with_weather(user_input, farmer_context, lat, lon)
        print("─" * 65)
        print(answer)
        print("─" * 65)


if __name__ == "__main__":
    run_chatbot()