"""
=============================================================
WEATHER TOOL — get_weather_forecast
Coordinates, time horizon, variables → Open-Meteo daily forecast
with units, dates, retrieval time, and model metadata
=============================================================

Uses the Open-Meteo Forecast API (free, no key):
  https://api.open-meteo.com/v1/forecast
and, for start dates older than its ~90-day past window, the Historical
Forecast API (same parameters, archived model runs going back years):
  https://historical-forecast-api.open-meteo.com/v1/forecast

Never raises: every call returns a dict with "ok": True/False and "error",
so an LLM tool-caller (MCP) can read failures instead of crashing.

Output (dict):
  {
    "ok": bool, "error": str or None,
    "location": {"requested_latitude", "requested_longitude",
                 "grid_latitude", "grid_longitude", "elevation_m", "timezone"},
    "period":   {"start_date", "end_date", "days"},
    "variables": [friendly names],
    "units":    {variable: unit},
    "daily":    [{"date": "YYYY-MM-DD", "weekday": "Monday", variable: value, ...}, ...],
    "summary":  {variable: {"total"/"min"/"max"/"mean": value, "unit": unit, ...}},
    "metadata": {"provider", "model", "model_description", "model_run_time",
                 "retrieved_at", "dates_are": "local calendar days (timezone above)"},
  }
=============================================================
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
FORECAST_PAST_DAYS_LIMIT = 90  # the live API rejects start dates older than ~92 days; keep a margin
MODEL_META_URL = "https://api.open-meteo.com/data/{meta_name}/static/meta.json"
MAX_HORIZON_DAYS = 16
REQUEST_TIMEOUT_S = 20
RAINY_DAY_THRESHOLD_MM = 1.0

# friendly name → (Open-Meteo daily variable, how to summarize, description)
WEATHER_VARIABLES = {
    "precipitation":             ("precipitation_sum", "sum", "Total daily precipitation (rain, showers, snow)"),
    "precipitation_probability": ("precipitation_probability_max", "max", "Maximum daily probability of precipitation"),
    "precipitation_hours":       ("precipitation_hours", "sum", "Hours with precipitation"),
    "temperature_max":           ("temperature_2m_max", "max", "Daily maximum air temperature at 2 m"),
    "temperature_min":           ("temperature_2m_min", "min", "Daily minimum air temperature at 2 m"),
    "temperature_mean":          ("temperature_2m_mean", "mean", "Daily mean air temperature at 2 m"),
    "et0":                       ("et0_fao_evapotranspiration", "sum", "FAO-56 reference evapotranspiration (crop water demand)"),
    "relative_humidity_mean":    ("relative_humidity_2m_mean", "mean", "Daily mean relative humidity at 2 m"),
    "wind_speed_max":            ("wind_speed_10m_max", "max", "Daily maximum wind speed at 10 m"),
    "wind_gusts_max":            ("wind_gusts_10m_max", "max", "Daily maximum wind gusts at 10 m"),
    "solar_radiation":           ("shortwave_radiation_sum", "sum", "Daily total shortwave solar radiation"),
    "sunshine_duration":         ("sunshine_duration", "sum", "Daily sunshine duration"),
    "soil_moisture_0_7cm":       ("soil_moisture_0_to_7cm_mean", "mean", "Mean volumetric soil moisture, 0-7 cm"),
}
DEFAULT_VARIABLES = ["precipitation", "precipitation_probability", "temperature_max", "temperature_min", "et0"]

# Open-Meteo model name → (description, meta.json name for the model run time)
WEATHER_MODELS = {
    "best_match":                     ("Open-Meteo automatic selection: blends the best available models for this location", None),
    "ecmwf_ifs025":                   ("ECMWF IFS 0.25° global model", "ecmwf_ifs025"),
    "ecmwf_aifs025_single":           ("ECMWF AIFS 0.25° AI-based global model", "ecmwf_aifs025_single"),
    "gfs_global":                     ("NOAA GFS global model", "ncep_gfs025"),
    "icon_global":                    ("DWD ICON global model", "dwd_icon"),
    "ukmo_global_deterministic_10km": ("UK Met Office global model, 10 km", "ukmo_global_deterministic_10km"),
    "meteofrance_arpege_world":       ("Météo-France ARPEGE global model", "meteofrance_arpege_world025"),
    "jma_gsm":                        ("JMA GSM global model", "jma_gsm"),
}


def _error(message: str, **extra) -> dict:
    return {"ok": False, "error": message, **extra}


def _model_run_time(meta_name: Optional[str]) -> Optional[str]:
    """ISO time of the latest model run (initialisation), if Open-Meteo publishes it."""
    if not meta_name:
        return None
    try:
        response = requests.get(MODEL_META_URL.format(meta_name=meta_name), timeout=REQUEST_TIMEOUT_S)
        response.raise_for_status()
        init = response.json().get("last_run_initialisation_time")
        return datetime.fromtimestamp(init, tz=timezone.utc).isoformat() if init else None
    except Exception:
        return None


def _summarize(name: str, values: list, dates: list, unit: str) -> dict:
    """Summary for one variable over the period, ignoring missing (null) days."""
    how = WEATHER_VARIABLES[name][1]
    pairs = [(d, v) for d, v in zip(dates, values) if v is not None]
    if not pairs:
        return {"unit": unit, "note": "no data for this period"}
    nums = [v for _, v in pairs]
    summary = {"unit": unit, "days_with_data": len(nums)}
    if how == "sum":
        summary["total"] = round(sum(nums), 2)
        peak_date, peak = max(pairs, key=lambda p: p[1])
        summary["max_day"] = {"date": peak_date, "value": peak}
    elif how == "max":
        peak_date, peak = max(pairs, key=lambda p: p[1])
        summary["max"] = {"date": peak_date, "value": peak}
    elif how == "min":
        low_date, low = min(pairs, key=lambda p: p[1])
        summary["min"] = {"date": low_date, "value": low}
    else:
        summary["mean"] = round(sum(nums) / len(nums), 2)
        summary["min"] = min(nums)
        summary["max"] = max(nums)
    if name == "precipitation":
        rainy = [d for d, v in pairs if v >= RAINY_DAY_THRESHOLD_MM]
        summary["rainy_days"] = len(rainy)
        summary["rainy_day_threshold_mm"] = RAINY_DAY_THRESHOLD_MM
        summary["first_rainy_date"] = rainy[0] if rainy else None
    return summary


def get_weather_forecast(latitude: float,
                         longitude: float,
                         horizon_days: int = 7,
                         variables: Optional[list] = None,
                         start_date: Optional[str] = None,
                         model: str = "best_match") -> dict:
    """
    Daily weather forecast for a location.

    Args:
        latitude, longitude: location in decimal degrees
        horizon_days: number of days to return (1-16)
        variables: friendly variable names (see WEATHER_VARIABLES); default: rain, rain
                   probability, max/min temperature, ET0
        start_date: "YYYY-MM-DD" first forecast day (default: today at the location);
                    dates older than ~90 days are fetched from the Historical Forecast API
        model: "best_match" (default) or a model from WEATHER_MODELS
    """
    retrieved_at = datetime.now(timezone.utc).isoformat()

    # ── Validate inputs ──
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _error(f"Invalid coordinates: lat={latitude}, lon={longitude}")
    if not isinstance(horizon_days, int) or not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        return _error(f"horizon_days must be an integer from 1 to {MAX_HORIZON_DAYS}")
    variables = list(dict.fromkeys(variables or DEFAULT_VARIABLES))
    unknown = [v for v in variables if v not in WEATHER_VARIABLES]
    if unknown:
        return _error(f"Unknown variables {unknown}. Valid: {sorted(WEATHER_VARIABLES)}")
    if model not in WEATHER_MODELS:
        return _error(f"Unknown model '{model}'. Valid: {sorted(WEATHER_MODELS)}")

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(WEATHER_VARIABLES[v][0] for v in variables),
        "timezone": "auto",  # dates are local calendar days at the location
        "models": model,
    }
    url, source = FORECAST_URL, "forecast"
    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            return _error(f"start_date must be YYYY-MM-DD, got '{start_date}'")
        # Open-Meteo rejects start_date + forecast_days together; it needs an end_date
        params["start_date"] = start.isoformat()
        params["end_date"] = (start + timedelta(days=horizon_days - 1)).isoformat()
        if start < datetime.now(timezone.utc).date() - timedelta(days=FORECAST_PAST_DAYS_LIMIT):
            url, source = HISTORICAL_FORECAST_URL, "historical"
    else:
        params["forecast_days"] = horizon_days

    # ── Fetch ──
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
        data = response.json()
        if response.status_code != 200 or data.get("error"):
            reason = data.get("reason", f"HTTP {response.status_code}")
            return _error(f"Open-Meteo rejected the request: {reason}")
    except Exception as e:
        return _error(f"Could not reach Open-Meteo: {e}")

    daily_raw = data.get("daily", {})
    units_raw = data.get("daily_units", {})
    dates = daily_raw.get("time", [])

    units = {v: units_raw.get(WEATHER_VARIABLES[v][0]) for v in variables}
    daily = [
        {"date": d, "weekday": datetime.strptime(d, "%Y-%m-%d").strftime("%A"),
         **{v: daily_raw.get(WEATHER_VARIABLES[v][0], [None] * len(dates))[i] for v in variables}}
        for i, d in enumerate(dates)
    ]
    summary = {
        v: _summarize(v, daily_raw.get(WEATHER_VARIABLES[v][0], []), dates, units[v])
        for v in variables
    }
    description, meta_name = WEATHER_MODELS[model]

    # A variable with no data on any day (e.g. rain probability for past dates) is dropped with a
    # warning; only fail when nothing is left
    warnings = []
    empty = [v for v in variables if all(d[v] is None for d in daily)]
    if empty:
        warnings.append(f"No data for {empty} in this period; left out.")
        variables = [v for v in variables if v not in empty]
        units = {v: units[v] for v in variables}
        summary = {v: summary[v] for v in variables}
        daily = [{k: x for k, x in d.items() if k not in empty} for d in daily]
    if not variables or not dates:
        return _error("Open-Meteo returned no values for this period (too far in the past or future).")
    # Open-Meteo accepts dates near the edge of its range but returns nulls there
    missing = sorted({d["date"] for d in daily for v in variables if d[v] is None})
    if missing:
        warnings.append(f"No data for {len(missing)} of {len(dates)} days: {missing}")

    return {
        "ok": True,
        "error": None,
        "location": {
            "requested_latitude": latitude,
            "requested_longitude": longitude,
            "grid_latitude": data.get("latitude"),
            "grid_longitude": data.get("longitude"),
            "elevation_m": data.get("elevation"),
            "timezone": data.get("timezone"),
        },
        "period": {
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "days": len(dates),
        },
        "variables": variables,
        "variable_descriptions": {v: WEATHER_VARIABLES[v][2] for v in variables},
        "units": units,
        "daily": daily,
        "summary": summary,
        "metadata": {
            "provider": "Open-Meteo" + (" Historical Forecast API" if source == "historical" else ""),
            "model": model,
            "model_description": description,
            # latest run time only makes sense for live forecasts; None for best_match (not published)
            "model_run_time": _model_run_time(meta_name) if source == "forecast" else None,
            "retrieved_at": retrieved_at,
            "dates_are": "local calendar days in the timezone above",
            "data_type": "model forecast; past dates are model estimates, not rain-gauge/station observations",
        },
        "warnings": warnings,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_weather_forecast(1.0157, 34.9865, horizon_days=3), indent=2))
