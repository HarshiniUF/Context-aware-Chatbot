"""
=============================================================
UNIFIED FORECAST HANDLER
Integrates multiple weather service providers for both
daily and seasonal forecasts
=============================================================

This module dynamically imports the correct WSP modules based on
configuration settings in wsp_config.py

DEFAULT SETUP:
- Daily Forecast: Open-Meteo (1-16 days, high resolution)
- Seasonal Forecast: NOAA CPC (longer range)

EASY SWITCHING:
Change DAILY_FORECAST_WSP and SEASONAL_FORECAST_WSP in wsp_config.py
to switch providers without modifying this file.
=============================================================
"""

import json
import re
from datetime import datetime, timezone
from typing import Dict, Tuple, List, Optional
from wsp_config import (
    get_llm, UNIFIED_PROMPT,
    DAILY_FORECAST_WSP, SEASONAL_FORECAST_WSP,
    DEFAULT_LATITUDE, DEFAULT_LONGITUDE, DEFAULT_LOCATION_NAME,
    extract_crop_from_question, extract_date_from_question, extract_crop_and_date_json,
    get_today_str, get_today_datetime
)
from langchain_core.prompts import ChatPromptTemplate

# ─────────────────────────────────────────────────────────────
# IMPORT SOIL MODULES (OPTIONAL)
# ─────────────────────────────────────────────────────────────

try:
    from wsp_soil_isda import get_soil_data, extract_soil_values
    from wsp_soil_integration import format_soil_for_prompt
    SOIL_AVAILABLE = True
except ImportError:
    SOIL_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
# DYNAMIC WSP MODULE LOADER
# ─────────────────────────────────────────────────────────────

def get_wsp_module(wsp_name: str):
    """
    Dynamically import the correct WSP module based on configuration.
    
    Args:
        wsp_name: Name of the WSP (e.g., "openmeteo", "noaacpc", etc.)
    
    Returns:
        The imported module
    """
    wsp_map = {
        "openmeteo": "wsp1_openmeteo",
        "chirps": "wsp2_chirps",
        "ecmwf": "wsp3_ecmwf",
        "noaacpc": "wsp4_noaacpc",
        "iri": "wsp5_iri",
    }
    
    if wsp_name not in wsp_map:
        raise ValueError(f"Unknown WSP: {wsp_name}. Available: {list(wsp_map.keys())}")
    
    module_name = wsp_map[wsp_name]
    try:
        return __import__(module_name)
    except ImportError as e:
        raise ImportError(f"Could not import {module_name}: {e}")


def fetch_daily_forecast(latitude: float, longitude: float, forecast_days: int = 16, start_date: Optional[str] = None) -> dict:
    """
    Fetch daily forecast using configured provider (DAILY_FORECAST_WSP).
    
    Args:
        latitude: Location latitude
        longitude: Location longitude
        forecast_days: Number of forecast days (typically 1-16)
    
    Returns:
        Forecast dictionary with standard structure
    """
    module = get_wsp_module(DAILY_FORECAST_WSP)
    if start_date:
        print(f"[DEBUG] fetch_daily_forecast: requested start_date={start_date} (providers may ignore this)")
    
    if DAILY_FORECAST_WSP == "openmeteo":
        return module.fetch_openmeteo_forecast(latitude, longitude, forecast_days, start_date=start_date)
    elif DAILY_FORECAST_WSP == "noaacpc":
        return module.fetch_noaa_gfs_forecast(latitude, longitude, forecast_days)
    elif DAILY_FORECAST_WSP == "chirps":
        return module.fetch_chirps_forecast(latitude, longitude, forecast_days)
    elif DAILY_FORECAST_WSP == "ecmwf":
        return module.fetch_ecmwf_forecast(latitude, longitude, forecast_days)
    elif DAILY_FORECAST_WSP == "iri":
        return module.fetch_iri_forecast(latitude, longitude, forecast_days)
    else:
        raise ValueError(f"No fetch function defined for {DAILY_FORECAST_WSP}")


def fetch_seasonal_forecast(latitude: float, longitude: float, forecast_days: int = 30, start_date: Optional[str] = None) -> dict:
    """
    Fetch seasonal forecast using configured provider (SEASONAL_FORECAST_WSP).
    
    Args:
        latitude: Location latitude
        longitude: Location longitude
        forecast_days: Number of forecast days (typically 30+ for seasonal)
    
    Returns:
        Forecast dictionary with standard structure
    """
    module = get_wsp_module(SEASONAL_FORECAST_WSP)
    if start_date:
        print(f"[DEBUG] fetch_seasonal_forecast: requested start_date={start_date} (providers may ignore this)")
    
    if SEASONAL_FORECAST_WSP == "openmeteo":
        return module.fetch_openmeteo_forecast(latitude, longitude, forecast_days, start_date=start_date)
    elif SEASONAL_FORECAST_WSP == "noaacpc":
        # Use NOAA CPC seasonal probability outlook (not GFS daily)
        return module.fetch_noaa_cpc_seasonal(latitude, longitude)
    elif SEASONAL_FORECAST_WSP == "chirps":
        return module.fetch_chirps_forecast(latitude, longitude, forecast_days)
    elif SEASONAL_FORECAST_WSP == "ecmwf":
        # ECMWF SEAS5 seasonal forecast from Copernicus Climate Data Store (CDS)
        # Uses approach from seasonal_test.py which works reliably
        try:
            import cdsapi
            import xarray as xr
            import numpy as np
            from datetime import datetime, timezone, timedelta
            from pathlib import Path
            
            client = cdsapi.Client()

            # Determine anchor date for model-run calculations. Prefer the provided start_date
            # (scenario date) when available; otherwise use today's date.
            if start_date:
                try:
                    anchor = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except Exception:
                    anchor = datetime.now(timezone.utc)
            else:
                anchor = datetime.now(timezone.utc)

            # Calculate model run date (1 month before anchor month)
            if anchor.month == 1:
                model_run_year = anchor.year - 1
                model_run_month = 12
            else:
                model_run_year = anchor.year
                model_run_month = anchor.month - 1

            # Safety: if model run not yet published (before 5th of anchor month), use previous month
            if model_run_year == anchor.year and model_run_month == anchor.month and anchor.day < 5:
                if anchor.month == 1:
                    model_run_year, model_run_month = anchor.year - 1, 12
                else:
                    model_run_year, model_run_month = anchor.year, anchor.month - 1
            
            # Compute lead months (1-6 months ahead of model run)
            # For anchor month and next 2 months
            lead_months = []
            current_month = anchor.month
            for i in range(3):  # Current month + next 2 months
                total = current_month - 1 + i
                fc_month = total % 12 + 1
                lead = (fc_month - model_run_month) % 12
                if lead == 0:
                    lead = 12
                if 1 <= lead <= 6:
                    lead_months.append(str(lead))
            
            if not lead_months:
                lead_months = ['1', '2', '3']  # Default fallback
            
            print(f"[DEBUG] ECMWF SEAS5: Model run {model_run_year}-{model_run_month:02d}, Lead months: {lead_months}")
            
            # Common parameters (from seasonal_test.py working example)
            common_params = {
                "originating_centre": "ecmwf",
                "system": "51",  # SEAS5 operational system
                "year": str(model_run_year),
                "month": f"{model_run_month:02d}",
                "leadtime_month": lead_months,
                "data_format": "grib",
            }
            
            # Fetch precipitation (ensemble mean)
            tmp_precip = Path("/tmp/seas5_precip.grib")
            client.retrieve(
                "seasonal-monthly-single-levels",
                {**common_params,
                 "variable": "total_precipitation",
                 "product_type": "ensemble_mean"},
                str(tmp_precip),
            )
            
            # Parse the GRIB file
            ds = xr.open_dataset(str(tmp_precip), engine='cfgrib')
            ds_point = ds.sel(latitude=latitude, longitude=longitude, method='nearest')
            
            # Extract precipitation values (tprate in m/s → mm/month)
            # seconds_per_month = 30 * 24 * 3600
            seconds_per_month = 30 * 24 * 3600
            precip_values = ds_point['tprate'].values * seconds_per_month * 1000.0
            
            # Create monthly forecast records with tercile probabilities
            monthly_forecast = []
            for i, lead_month in enumerate(lead_months):
                if i < len(precip_values):
                    fc_val = float(precip_values[i])
                else:
                    fc_val = 100.0
            
                # Simple tercile categorization
                avg_precip = float(np.mean(precip_values)) if len(precip_values) > 0 else 100.0
                
                if avg_precip > 0:
                    ratio = fc_val / avg_precip
                    if ratio > 1.15:
                        above, near, below, category = 45, 35, 20, "Above Normal"
                    elif ratio < 0.85:
                        above, near, below, category = 20, 35, 45, "Below Normal"
                    else:
                        above, near, below, category = 33, 34, 33, "Near Normal"
                else:
                    above, near, below, category = 33, 34, 33, "Near Normal"
                
                # Calculate actual forecast month
                total_months = (model_run_month - 1) + int(lead_month)
                fc_year = model_run_year + (total_months // 12)
                fc_month = (total_months % 12) + 1
                
                monthly_forecast.append({
                    "month": f"{fc_year}-{fc_month:02d}",
                    "lead_month": int(lead_month),
                    "rainfall_mm": round(fc_val, 1),
                    "above_normal_pct": above,
                    "near_normal_pct": near,
                    "below_normal_pct": below,
                    "dominant_category": category,
                })
            
            # Cleanup
            tmp_precip.unlink(missing_ok=True)
            
            print(f"[DEBUG] ✅ ECMWF SEAS5 fetch successful ({len(monthly_forecast)} months)")
            return {
                "provider": "ECMWF SEAS5",
                "forecast_type": "tercile_probabilities",
                "monthly_forecast": monthly_forecast,
            }
        except Exception as e:
            print(f"[DEBUG] ⚠️  ECMWF fetch failed: {type(e).__name__}: {str(e)[:80]}")
            return None
    elif SEASONAL_FORECAST_WSP == "iri":
        return module.fetch_iri_forecast(latitude, longitude, forecast_days)
    else:
        raise ValueError(f"No fetch function defined for {SEASONAL_FORECAST_WSP}")


def analyse_rain(forecast: dict, rain_threshold_mm: float = 1.0) -> dict:
    """
    Generic rain analysis function - works with any forecast structure.
    
    Args:
        forecast: Forecast dictionary with 'daily' key containing daily data
        rain_threshold_mm: Minimum rainfall to count as "rainy day"
    
    Returns:
        Dictionary with rain analysis metrics
    """
    daily = forecast.get("daily", [])
    if not daily:
        return {
            "has_rainy_event": False,
            "num_rainy_days": 0,
            "next_rainy_day": None,
            "total_forecast_rain_mm": 0,
            "peak_rain_day": None,
            "peak_rain_mm": 0,
            "rainy_days_detail": [],
        }
    
    # Handle both precipitation_mm and precipitation_sum keys
    rainy_days = [
        d for d in daily 
        if d.get("precipitation_mm", d.get("precipitation_sum", 0)) >= rain_threshold_mm
    ]
    
    # Find peak rain day
    precip_key = "precipitation_mm" if "precipitation_mm" in daily[0] else "precipitation_sum"
    max_day = max(daily, key=lambda d: d.get(precip_key, 0))
    
    return {
        "has_rainy_event": len(rainy_days) > 0,
        "num_rainy_days": len(rainy_days),
        "next_rainy_day": rainy_days[0]["date"] if rainy_days else None,
        "total_forecast_rain_mm": round(
            sum(d.get("precipitation_mm", d.get("precipitation_sum", 0)) for d in rainy_days),
            2
        ),
        "peak_rain_day": max_day["date"],
        "peak_rain_mm": max_day.get("precipitation_mm", max_day.get("precipitation_sum", 0)),
        "rainy_days_detail": rainy_days,
    }


def fetch_soil_data(latitude: float, longitude: float) -> Optional[dict]:
    """
    Fetch and format soil data from iSDAsoil for the given location.
    Returns None gracefully if soil module not available or fetch fails.
    
    REQUIRES: iSDAsoil API credentials in environment or .env file
      - ISDASOIL_USERNAME=your_username
      - ISDASOIL_PASSWORD=your_password
    
    Args:
        latitude: Location latitude
        longitude: Location longitude
    
    Returns:
        Dictionary with formatted soil data (for use in prompts), or None if unavailable
    """
    if not SOIL_AVAILABLE:
        print("[DEBUG] ⚠️  Soil module not available (wsp_soil_isda/wsp_soil_integration import failed)")
        return None
    
    try:
        print(f"[DEBUG] Fetching soil data from iSDAsoil API for ({latitude}, {longitude})...")
        soil_data = get_soil_data(latitude, longitude)
        
        if soil_data and soil_data.get("properties"):
            num_props = len(soil_data["properties"])
            props_list = ", ".join(soil_data["properties"].keys())
            print(f"[DEBUG] ✅ Soil data fetched: {num_props} properties available")
            print(f"[DEBUG]    Properties: {props_list}")
            return soil_data  # Return raw API data (will be formatted by prepare_soil_prompt_vars)
        else:
            print(f"[DEBUG] ⚠️  Soil API returned empty response (location may not be in coverage)")
            return None
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"[DEBUG] ⚠️  Soil data fetch failed ({error_type}): {error_msg[:100]}")
        return None


def prepare_soil_prompt_vars(soil_data: Optional[dict]) -> dict:
    """
    Extract and format soil variables for use in the prompt.
    
    Args:
        soil_data: Raw soil data from iSDAsoil API
    
    Returns:
        Dictionary with soil_data_summary, soil_risk_flags, soil_recommendations
    """
    if not soil_data or not SOIL_AVAILABLE:
        return {
            "soil_data_summary": "No soil data available",
            "soil_risk_flags": "",
            "soil_recommendations": "",
            "soil_health_status": ""
        }
    
    try:
        soil_vars = format_soil_for_prompt(soil_data)
        return soil_vars
    except Exception as e:
        print(f"[DEBUG] Soil format error: {e}")
        return {
            "soil_data_summary": "Could not process soil data",
            "soil_risk_flags": "",
            "soil_recommendations": "",
            "soil_health_status": ""
        }


# ─────────────────────────────────────────────────────────────
# SEASONAL FORECAST MONTH NAME EXTRACTOR
# ─────────────────────────────────────────────────────────────

def extract_seasonal_month_names(seasonal_forecast: dict) -> str:
    """
    Extract month names from seasonal forecast data.
    
    Args:
        seasonal_forecast: Seasonal forecast dictionary from fetch_seasonal_forecast()
    
    Returns:
        String with month names (e.g., "April-May-June" or "May-June")
    """
    from datetime import datetime
    import calendar
    
    if not seasonal_forecast:
        return "Unknown months"
    
    month_names = []
    
    try:
        # ECMWF SEAS5: monthly_forecast list
        if seasonal_forecast.get("provider", "").upper().startswith("ECMWF"):
            monthly_records = seasonal_forecast.get("monthly_forecast", [])
            for record in monthly_records[:3]:  # Get first 3 months max
                date_str = record.get("month", "")
                if date_str and len(date_str) >= 7:  # Format: "2026-04"
                    try:
                        date_obj = datetime.strptime(date_str, "%Y-%m")
                        month_name = calendar.month_name[date_obj.month]
                        month_names.append(month_name)
                    except:
                        pass
        
        # NOAA CPC: seasonal_months list
        elif seasonal_forecast.get("forecast_type") == "probability_outlook":
            months_data = seasonal_forecast.get("seasonal_months", [])
            for record in months_data[:3]:  # Get first 3 months max
                month_str = record.get("month", "")
                if month_str:
                    try:
                        # Try parsing different formats
                        if len(month_str) == 7 and "-" in month_str:  # "2026-04"
                            date_obj = datetime.strptime(month_str, "%Y-%m")
                            month_name = calendar.month_name[date_obj.month]
                            month_names.append(month_name)
                        elif month_str.isdigit() and 1 <= int(month_str) <= 12:
                            month_name = calendar.month_name[int(month_str)]
                            month_names.append(month_name)
                    except:
                        pass
        
        # IRI NMME: daily forecast dates
        elif "IRI" in seasonal_forecast.get("provider", ""):
            daily_records = seasonal_forecast.get("daily", [])
            months_seen = set()
            for record in daily_records[:90]:  # Check first ~3 months of daily data
                date_str = record.get("date", "")
                if date_str and len(date_str) >= 10:  # Format: "2026-04-01"
                    try:
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        month_name = calendar.month_name[date_obj.month]
                        if month_name not in months_seen:
                            month_names.append(month_name)
                            months_seen.add(month_name)
                    except:
                        pass
    
    except Exception as e:
        print(f"[DEBUG] Error extracting month names: {e}")
    
    if month_names:
        return " - ".join(month_names)
    return "Unknown months"


# ─────────────────────────────────────────────────────────────
# DUAL FORECAST ANSWER GENERATOR
# ─────────────────────────────────────────────────────────────

def answer_with_dual_forecast(
    user_question: str,
    farmer_context: dict,
    latitude: float,
    longitude: float,
    daily_forecast_days: int = 16,
    seasonal_forecast_days: int = 100,
    forced_context_date: Optional[str] = None,
) -> str:
    """
    Generate an answer that includes BOTH daily and seasonal forecast information.
    
    Args:
        user_question: The farmer's question
        farmer_context: Dictionary with crop, region, season, etc.
        latitude: Location latitude
        longitude: Location longitude
        daily_forecast_days: Number of days for daily forecast
        seasonal_forecast_days: Number of days for seasonal forecast
    
    Returns:
        LLM response integrating both forecasts
    """
    llm = get_llm()
    
    # Resolve context date early so that forecast fetches can align to the scenario
    if forced_context_date:
        context_date = forced_context_date
    else:
        inferred_date = extract_date_from_question(user_question)
        if inferred_date:
            context_date = inferred_date.strftime("%Y-%m-%d")
        else:
            # Use wsp_config's today definition (local or UTC depending on env toggle)
            context_date = get_today_str()
    # Decide whether to use provider weather context: only use provider data if the
    # resolved context_date is today's date. For scenario dates (anything other than
    # today's date) we will NOT use provider weather context in the prompt.
    # Use wsp_config's today string so comparisons are consistent for operators
    today_str = get_today_str()
    use_provider_context = (context_date == today_str)

    daily_forecast = None
    seasonal_forecast = None
    daily_error = None
    seasonal_error = None

    if use_provider_context:
        # Fetch both forecasts (pass start_date where possible; providers may ignore)
        try:
            daily_forecast = fetch_daily_forecast(latitude, longitude, daily_forecast_days, start_date=context_date)
            daily_error = None
        except Exception as e:
            daily_forecast = None
            daily_error = str(e)
            print(f"[DEBUG] Daily forecast error: {daily_error}")
        
        try:
            seasonal_forecast = fetch_seasonal_forecast(latitude, longitude, seasonal_forecast_days, start_date=context_date)
            seasonal_error = None
        except Exception as e:
            seasonal_forecast = None
            seasonal_error = str(e)
            print(f"[DEBUG] Seasonal forecast error: {seasonal_error}")
    else:
        print(f"[DEBUG] Skipping provider weather fetches because context_date ({context_date}) != today ({today_str})")

    # --- Provenance: record what start dates were requested/returned ---
    daily_prov = {
        "requested_start_date": None,
        "fetched_start_date": None,
        "fetched_end_date": None,
        "start_date_honored": False,
        "provider_used": use_provider_context,
    }
    if isinstance(daily_forecast, dict):
        daily_prov["requested_start_date"] = daily_forecast.get("requested_start_date")
        daily_prov["fetched_start_date"] = daily_forecast.get("fetched_start_date")
        daily_prov["fetched_end_date"] = daily_forecast.get("fetched_end_date")
        daily_prov["start_date_honored"] = bool(daily_forecast.get("start_date_honored", False))

    seasonal_prov = {
        "requested_start_date": None,
        "fetched_start_date": None,
        "fetched_end_date": None,
        "start_date_honored": False,
        "provider_used": use_provider_context,
    }
    if isinstance(seasonal_forecast, dict):
        # Many seasonal providers won't include these fields yet; try to read them when present
        seasonal_prov["requested_start_date"] = seasonal_forecast.get("requested_start_date")
        seasonal_prov["fetched_start_date"] = seasonal_forecast.get("fetched_start_date")
        seasonal_prov["fetched_end_date"] = seasonal_forecast.get("fetched_end_date")
        seasonal_prov["start_date_honored"] = bool(seasonal_forecast.get("start_date_honored", False))
    
    # Fetch soil data (optional)
    try:
        soil_data = fetch_soil_data(latitude, longitude)
        soil_vars = prepare_soil_prompt_vars(soil_data)
    except Exception as e:
        print(f"[DEBUG] Soil data error: {e}")
        soil_data = None
        soil_vars = {
            "soil_data_summary": "",
            "soil_risk_flags": "",
            "soil_recommendations": "",
            "soil_health_status": ""
        }
    
    # Analyze rain for both forecasts

    # Analyze rain for both forecasts
    if daily_forecast:
        daily_rain = analyse_rain(daily_forecast)
        daily_provider = daily_forecast.get("provider", "Unknown")
        daily_range = f"Next {daily_forecast_days} days"
    else:
        daily_rain = {
            "has_rainy_event": False, "num_rainy_days": 0, "next_rainy_day": None,
            "total_forecast_rain_mm": 0, "peak_rain_day": None, "peak_rain_mm": 0,
            "rainy_days_detail": []
        }
        daily_provider = f"Error: {daily_error}"
        daily_range = "N/A"

    if seasonal_forecast:
        seasonal_rain = analyse_rain(seasonal_forecast)
        seasonal_provider = seasonal_forecast.get("provider", "Unknown")
        seasonal_months = extract_seasonal_month_names(seasonal_forecast)
        seasonal_range = f"Next {seasonal_forecast_days} days ({seasonal_months})"
    else:
        seasonal_rain = {
            "has_rainy_event": False, "num_rainy_days": 0, "next_rainy_day": None,
            "total_forecast_rain_mm": 0, "peak_rain_day": None, "peak_rain_mm": 0,
            "rainy_days_detail": []
        }
        seasonal_provider = f"Error: {seasonal_error}"
        seasonal_range = "N/A"

    # Extract seasonal category info - handle ECMWF SEAS5, NOAA CPC, IRI
    seasonal_category = "Not available"
    seasonal_prob_info = ""
    seasonal_mm_info = ""

    if seasonal_forecast:
        # ECMWF SEAS5: Tercile probabilities from monthly_forecast
        if seasonal_forecast.get("provider", "").upper().startswith("ECMWF"):
            monthly_records = seasonal_forecast.get("monthly_forecast", [])
            if monthly_records:
                first_month = monthly_records[0]
                seasonal_category = first_month.get("dominant_category", "Normal")
                above = first_month.get("above_normal_pct", 33)
                normal = first_month.get("near_normal_pct", 34)
                below = first_month.get("below_normal_pct", 33)
                rainfall_mm = first_month.get("rainfall_mm", "unknown")
                seasonal_prob_info = f" | Probabilities: Above Normal {above}%, Near Normal {normal}%, Below Normal {below}% | Expected rainfall: {rainfall_mm}mm"
        # NOAA CPC: Probability-based outlook
        elif seasonal_forecast.get("forecast_type") == "probability_outlook":
            months_data = seasonal_forecast.get("seasonal_months", [])
            if months_data:
                first_month = months_data[0]
                seasonal_category = first_month.get("category", "Normal")
                above = first_month.get("above_normal_prob", 33)
                normal = first_month.get("normal_prob", 34)
                below = first_month.get("below_normal_prob", 33)
                seasonal_prob_info = f" | Probabilities: Above Normal {above}%, Normal {normal}%, Below Normal {below}%"
        # IRI NMME: Monthly precipitation (mm) values
        elif "IRI" in seasonal_forecast.get("provider", ""):
            daily_records = seasonal_forecast.get("daily", [])
            if daily_records:
                # Show first 3-4 months of IRI forecast
                summary = ", ".join([f"{d['date']}: {d['precipitation_mm']}mm" for d in daily_records[:4]])
                seasonal_mm_info = f" | Expected monthly: {summary}"
                seasonal_category = f"IRI NMME Seasonal"

    # ─────────────────────────────────────────────
    # Build Biophysical and Temporal Context Blocks
    # ─────────────────────────────────────────────
    biophysical_context = f"""
    SOIL DATA: {soil_vars.get('soil_data_summary','')}
    SOIL RISK FLAGS: {soil_vars.get('soil_risk_flags','')}
    SOIL RECOMMENDATIONS: {soil_vars.get('soil_recommendations','')}
    DAILY WEATHER: Provider: {daily_provider}, Range: {daily_range}, Rainy Days: {daily_rain['num_rainy_days']}, Peak Rain: {daily_rain['peak_rain_day']} ({daily_rain['peak_rain_mm']}mm), Total Rain: {daily_rain['total_forecast_rain_mm']}mm
    SEASONAL WEATHER: Provider: {seasonal_provider}, Range: {seasonal_range}, Category: {seasonal_category}, Probabilities: {seasonal_prob_info}, Monthly Info: {seasonal_mm_info}
    """
    # Temporal context: crop, stage, phenology, season, etc.
    temporal_context = f"""
    CROP: {farmer_context.get('crop','')}
    REGION: {farmer_context.get('region','')}
    SEASON: {farmer_context.get('season','')}
    SCALE: {farmer_context.get('scale_ha','')}
    GROWTH STAGE: (Infer from question/context)
    DATE: {context_date}
    """
    
    # Build the daily_weather_section only if provider context is used. Otherwise provide an empty string
    if use_provider_context and daily_forecast:
        daily_weather_section = f"""
DAILY WEATHER FORECAST:
- Rainy event: {daily_rain.get('has_rainy_event', False)}
- Rainy days ahead: {daily_rain.get('num_rainy_days', 0)}
- Next rainy day: {daily_rain.get('next_rainy_day', 'N/A')}
- Peak rainfall: {daily_rain.get('peak_rain_day', 'N/A')} ({daily_rain.get('peak_rain_mm', 0)} mm)
- Total rainfall: {daily_rain.get('total_forecast_rain_mm', 0)} mm
"""
    else:
        daily_weather_section = ""  # no weather info to include

    # If provider context was skipped, remove seasonal_category to avoid implying seasonal data
    if not use_provider_context:
        seasonal_category_safe = ""
    else:
        seasonal_category_safe = seasonal_category

    # Use UNIFIED_PROMPT from wsp_config for consistency
    # This ensures all modes use the same GATE framework logic

    # Display context blocks in terminal for transparency/debugging
    print("\n────────────────────────────── CONTEXT BLOCKS ──────────────────────────────")
    print("BIOPHYSICAL CONTEXT:\n" + str(biophysical_context))
    print("\nTEMPORAL CONTEXT:\n" + str(temporal_context))
    print("────────────────────────────────────────────────────────────────────────────\n")

    # Resolve context date: prefer an explicitly forced date from the caller,
    # otherwise fall back to extracting from the user's question, then to today.
    if forced_context_date:
        context_date = forced_context_date
    else:
        inferred_date = extract_date_from_question(user_question)
        if inferred_date:
            context_date = inferred_date.strftime("%Y-%m-%d")
        else:
            context_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Helper to build a complete GATE context dict for the prompt
    def build_gate_context():
        # G: Ground Truth
        gate = {
            "farmer_context": json.dumps(farmer_context, indent=2),
            "latitude": latitude,
            "longitude": longitude,
            "seasonal_category": seasonal_category_safe,
            "soil_data_summary": soil_vars.get("soil_data_summary", "No soil data available"),
            "soil_risk_flags": soil_vars.get("soil_risk_flags", ""),
            "soil_recommendations": soil_vars.get("soil_recommendations", ""),
            # T: Temporal
            "today_date": context_date,
            # A: Actions
            # (Scale & Socioeconomic Factors are in farmer_context)
            # E: End values (purpose)
            # (Farming Purpose inferred from question)
            # Other context for prompt
            "user_question": user_question,
            "daily_weather_section": daily_weather_section,
        }

        # Only add provider provenance keys when provider context is actually used.
        if use_provider_context:
            gate.update({
                "daily_requested_start_date": daily_prov.get("requested_start_date"),
                "daily_fetched_start_date": daily_prov.get("fetched_start_date"),
                "daily_fetched_end_date": daily_prov.get("fetched_end_date"),
                "daily_start_date_honored": daily_prov.get("start_date_honored", False),
                "daily_provider_used": daily_prov.get("provider_used", False),
                "seasonal_requested_start_date": seasonal_prov.get("requested_start_date"),
                "seasonal_fetched_start_date": seasonal_prov.get("fetched_start_date"),
                "seasonal_fetched_end_date": seasonal_prov.get("fetched_end_date"),
                "seasonal_start_date_honored": seasonal_prov.get("start_date_honored", False),
                "seasonal_provider_used": seasonal_prov.get("provider_used", False),
                # Weather summary keys
                "has_rain": daily_rain.get("has_rainy_event", False),
                "num_rainy_days": daily_rain.get("num_rainy_days", 0),
                "next_rainy_day": daily_rain.get("next_rainy_day", "N/A"),
                "peak_rain_day": daily_rain.get("peak_rain_day", "N/A"),
                "peak_rain_mm": daily_rain.get("peak_rain_mm", 0),
                "total_rain_mm": daily_rain.get("total_forecast_rain_mm", 0),
            })

        # Terminal-only debug: print which keys are being sent to the LLM (do not expose to LLM)
        try:
            keys = list(gate.keys())
            print(f"[DEBUG] Prompt vars keys (terminal-only): {keys}")
        except Exception:
            pass
        return gate

    gate_context = build_gate_context()
    result = llm.invoke(UNIFIED_PROMPT.format_messages(**gate_context))
    return result.content.strip()
# BACKWARD COMPATIBILITY - Single Forecast Functions
# ─────────────────────────────────────────────────────────────

def answer_with_weather(
    user_question: str,
    farmer_context: dict,
    latitude: float,
    longitude: float,
    forecast_days: int = 16,
) -> str:
    """
    Single forecast version with optional soil data (backward compatible).
    Uses DAILY_FORECAST_WSP + optional soil data.
    """
    llm = get_llm()
    
    try:
        forecast = fetch_daily_forecast(latitude, longitude, forecast_days)
    except Exception as e:
        return f"⚠️ Could not fetch forecast data: {e}"
    
    rain = analyse_rain(forecast)
    provider = forecast.get("provider", "Unknown")
    
    # Fetch soil data (optional)
    try:
        soil_data = fetch_soil_data(latitude, longitude)
        soil_vars = prepare_soil_prompt_vars(soil_data)
    except Exception as e:
        print(f"[DEBUG] Soil data error: {e}")
        soil_vars = {
            "soil_data_summary": "",
            "soil_risk_flags": "",
            "soil_recommendations": "",
            "soil_health_status": ""
        }
    
    result = llm.invoke(UNIFIED_PROMPT.format_messages(
        farmer_context=json.dumps(farmer_context, indent=2),
        latitude=latitude,
        longitude=longitude,
        today_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        forecast_range=f"Next {forecast_days} days",
        has_rain=rain["has_rainy_event"],
        num_rainy_days=rain["num_rainy_days"],
        next_rainy_day=rain["next_rainy_day"] or "No rain in forecast window",
        total_rain_mm=rain["total_forecast_rain_mm"],
        peak_rain_day=rain["peak_rain_day"],
        peak_rain_mm=rain["peak_rain_mm"],
        rainy_days_json="[]",
        soil_data_summary=soil_vars.get("soil_data_summary", ""),
        soil_risk_flags=soil_vars.get("soil_risk_flags", ""),
        soil_recommendations=soil_vars.get("soil_recommendations", ""),
    ))
    
    return result.content.strip()

def run_chatbot(use_dual_forecast: bool = True):
    """
    Interactive chatbot with dual forecast capability.
    
    Args:
        use_dual_forecast: If True, uses both daily and seasonal forecasts.
                          If False, uses only daily forecast (backward compatible).
    """
    farmer_context = {
        "crop": "Wheat",  # DEFAULT - will be overridden by question if crop mentioned
        "region": DEFAULT_LOCATION_NAME,
        "latitude": DEFAULT_LATITUDE,
        "longitude": DEFAULT_LONGITUDE,
        "scale_ha": 3.0,
    }
    lat, lon = farmer_context["latitude"], farmer_context["longitude"]
    
    print("=" * 70)
    print("  Agricultural Chatbot - Unified Forecast (Daily + Seasonal + Soil)")
    print("=" * 70)
    print(f"  Location         : {farmer_context['region']}")
    print(f"  Daily Forecast   : {DAILY_FORECAST_WSP.upper()}")
    print(f"  Seasonal Forecast: {SEASONAL_FORECAST_WSP.upper()}")
    print(f"  Soil Data        : iSDAsoil API")
    print(f"  LLM              : NaviGator API (UF) | Model: gpt-5")
    print(f"  Dual Forecast    : {'YES' if use_dual_forecast else 'NO'}")
    print("  Type 'quit' to exit.")
    print("=" * 70)
    
    while True:
        user_input = input("\n🌾 Your question: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye! 🌦️")
            break
        if not user_input:
            continue

        # Unified crop and date extraction
        from wsp_config import extract_crop_and_date_json
        extraction = extract_crop_and_date_json(user_input)
        crop = extraction["extracted_crop"]
        context_date = extraction["context_date"]
        date_source = extraction["date_source"]
        user_input_to_answer = user_input

        if crop:
            farmer_context["crop"] = crop
            print(f"\n📌 Detected crop: {crop}")
        else:
            print("\n⚠️  I don't see a specific crop mentioned in your question.")
            print("   Could you please specify which crop you're asking about?")
            print("   (e.g., maize, wheat, potato, beans, sesame, tomato, etc.)")
            crop_input = input("\n🌾 Which crop? ").strip()
            if crop_input.lower() in ("quit", "exit", "q"):
                print("Goodbye! 🌦️")
                break
            if not crop_input:
                print("⚠️  No crop entered. Please try again.")
                continue
            extraction2 = extract_crop_and_date_json(crop_input)
            crop = extraction2["extracted_crop"] if extraction2["extracted_crop"] else crop_input.capitalize()
            farmer_context["crop"] = crop
            print(f"\n📌 Got it! Working with {crop}...")
            user_input_to_answer = user_input

        print(f"🗓️  Context date: {context_date} (source: {date_source})")
        print(f"📝 Extraction JSON: {extraction}")

        # Pass the extracted crop and date to the answer function via context
        # (If you want to inject date into context, update farmer_context or prompt as needed)
        if use_dual_forecast:
            print("⏳ Fetching DAILY, SEASONAL forecasts and SOIL data, generating answer...\n")
            answer = answer_with_dual_forecast(
                user_input_to_answer,
                farmer_context,
                lat,
                lon,
                seasonal_forecast_days=100,
                forced_context_date=context_date,
            )
        else:
            print("⏳ Fetching DAILY forecast and generating answer...\n")
            answer = answer_with_weather(user_input_to_answer, farmer_context, lat, lon)

        print("─" * 70)
        print(answer)
        print("─" * 70)


def run_demo(use_dual_forecast: bool = True):
    """
    Run demo with sample questions and dynamic crop detection.
    """
    farmer_context = {
        "crop": "Wheat",  # DEFAULT - will be overridden by detected crop
        "region": DEFAULT_LOCATION_NAME,
        "latitude": DEFAULT_LATITUDE,
        "longitude": DEFAULT_LONGITUDE,
        "agroecological_zone": "Upper Midland (AEZ IIa)",
        "altitude_m": 1800,
        "season": "Long Rains (MAM)",
        "scale_ha": 3.0,
        "soil_type": "Fertile loam with good drainage",
    }
    
    sample_questions = [
        "Can I still add urea to my maize this week?",
        "Is it safe to spray fungicide on my rice this week?",
        "When should I plan for the next planting season?",
    ]
    
    for q in sample_questions:
        print(f"\n{'='*70}\nQ: {q}\n{'='*70}")
        
        # ✅ DYNAMIC CROP EXTRACTION for demo
        detected_crop = extract_crop_from_question(q)
        if detected_crop:
            print(f"📌 Detected crop: {detected_crop}\n")
        else:
            # For demo mode, we'll use a default crop, but log that no crop was detected
            farmer_context["crop"] = "Wheat"
            print(f"⚠️  No crop detected in question - Using default: {farmer_context['crop']}\n")
        
        if use_dual_forecast:
            print(answer_with_dual_forecast(q, farmer_context, 0.8500, 34.9167))
        else:
            print(answer_with_weather(q, farmer_context, 0.8500, 34.9167))


def answer_from_question(user_question: str, use_dual_forecast: bool = True) -> str:
    """
    Convenience wrapper that accepts only the user's question (runtime-only input).
    It will extract crop and date automatically, build a minimal farmer_context using
    defaults, and call the appropriate answer generator.

    Args:
        user_question: The farmer's question string (required)
        use_dual_forecast: If True, uses both daily + seasonal forecasts (when allowed)

    Returns:
        The LLM-generated answer string.
    """
    extraction = extract_crop_and_date_json(user_question)
    crop = extraction.get("extracted_crop") or "Unknown"
    context_date = extraction.get("context_date")

    farmer_context = {
        "crop": crop,
        "region": DEFAULT_LOCATION_NAME,
        "latitude": DEFAULT_LATITUDE,
        "longitude": DEFAULT_LONGITUDE,
        "scale_ha": 1.0,
    }

    if use_dual_forecast:
        return answer_with_dual_forecast(user_question, farmer_context, DEFAULT_LATITUDE, DEFAULT_LONGITUDE, forced_context_date=context_date)
    else:
        return answer_with_weather(user_question, farmer_context, DEFAULT_LATITUDE, DEFAULT_LONGITUDE)


if __name__ == "__main__":
    import sys
    
    # Check command line arguments
    use_dual = "--single" not in sys.argv
    
    if "demo" in sys.argv:
        run_demo(use_dual_forecast=use_dual)
    else:
        run_chatbot(use_dual_forecast=use_dual)
