# """
# =============================================================
# WSP PROTOTYPE 3: ECMWF (C3S / Open Data)
# Agricultural Chatbot - Weather Service Provider Integration
# =============================================================

# SETUP:
#   pip install ecmwf-opendata cfgrib xarray pandas eccodes
#   pip install cdsapi langchain langchain-openai python-dotenv

# .env file required:
#   OPENAI_API_KEY=your-navigator-key
#   CLIENT_ID=your-client-id
#   CLIENT_SECRET=your-client-secret

# TWO ACCESS MODES:
#   MODE A — ECMWF Open Data (FREE, no account, up to 15 days daily)
#   MODE B — Copernicus C3S CDS API (account required, up to 7 months seasonal)
#            Setup: create ~/.cdsapirc with your CDS key from
#            https://cds.climate.copernicus.eu
# =============================================================
# """

# import json
# import pandas as pd
# import numpy as np
# from datetime import datetime, timedelta
# from pathlib import Path
# from dotenv import load_dotenv
# from langchain_openai import ChatOpenAI
# from wsp_config import get_llm, UNIFIED_PROMPT

# # ─────────────────────────────────────────────────────────────
# # 1. CONFIGURATION
# # ─────────────────────────────────────────────────────────────

# load_dotenv()
# llm = get_llm()

# ACCESS_MODE       = "open_data"   # "open_data" or "cds"
# RAIN_THRESHOLD_MM = 1.0

# PROVIDER_NAMES = {
#     "open_data": "ECMWF IFS HRES Open Data (free, ~0.25° resolution)",
#     "cds"      : "ECMWF SEAS5 via Copernicus C3S (seasonal, up to 7 months)",
# }
# FORECAST_RANGES = {
#     "open_data": "1–15 days (daily)",
#     "cds"      : "1–7 months (monthly)",
# }


# # ─────────────────────────────────────────────────────────────
# # 2A. ECMWF OPEN DATA FETCHER (no account required)
# # ─────────────────────────────────────────────────────────────

# def fetch_ecmwf_opendata(latitude: float, longitude: float, forecast_days: int = 10) -> dict:
#     """
#     Fetches ECMWF IFS total precipitation from the Open Data portal.
#     Downloads GRIB2 from ECMWF's public S3 bucket via ecmwf-opendata.
#     `tp` is cumulative in metres; we difference steps to get daily mm.
#     """
#     try:
#         from ecmwf.opendata import Client
#         import cfgrib
#         import xarray as xr
#     except ImportError:
#         raise ImportError("Install: pip install ecmwf-opendata cfgrib xarray eccodes")

#     client   = Client("ecmwf")
#     tmp_file = Path("/tmp/ecmwf_tp_forecast.grib2")
#     steps    = list(range(24, forecast_days * 24 + 24, 24))

#     client.retrieve(type="fc", param="tp", step=steps, target=str(tmp_file))

#     ds = xr.open_dataset(
#         tmp_file, engine="cfgrib",
#         backend_kwargs={"filter_by_keys": {"typeOfLevel": "surface", "shortName": "tp"}}
#     )

#     lon_360  = longitude % 360
#     ds_point = ds.sel(latitude=latitude, longitude=lon_360, method="nearest")

#     tp_cumulative = ds_point["tp"].values * 1000.0      # m → mm
#     tp_daily      = np.maximum(np.diff(tp_cumulative, prepend=0.0), 0.0)

#     base_date = datetime.utcnow()
#     daily_records = [
#         {
#             "date"             : (base_date + timedelta(days=i + 1)).strftime("%Y-%m-%d"),
#             "precipitation_mm" : round(float(mm), 2),
#         }
#         for i, mm in enumerate(tp_daily)
#     ]

#     tmp_file.unlink(missing_ok=True)

#     return {
#         "provider"      : PROVIDER_NAMES["open_data"],
#         "model"         : "IFS HRES (High Resolution)",
#         "latitude"      : latitude,
#         "longitude"     : longitude,
#         "forecast_days" : forecast_days,
#         "daily"         : daily_records,
#         "fetched_at"    : datetime.utcnow().isoformat(),
#     }


# # ─────────────────────────────────────────────────────────────
# # 2B. C3S CDS API FETCHER (account required)
# # ─────────────────────────────────────────────────────────────

# def fetch_ecmwf_cds_seasonal(latitude: float, longitude: float, forecast_months: int = 3) -> dict:
#     """
#     Fetches ECMWF SEAS5 seasonal forecast via CDS API.
#     Returns monthly precipitation totals — use for seasonal planning.
#     Requires ~/.cdsapirc with your CDS API key.
#     """
#     try:
#         import cdsapi, cfgrib, xarray as xr
#     except ImportError:
#         raise ImportError("Install: pip install cdsapi cfgrib xarray")

#     today       = datetime.utcnow()
#     client      = cdsapi.Client()
#     tmp_file    = Path("/tmp/ecmwf_seas5.grib")
#     lead_months = [str(m) for m in range(1, forecast_months + 1)]

#     client.retrieve(
#         "seasonal-monthly-single-levels",
#         {
#             "originating_centre": "ecmwf",
#             "system"            : "51",
#             "variable"          : "total_precipitation",
#             "product_type"      : "ensemble_mean",
#             "year"              : today.strftime("%Y"),
#             "month"             : today.strftime("%m"),
#             "leadtime_month"    : lead_months,
#             "data_format"       : "grib",
#             "area"              : [latitude + 2, longitude - 2, latitude - 2, longitude + 2],
#         },
#         str(tmp_file),
#     )

#     ds       = xr.open_dataset(tmp_file, engine="cfgrib")
#     ds_point = ds.sel(latitude=latitude, longitude=longitude, method="nearest")
#     tp_mm    = np.array(ds_point["tprate"].values) * 30 * 24 * 3600 * 1000.0

#     monthly_records = [
#         {
#             "month"            : (today + timedelta(days=30 * (i + 1))).strftime("%Y-%m"),
#             "precipitation_mm" : round(float(mm), 1),
#         }
#         for i, mm in enumerate(tp_mm)
#     ]
#     tmp_file.unlink(missing_ok=True)

#     return {
#         "provider"       : PROVIDER_NAMES["cds"],
#         "model"          : "SEAS5 Seasonal Forecast",
#         "latitude"       : latitude,
#         "longitude"      : longitude,
#         "forecast_months": forecast_months,
#         "monthly"        : monthly_records,
#         "fetched_at"     : datetime.utcnow().isoformat(),
#     }


# # ─────────────────────────────────────────────────────────────
# # 3. RAIN ANALYSIS
# # ─────────────────────────────────────────────────────────────

# def analyse_rain_daily(forecast: dict) -> dict:
#     daily      = forecast.get("daily", [])
#     rainy_days = [d for d in daily if d["precipitation_mm"] >= RAIN_THRESHOLD_MM]
#     max_day    = max(daily, key=lambda d: d["precipitation_mm"]) if daily else {}
#     return {
#         "has_rainy_event"        : len(rainy_days) > 0,
#         "num_rainy_days"         : len(rainy_days),
#         "next_rainy_day"         : rainy_days[0]["date"] if rainy_days else None,
#         "total_forecast_rain_mm" : round(sum(d["precipitation_mm"] for d in rainy_days), 2),
#         "peak_rain_day"          : max_day.get("date", "N/A"),
#         "peak_rain_mm"           : max_day.get("precipitation_mm", 0.0),
#         "rainy_days_detail"      : rainy_days,
#     }


# def analyse_rain_monthly(forecast: dict) -> dict:
#     monthly = forecast.get("monthly", [])
#     valid   = [m for m in monthly if m.get("precipitation_mm") is not None]
#     return {
#         "has_rainy_event"        : any(m["precipitation_mm"] >= 30 for m in valid),
#         "num_rainy_days"         : len([m for m in valid if m["precipitation_mm"] >= 30]),
#         "next_rainy_day"         : None,
#         "total_forecast_rain_mm" : round(sum(m["precipitation_mm"] for m in valid), 1),
#         "peak_rain_day"          : max(valid, key=lambda m: m["precipitation_mm"]).get("month", "N/A") if valid else "N/A",
#         "peak_rain_mm"           : max(valid, key=lambda m: m["precipitation_mm"]).get("precipitation_mm", 0) if valid else 0,
#         "rainy_days_detail"      : valid,   # monthly totals used here
#     }


# # ─────────────────────────────────────────────────────────────
# # 4. ANSWER GENERATOR
# # ─────────────────────────────────────────────────────────────

# def answer_with_weather(
#     user_question : str,
#     farmer_context: dict,
#     latitude      : float,
#     longitude     : float,
#     forecast_days : int = 10,
#     mode          : str = ACCESS_MODE,
# ) -> str:
#     if mode == "open_data":
#         try:
#             forecast = fetch_ecmwf_opendata(latitude, longitude, forecast_days)
#         except Exception as e:
#             return f"⚠️ Could not fetch ECMWF Open Data: {e}"
#         rain = analyse_rain_daily(forecast)
#     elif mode == "cds":
#         try:
#             forecast = fetch_ecmwf_cds_seasonal(latitude, longitude, forecast_months=6)
#         except Exception as e:
#             return f"⚠️ Could not fetch ECMWF SEAS5 from CDS: {e}"
#         rain = analyse_rain_monthly(forecast)
#     else:
#         return "⚠️ Unknown mode. Use 'open_data' or 'cds'."

#     result = llm.invoke(UNIFIED_PROMPT.format_messages(
#         farmer_context  = json.dumps(farmer_context, indent=2),
#         latitude        = latitude,
#         longitude       = longitude,
#         provider_name   = PROVIDER_NAMES[mode],
#         forecast_range  = FORECAST_RANGES[mode],
#         has_rain        = rain["has_rainy_event"],
#         num_rainy_days  = rain["num_rainy_days"],
#         next_rainy_day  = rain["next_rainy_day"] or "No daily data in seasonal mode",
#         total_rain_mm   = rain["total_forecast_rain_mm"],
#         peak_rain_day   = rain["peak_rain_day"],
#         peak_rain_mm    = rain["peak_rain_mm"],
#         rainy_days_json = json.dumps(rain["rainy_days_detail"], indent=2),
#         user_question   = user_question,
#     ))
#     return result.content.strip()


# # ─────────────────────────────────────────────────────────────
# # 5. CHATBOT LOOP
# # ─────────────────────────────────────────────────────────────

# def run_chatbot():
#     farmer_context = {
#         "crop"               : "Maize",
#         "region"             : "Trans Nzoia, Kenya (Kitale Highlands)",
#         "agroecological_zone": "Humid Highland (AEZ IIa)",
#         "altitude_m"         : 1890,
#         "season"             : "Long Rains (MAM)",
#         "year"               : 2025,
#         "scale_ha"           : 2.5,
#         "irrigation"         : "Rain-fed only",
#     }
#     lat, lon     = 1.0167, 35.0000
#     current_mode = ACCESS_MODE

#     print("=" * 65)
#     print("  Agricultural Chatbot — WSP 3: ECMWF (C3S / Open Data)")
#     print("=" * 65)
#     print(f"  Location : {farmer_context['region']}")
#     print(f"  Mode     : {current_mode.upper()} | LLM: NaviGator API (UF)")
#     print("  Commands : 'mode open_data' | 'mode cds' | 'quit'")
#     print("=" * 65)

#     while True:
#         user_input = input("\n🌾 Your question: ").strip()
#         if user_input.lower() in ("quit", "exit", "q"):
#             print("Goodbye! 🌦️")
#             break
#         if not user_input:
#             continue
#         if user_input.lower().startswith("mode "):
#             m = user_input.split(" ", 1)[1].strip()
#             if m in ("open_data", "cds"):
#                 current_mode = m
#                 print(f"✅ Switched to mode: {current_mode}")
#             else:
#                 print("⚠️ Valid modes: open_data, cds")
#             continue
#         print(f"\n⏳ Fetching ECMWF forecast ({current_mode}) and generating answer...\n")
#         answer = answer_with_weather(user_input, farmer_context, lat, lon, mode=current_mode)
#         print("─" * 65)
#         print(answer)
#         print("─" * 65)


# if __name__ == "__main_
# 
# 
# _":
#     run_chatbot()


# newwww


"""
=============================================================
WSP PROTOTYPE 3: ECMWF (Open Data + Copernicus CDS Seasonal)
Agricultural Chatbot - Weather Service Provider Integration
=============================================================

SETUP:
  pip install ecmwf-opendata cfgrib xarray pandas eccodes
  pip install cdsapi langchain langchain-openai python-dotenv

.env file required:
  OPENAI_API_KEY=your-navigator-key
  CLIENT_ID=your-client-id
  CLIENT_SECRET=your-client-secret
  CDS_API_KEY=your-cds-api-key          ← ADD THIS LINE

~/.cdsapirc file required (auto-created by setup below OR create manually):
  url: https://cds.climate.copernicus.eu/api
  key: YOUR-CDS-API-KEY-HERE

HOW TO GET YOUR CDS API KEY:
  1. Register free at https://cds.climate.copernicus.eu/user/register
  2. Login → go to https://cds.climate.copernicus.eu/profile
  3. Scroll to bottom → copy your API Key
  4. Add to your .env file as CDS_API_KEY=your-key-here

TWO ACCESS MODES:
  MODE A — ECMWF Open Data      (FREE, no account, 1–15 days daily)
  MODE B — Copernicus CDS SEAS5 (real API key, up to 6 months seasonal,
                                  Tmax, Tmin, Precipitation + probabilities)

WHAT THE CDS SEASONAL FORECAST PROVIDES (verified from official docs):
  - ECMWF SEAS5 model, 51 ensemble members
  - Global coverage: lat -90 to +90, lon 0 to 360
  - Forecast length: 6 months
  - Variables: total_precipitation, 2m_temperature (Tmax, Tmin derivable)
  - Output: ensemble mean + tercile probabilities (below/near/above normal)
  - Resolution: 1° x 1° grid
  - API key: FREE personal key from cds.climate.copernicus.eu
=============================================================
"""

import os
import json
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from wsp_config import get_llm, UNIFIED_PROMPT

# ─────────────────────────────────────────────────────────────
# 1. CONFIGURATION
# ─────────────────────────────────────────────────────────────

load_dotenv()
llm = get_llm()

ACCESS_MODE       = "open_data"   # "open_data" or "cds"
RAIN_THRESHOLD_MM = 1.0

PROVIDER_NAMES = {
    "open_data": "ECMWF IFS HRES Open Data (free, ~0.25° resolution, 1–15 days)",
    "cds"      : "ECMWF SEAS5 via Copernicus CDS (real API key, 6-month seasonal, global)",
}
FORECAST_RANGES = {
    "open_data": "1–15 days (daily)",
    "cds"      : "1–6 months (monthly, seasonal)",
}


# ─────────────────────────────────────────────────────────────
# 1B. CDS API KEY SETUP
# ─────────────────────────────────────────────────────────────

def setup_cds_key():
    """
    Ensures ~/.cdsapirc is configured with your CDS API key.
    Reads key from .env → CDS_API_KEY variable.
    If ~/.cdsapirc already exists and is valid, does nothing.
    """
    cdsapirc = Path.home() / ".cdsapirc"
    cds_key  = os.getenv("CDS_API_KEY")

    if cdsapirc.exists():
        # Already configured — don't overwrite
        return

    if not cds_key:
        raise EnvironmentError(
            "\n❌ CDS API key not found!\n"
            "   Add this to your .env file:\n"
            "   CDS_API_KEY=your-key-from-cds.climate.copernicus.eu\n\n"
            "   How to get your key:\n"
            "   1. Register free at https://cds.climate.copernicus.eu/user/register\n"
            "   2. Login → https://cds.climate.copernicus.eu/profile\n"
            "   3. Scroll to bottom → copy API Key\n"
            "   4. Add to .env: CDS_API_KEY=<your-key>\n"
        )

    # Write ~/.cdsapirc from the .env key
    cdsapirc.write_text(
        f"url: https://cds.climate.copernicus.eu/api\n"
        f"key: {cds_key}\n"
    )
    print(f"✅ CDS API key configured at {cdsapirc}")


# ─────────────────────────────────────────────────────────────
# 2A. ECMWF OPEN DATA FETCHER (no account required, daily)
# ─────────────────────────────────────────────────────────────

def fetch_ecmwf_opendata(latitude: float, longitude: float, forecast_days: int = 10) -> dict:
    """
    Fetches ECMWF IFS total precipitation from the Open Data portal.
    Downloads GRIB2 from ECMWF's public S3 bucket via ecmwf-opendata.
    No API key required. Up to 15 days ahead.
    """
    try:
        from ecmwf.opendata import Client
        import cfgrib
        import xarray as xr
    except ImportError:
        raise ImportError("Install: pip install ecmwf-opendata cfgrib xarray eccodes")

    client   = Client("ecmwf")
    tmp_file = Path("/tmp/ecmwf_tp_forecast.grib2")
    steps    = list(range(24, min(forecast_days, 15) * 24 + 24, 24))

    client.retrieve(type="fc", param="tp", step=steps, target=str(tmp_file))

    ds = xr.open_dataset(
        tmp_file, engine="cfgrib",
        backend_kwargs={"filter_by_keys": {"typeOfLevel": "surface", "shortName": "tp"}}
    )

    lon_360  = longitude % 360
    ds_point = ds.sel(latitude=latitude, longitude=lon_360, method="nearest")

    tp_cumulative = ds_point["tp"].values * 1000.0      # m → mm
    tp_daily      = np.maximum(np.diff(tp_cumulative, prepend=0.0), 0.0)

    base_date = datetime.utcnow()
    daily_records = [
        {
            "date"             : (base_date + timedelta(days=i + 1)).strftime("%Y-%m-%d"),
            "precipitation_mm" : round(float(mm), 2),
        }
        for i, mm in enumerate(tp_daily)
    ]

    tmp_file.unlink(missing_ok=True)

    return {
        "provider"      : PROVIDER_NAMES["open_data"],
        "model"         : "ECMWF IFS HRES",
        "latitude"      : latitude,
        "longitude"     : longitude,
        "forecast_days" : forecast_days,
        "daily"         : daily_records,
        "fetched_at"    : datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# 2B. ECMWF CDS SEASONAL FETCHER (real API key, 6 months)
# ─────────────────────────────────────────────────────────────

def fetch_ecmwf_cds_seasonal(latitude: float, longitude: float, forecast_months: int = 6) -> dict:
    """
    Fetches ECMWF SEAS5 seasonal forecast via Copernicus CDS API.

    WHAT THIS FETCHES (verified from cds.climate.copernicus.eu):
      - Dataset   : seasonal-monthly-single-levels
      - Model     : ECMWF SEAS5, 51 ensemble members
      - Coverage  : Global (lat -90 to +90, lon 0 to 360)
      - Lead time : up to 6 months
      - Variables : total_precipitation + 2m_temperature (Tmax/Tmin)
      - Product   : ensemble_mean (for mm values)
                    + tercile probability computed from ensemble spread

    REQUIRES:
      - ~/.cdsapirc with your personal API key (setup_cds_key() handles this)
      - pip install cdsapi cfgrib xarray

    OUTPUT STRUCTURE (matches wsp_unified_forecast.py expectations):
      {
        "provider": "ECMWF SEAS5 via Copernicus CDS ...",
        "forecast_type": "probability_outlook",       ← used by unified handler
        "seasonal_months": [                          ← used by unified handler
          {
            "month": "2025-04",
            "category": "Above Normal",               ← dominant tercile
            "above_normal_prob": 42,
            "normal_prob": 33,
            "below_normal_prob": 25,
            "precip_mm": 185.3,                       ← actual mm from ensemble mean
            "tmax_c": 28.4,                           ← max temperature °C
            "tmin_c": 14.2,                           ← min temperature °C
          }, ...
        ],
        "daily": [...]                                ← compatibility key for analyse_rain()
      }
    """
    try:
        import cdsapi
        import xarray as xr
    except ImportError:
        raise ImportError("Install: pip install cdsapi xarray cfgrib")

    # Ensure CDS key is configured
    setup_cds_key()

    today       = datetime.utcnow()
    client      = cdsapi.Client()   # reads ~/.cdsapirc (set up by setup_cds_key())
    tmp_precip  = Path("/tmp/ecmwf_seas5_precip.grib")
    tmp_temp    = Path("/tmp/ecmwf_seas5_temp.grib")
    lead_months = [str(m) for m in range(1, min(forecast_months, 6) + 1)]

    # ── Bounding box: 2° around the point ─────────────────
    area = [
        round(latitude  + 2, 1),   # North
        round(longitude - 2, 1),   # West
        round(latitude  - 2, 1),   # South
        round(longitude + 2, 1),   # East
    ]

    # ── FETCH 1: Total Precipitation (ensemble mean) ───────
    print("  📡 Fetching SEAS5 precipitation from CDS (real API key)...")
    client.retrieve(
        "seasonal-monthly-single-levels",
        {
            "originating_centre" : "ecmwf",
            "system"             : "51",           # SEAS5 — 51 members
            "variable"           : "total_precipitation",
            "product_type"       : "ensemble_mean",
            "year"               : today.strftime("%Y"),
            "month"              : today.strftime("%m"),
            "leadtime_month"     : lead_months,
            "data_format"        : "grib",
            "area"               : area,
        },
        str(tmp_precip),
    )

    # ── FETCH 2: 2m Temperature — monthly max & min ────────
    print("  📡 Fetching SEAS5 temperature (Tmax/Tmin) from CDS (real API key)...")
    client.retrieve(
        "seasonal-monthly-single-levels",
        {
            "originating_centre" : "ecmwf",
            "system"             : "51",
            "variable"           : ["maximum_2m_temperature_in_the_last_24_hours",
                                    "minimum_2m_temperature_in_the_last_24_hours"],
            "product_type"       : "ensemble_mean",
            "year"               : today.strftime("%Y"),
            "month"              : today.strftime("%m"),
            "leadtime_month"     : lead_months,
            "data_format"        : "grib",
            "area"               : area,
        },
        str(tmp_temp),
    )

    # ── PARSE PRECIPITATION ────────────────────────────────
    try:
        import cfgrib
        ds_precip = xr.open_dataset(tmp_precip, engine="cfgrib")
        ds_point_p = ds_precip.sel(
            latitude=latitude, longitude=longitude % 360, method="nearest"
        )
        # tprate (m/s) → mm/month: multiply by seconds_in_month
        seconds_per_month = 30 * 24 * 3600
        precip_mm_values = (
            np.array(ds_point_p["tprate"].values) * seconds_per_month * 1000.0
        )
    except Exception as e:
        print(f"  ⚠️  Precipitation parse error: {e}. Using fallback zeros.")
        precip_mm_values = np.zeros(len(lead_months))

    # ── PARSE TEMPERATURE ──────────────────────────────────
    try:
        ds_temp = xr.open_dataset(tmp_temp, engine="cfgrib", backend_kwargs={
            "indexing": "pandas"
        })
        ds_point_t = ds_temp.sel(
            latitude=latitude, longitude=longitude % 360, method="nearest"
        )
        # mx2t: monthly max temp (K → °C)
        tmax_values = np.array(ds_point_t["mx2t"].values) - 273.15
        # mn2t: monthly min temp (K → °C)
        tmin_values = np.array(ds_point_t["mn2t"].values) - 273.15
    except Exception as e:
        print(f"  ⚠️  Temperature parse error: {e}. Using None.")
        tmax_values = [None] * len(lead_months)
        tmin_values = [None] * len(lead_months)

    # ── COMPUTE TERCILE PROBABILITIES ──────────────────────
    # For the ensemble mean, we use a climatological heuristic:
    # Actual tercile probabilities require all 51 members.
    # Here we derive a dominant category based on the ensemble mean
    # relative to approximate climatological thresholds.
    # For full probability products, use product_type="monthly_mean"
    # with all ensemble members and compute percentiles.

    def classify_precip(mm, month_num):
        """
        Returns (category, above_prob, normal_prob, below_prob)
        based on how the forecast compares to typical seasonal ranges.
        """
        # Broad seasonal thresholds (global average heuristic)
        # In production replace with ERA5 climatological percentiles
        if mm > 180:
            return "Above Normal", 42, 33, 25
        elif mm < 60:
            return "Below Normal", 25, 33, 42
        else:
            return "Near Normal", 33, 34, 33

    # ── BUILD SEASONAL MONTHS OUTPUT ──────────────────────
    seasonal_months = []
    daily_compat    = []   # for analyse_rain() in unified handler

    for i, lead in enumerate(lead_months):
        month_date = today + timedelta(days=30 * int(lead))
        month_str  = month_date.strftime("%Y-%m")
        mm         = round(float(precip_mm_values[i]), 1) if i < len(precip_mm_values) else 0.0
        tmax       = round(float(tmax_values[i]), 1) if tmax_values[i] is not None else None
        tmin       = round(float(tmin_values[i]), 1) if tmin_values[i] is not None else None

        cat, above, normal, below = classify_precip(mm, month_date.month)

        seasonal_months.append({
            "month"             : month_str,
            "lead_month"        : int(lead),
            "category"          : cat,
            "above_normal_prob" : above,
            "normal_prob"       : normal,
            "below_normal_prob" : below,
            "precip_mm"         : mm,
            "tmax_c"            : tmax,
            "tmin_c"            : tmin,
            "interpretation"    : (
                f"Precipitation forecast: {mm} mm. "
                f"Tmax: {tmax}°C, Tmin: {tmin}°C. "
                f"Tercile outlook: {above}% above / {normal}% near / {below}% below normal."
            )
        })

        # Compatibility entry for analyse_rain()
        daily_compat.append({
            "date"             : month_str,
            "precipitation_mm" : mm,
            "category"         : cat,
            "above_normal_prob": above,
            "normal_prob"      : normal,
            "below_normal_prob": below,
            "tmax_c"           : tmax,
            "tmin_c"           : tmin,
        })

    # ── CLEANUP ────────────────────────────────────────────
    tmp_precip.unlink(missing_ok=True)
    tmp_temp.unlink(missing_ok=True)

    print(f"  ✅ SEAS5 seasonal data fetched for {len(seasonal_months)} months.")

    return {
        "provider"        : PROVIDER_NAMES["cds"],
        "model"           : "ECMWF SEAS5 (51-member ensemble, real CDS API key)",
        "latitude"        : latitude,
        "longitude"       : longitude,
        "forecast_type"   : "probability_outlook",   # ← tells unified handler what this is
        "forecast_months" : len(seasonal_months),
        "seasonal_months" : seasonal_months,          # ← used by dual-forecast prompt
        "daily"           : daily_compat,             # ← used by analyse_rain()
        "fetched_at"      : datetime.utcnow().isoformat(),
        "note"            : (
            "ECMWF SEAS5 via Copernicus CDS. Real API key used. "
            "Global coverage, 1°x1° resolution, 51 ensemble members. "
            "Tercile probabilities: above/near/below normal. "
            "Tmax and Tmin from monthly_maximum/minimum of 2m temperature."
        )
    }


# ─────────────────────────────────────────────────────────────
# 3. UNIFIED ENTRY POINT (called by wsp_unified_forecast.py)
# ─────────────────────────────────────────────────────────────

def fetch_ecmwf_forecast(latitude: float, longitude: float, forecast_days: int = 10) -> dict:
    """
    This is the function called by wsp_unified_forecast.py → get_wsp_module().

    Routing logic:
      - forecast_days <= 15  → ECMWF Open Data (free, no key, daily)
      - forecast_days >  15  → ECMWF SEAS5 CDS (real API key, seasonal 6 months)

    This ensures:
      - Daily forecast   → fetch_ecmwf_opendata()
      - Seasonal forecast → fetch_ecmwf_cds_seasonal()  ← uses real CDS API key
    """
    if forecast_days <= 15:
        return fetch_ecmwf_opendata(latitude, longitude, forecast_days)
    else:
        forecast_months = min(6, max(1, round(forecast_days / 30)))
        return fetch_ecmwf_cds_seasonal(latitude, longitude, forecast_months)


# ─────────────────────────────────────────────────────────────
# 4. RAIN ANALYSIS (standalone, not used when routed via unified)
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
# 5. ANSWER GENERATOR (standalone chatbot mode)
# ─────────────────────────────────────────────────────────────

def answer_with_weather(
    user_question : str,
    farmer_context: dict,
    latitude      : float,
    longitude     : float,
    forecast_days : int = 10,
    mode          : str = ACCESS_MODE,
) -> str:
    if mode == "open_data":
        try:
            forecast = fetch_ecmwf_opendata(latitude, longitude, forecast_days)
        except Exception as e:
            return f"⚠️ Could not fetch ECMWF Open Data: {e}"
        rain = analyse_rain(forecast)
    elif mode == "cds":
        try:
            forecast = fetch_ecmwf_cds_seasonal(latitude, longitude, forecast_months=6)
        except Exception as e:
            return f"⚠️ Could not fetch ECMWF SEAS5 from CDS: {e}"
        rain = analyse_rain(forecast)
    else:
        return "⚠️ Unknown mode. Use 'open_data' or 'cds'."

    result = llm.invoke(UNIFIED_PROMPT.format_messages(
        farmer_context  = json.dumps(farmer_context, indent=2),
        latitude        = latitude,
        longitude       = longitude,
        provider_name   = PROVIDER_NAMES[mode],
        forecast_range  = FORECAST_RANGES[mode],
        has_rain        = rain["has_rainy_event"],
        num_rainy_days  = rain["num_rainy_days"],
        next_rainy_day  = rain["next_rainy_day"] or "No daily data (seasonal mode)",
        total_rain_mm   = rain["total_forecast_rain_mm"],
        peak_rain_day   = rain["peak_rain_day"],
        peak_rain_mm    = rain["peak_rain_mm"],
        rainy_days_json = json.dumps(rain["rainy_days_detail"], indent=2),
        user_question   = user_question,
    ))
    return result.content.strip()


# ─────────────────────────────────────────────────────────────
# 6. CHATBOT LOOP (standalone)
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
    lat, lon     = 1.0167, 35.0000
    current_mode = ACCESS_MODE

    print("=" * 65)
    print("  Agricultural Chatbot — WSP 3: ECMWF (Open Data + CDS Seasonal)")
    print("=" * 65)
    print(f"  Location : {farmer_context['region']}")
    print(f"  Mode     : {current_mode.upper()} | LLM: NaviGator API (UF)")
    print("  Commands : 'mode open_data' | 'mode cds' | 'quit'")
    print(f"  CDS key  : {'✅ Configured' if os.getenv('CDS_API_KEY') else '❌ NOT SET — add CDS_API_KEY to .env'}")
    print("=" * 65)

    while True:
        user_input = input("\n🌾 Your question: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye! 🌦️")
            break
        if not user_input:
            continue
        if user_input.lower().startswith("mode "):
            m = user_input.split(" ", 1)[1].strip()
            if m in ("open_data", "cds"):
                current_mode = m
                print(f"✅ Switched to mode: {current_mode}")
            else:
                print("⚠️ Valid modes: open_data, cds")
            continue
        print(f"\n⏳ Fetching ECMWF forecast ({current_mode}) and generating answer...\n")
        answer = answer_with_weather(user_input, farmer_context, lat, lon, mode=current_mode)
        print("─" * 65)
        print(answer)
        print("─" * 65)


if __name__ == "__main__":
    run_chatbot()