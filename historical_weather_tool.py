"""
=============================================================
HISTORICAL WEATHER TOOL — get_historical_weather
Coordinates, past period, variables → observed daily weather
(ERA5 reanalysis), optionally compared with the 1991-2020 normal
=============================================================

Uses the Open-Meteo Historical Weather API (free, no key):
  https://archive-api.open-meteo.com/v1/archive
Model "era5_seamless" (ERA5-Land ~9 km where available, else ERA5 ~25 km)
is used for every year, so past years and normals are comparable; the
default "best_match" switches to a newer model from ~2017 and would make
recent years look warmer. ERA5 data starts in 1940 and lags ~6 days; the
missing recent days are filled from "best_match" and flagged in warnings.

Short periods (up to 62 days) return daily values; longer periods return
monthly totals/means instead, so the answer stays readable.

With compare_to_normal (periods up to a year), the same calendar window is
taken from every year 1991-2020 at this location, giving the normal rainfall
total and mean temperature for that window, percent of normal, and how many
of those 30 years were drier than this one.

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
    "daily":    [{"date", "weekday", variable: value, ...}, ...]   (periods ≤ 62 days)
    "monthly":  [{"month", "days", variable: value, ...}, ...]     (longer periods)
    "summary":  {variable: {"total"/"min"/"max"/"mean": value, "unit": unit, ...}},
    "comparison_to_normal": {"precipitation": {...}, "temperature": {...}} or None,
    "metadata": {"provider", "data_type", "retrieved_at", "dates_are"},
    "warnings": [str],
  }
=============================================================
"""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import requests

from seasonal_tool import WARM_COOL_C, WET_DRY_PERCENT
from weather_tool import WEATHER_VARIABLES as _ALL_WEATHER_VARIABLES, _error, _summarize

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
EARLIEST_DATE = date(1940, 1, 2)   # 1940-01-01 comes back partly empty
MAX_PERIOD_DAYS = 3660             # ~10 years per call
DAILY_DETAIL_MAX_DAYS = 62         # longer periods are returned as monthly aggregates
NORMAL_FIRST_YEAR, NORMAL_LAST_YEAR = 1991, 2020   # WMO standard climate normal period
NORMAL_MAX_DAYS = 366
DRY_PERIOD_NORMAL_MM = 10          # normal rain below this → % of normal not meaningful
REQUEST_TIMEOUT_S = 60
MODEL = "era5_seamless"            # one consistent dataset for all years
RECENT_FILL_MODEL = "best_match"   # fills the days ERA5 has not reached yet
RECENT_FILL_DAYS = 14

# Same variables as the forecast tool, minus rain probability (a forecast-only quantity)
WEATHER_VARIABLES = {k: v for k, v in _ALL_WEATHER_VARIABLES.items() if k != "precipitation_probability"}
DEFAULT_VARIABLES = ["precipitation", "temperature_max", "temperature_min", "et0"]
NORMAL_API_VARIABLES = ["precipitation_sum", "temperature_2m_mean"]


def _shift_year(d: date, year: int) -> date:
    """Same calendar day in another year (29 Feb → 28 Feb)."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


def _fetch(params: dict) -> dict:
    """One archive request; raises RuntimeError with Open-Meteo's reason on rejection."""
    response = requests.get(ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT_S)
    data = response.json()
    if response.status_code != 200 or data.get("error"):
        raise RuntimeError(data.get("reason", f"HTTP {response.status_code}"))
    return data


@lru_cache(maxsize=32)
def _fetch_reference(latitude: float, longitude: float) -> tuple:
    """Daily rain and mean temperature 1991-2021 (2021 so windows crossing New Year fit). Cached per point."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": f"{NORMAL_FIRST_YEAR}-01-01",
        "end_date": f"{NORMAL_LAST_YEAR + 1}-12-31",
        "daily": ",".join(NORMAL_API_VARIABLES),
        "timezone": "auto",
        "models": MODEL,
    }
    daily = _fetch(params)["daily"]
    rain = dict(zip(daily["time"], daily["precipitation_sum"]))
    temp = dict(zip(daily["time"], daily["temperature_2m_mean"]))
    return rain, temp


def _rain_category(percent: int) -> str:
    if percent >= 100 + WET_DRY_PERCENT:
        return "wetter than normal"
    if percent <= 100 - WET_DRY_PERCENT:
        return "drier than normal"
    return "near normal"


def _temp_category(anomaly_c: float) -> str:
    if anomaly_c >= WARM_COOL_C:
        return "warmer than normal"
    if anomaly_c <= -WARM_COOL_C:
        return "cooler than normal"
    return "near normal"


def _compare_to_normal(latitude: float, longitude: float, start: date, n_days: int,
                       rain_values: list, temp_values: list) -> tuple:
    """(comparison dict or None, warnings) for this window against the same window in 1991-2020."""
    if None in rain_values or None in temp_values:
        return None, ["Not compared with normal: some days in the period have no data yet."]
    try:
        ref_rain, ref_temp = _fetch_reference(latitude, longitude)
    except Exception as e:
        return None, [f"Not compared with normal: could not fetch 1991-2020 data ({e})."]

    year_rain, year_temp = {}, {}
    for year in range(NORMAL_FIRST_YEAR, NORMAL_LAST_YEAR + 1):
        first = _shift_year(start, year)
        days = [(first + timedelta(days=i)).isoformat() for i in range(n_days)]
        rain = [ref_rain.get(d) for d in days]
        temp = [ref_temp.get(d) for d in days]
        if None not in rain and None not in temp:
            year_rain[year] = sum(rain)
            year_temp[year] = sum(temp) / n_days
    if not year_rain:
        return None, ["Not compared with normal: no 1991-2020 data for this window."]

    actual_rain = sum(rain_values)
    actual_temp = sum(temp_values) / n_days
    normal_rain = sum(year_rain.values()) / len(year_rain)
    normal_temp = sum(year_temp.values()) / len(year_temp)
    drier_years = sum(1 for v in year_rain.values() if v < actual_rain)
    warmer_years = sum(1 for v in year_temp.values() if v > actual_temp)
    wettest = max(year_rain, key=year_rain.get)
    driest = min(year_rain, key=year_rain.get)

    if normal_rain < DRY_PERIOD_NORMAL_MM:
        percent, rain_cat = None, f"dry period (normally < {DRY_PERIOD_NORMAL_MM} mm; % of normal not meaningful)"
    else:
        percent = round(100 * actual_rain / normal_rain)
        rain_cat = _rain_category(percent)
    anomaly = actual_temp - normal_temp

    comparison = {
        "reference_period": f"{NORMAL_FIRST_YEAR}-{NORMAL_LAST_YEAR} (same calendar days each year)",
        "years_compared": len(year_rain),
        "precipitation": {
            "actual_mm": round(actual_rain, 1),
            "normal_mm": round(normal_rain, 1),
            "anomaly_mm": round(actual_rain - normal_rain, 1),
            "percent_of_normal": percent,
            "category": rain_cat,
            "years_drier_than_this": drier_years,
            "driest_year": {"year": driest, "mm": round(year_rain[driest], 1)},
            "wettest_year": {"year": wettest, "mm": round(year_rain[wettest], 1)},
        },
        "temperature": {
            "actual_mean_c": round(actual_temp, 1),
            "normal_mean_c": round(normal_temp, 1),
            "anomaly_c": round(anomaly, 1),
            "category": _temp_category(anomaly),
            "years_warmer_than_this": warmer_years,
        },
        "category_rules": {"rain": f"±{WET_DRY_PERCENT}% of normal", "temperature": f"±{WARM_COOL_C} °C"},
    }
    return comparison, []


def _monthly(variables: list, daily: list) -> list:
    """Per calendar month: totals for summed variables, max/min/mean for the others."""
    months = {}
    for row in daily:
        months.setdefault(row["date"][:7], []).append(row)
    result = []
    for month, rows in months.items():
        entry = {"month": month, "days": len(rows)}
        for v in variables:
            nums = [r[v] for r in rows if r[v] is not None]
            how = WEATHER_VARIABLES[v][1]
            if not nums:
                entry[v] = None
            elif how == "sum":
                entry[v] = round(sum(nums), 1)
            elif how == "max":
                entry[v] = max(nums)
            elif how == "min":
                entry[v] = min(nums)
            else:
                entry[v] = round(sum(nums) / len(nums), 2)
        result.append(entry)
    return result


def get_historical_weather(latitude: float,
                           longitude: float,
                           start_date: str,
                           end_date: Optional[str] = None,
                           variables: Optional[list] = None,
                           compare_to_normal: bool = True) -> dict:
    """
    Observed (reanalysis) daily weather for a past period.

    Args:
        latitude, longitude: location in decimal degrees
        start_date: first day, YYYY-MM-DD (1940-01-02 or later)
        end_date: last day, YYYY-MM-DD, before today (default: start_date)
        variables: friendly names from WEATHER_VARIABLES (default: DEFAULT_VARIABLES)
        compare_to_normal: add rain/temperature vs the 1991-2020 normal (periods up to 366 days)
    """
    retrieved_at = datetime.now(timezone.utc).isoformat()

    # ── Validate inputs ──
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _error(f"Invalid coordinates: lat={latitude}, lon={longitude}")
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else start
    except (TypeError, ValueError):
        return _error(f"Dates must be YYYY-MM-DD, got start_date='{start_date}', end_date='{end_date}'")
    today = datetime.now(timezone.utc).date()
    if end < start:
        return _error(f"end_date {end} is before start_date {start}")
    if start < EARLIEST_DATE:
        return _error(f"Historical data starts on {EARLIEST_DATE}")
    if end >= today:
        return _error(f"end_date must be before today ({today}); for today and future days use get_weather_forecast")
    n_days = (end - start).days + 1
    if n_days > MAX_PERIOD_DAYS:
        return _error(f"Period is {n_days} days; the maximum per call is {MAX_PERIOD_DAYS} (~10 years)")
    variables = list(dict.fromkeys(variables or DEFAULT_VARIABLES))
    unknown = [v for v in variables if v not in WEATHER_VARIABLES]
    if unknown:
        return _error(f"Unknown variables {unknown}. Valid: {sorted(WEATHER_VARIABLES)}")

    # Rain and mean temperature are always fetched: the normal comparison needs them
    api_variables = list(dict.fromkeys([WEATHER_VARIABLES[v][0] for v in variables] + NORMAL_API_VARIABLES))
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(api_variables),
        "timezone": "auto",  # dates are local calendar days at the location
        "models": MODEL,
    }

    # ── Fetch ──
    try:
        data = _fetch(params)
    except RuntimeError as e:
        return _error(f"Open-Meteo rejected the request: {e}")
    except Exception as e:
        return _error(f"Could not reach Open-Meteo: {e}")

    daily_raw = data.get("daily", {})
    units_raw = data.get("daily_units", {})
    dates = daily_raw.get("time", [])
    warnings = []

    # ── Fill the last days ERA5 has not reached yet from best_match ──
    recent = (today - timedelta(days=RECENT_FILL_DAYS)).isoformat()
    gaps = [i for i, d in enumerate(dates) if d >= recent
            and any(daily_raw.get(k, [None] * len(dates))[i] is None for k in api_variables)]
    if gaps:
        try:
            fill = _fetch({**params, "start_date": dates[gaps[0]], "models": RECENT_FILL_MODEL})["daily"]
            fill_index = {d: j for j, d in enumerate(fill["time"])}
            filled = set()
            for i in gaps:
                j = fill_index.get(dates[i])
                for k in api_variables:
                    if daily_raw[k][i] is None and j is not None and fill[k][j] is not None:
                        daily_raw[k][i] = fill[k][j]
                        filled.add(dates[i])
            if filled:
                warnings.append(f"{len(filled)} most recent day(s) ({min(filled)} to {max(filled)}) are not in "
                                "ERA5 yet; filled from Open-Meteo's best_match analysis (preliminary).")
        except Exception:
            pass  # the gaps are reported as missing values below

    # A variable with no data on any day is dropped with a warning; only fail if nothing is left
    empty = [v for v in variables if all(x is None for x in daily_raw.get(WEATHER_VARIABLES[v][0], [None]))]
    if empty:
        warnings.append(f"No data for {empty} in this period; left out.")
    variables = [v for v in variables if v not in empty]
    if not variables or not dates:
        return _error("Open-Meteo returned no values for this period.")

    units = {v: units_raw.get(WEATHER_VARIABLES[v][0]) for v in variables}
    daily = [
        {"date": d, "weekday": datetime.strptime(d, "%Y-%m-%d").strftime("%A"),
         **{v: daily_raw[WEATHER_VARIABLES[v][0]][i] for v in variables}}
        for i, d in enumerate(dates)
    ]
    missing = sorted({row["date"] for row in daily for v in variables if row[v] is None})
    if missing:
        shown = missing if len(missing) <= 10 else missing[:10] + ["..."]
        warnings.append(f"Some values missing on {len(missing)} of {len(dates)} days: {shown}")
    summary = {v: _summarize(v, daily_raw[WEATHER_VARIABLES[v][0]], dates, units[v]) for v in variables}

    comparison = None
    if compare_to_normal:
        if n_days > NORMAL_MAX_DAYS:
            warnings.append(f"Not compared with normal: only periods up to {NORMAL_MAX_DAYS} days are compared.")
        else:
            comparison, extra = _compare_to_normal(latitude, longitude, start, n_days,
                                                   daily_raw["precipitation_sum"],
                                                   daily_raw["temperature_2m_mean"])
            warnings.extend(extra)

    result = {
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
        "period": {"start_date": dates[0], "end_date": dates[-1], "days": len(dates)},
        "variables": variables,
        "variable_descriptions": {v: WEATHER_VARIABLES[v][2] for v in variables},
        "units": units,
    }
    if n_days <= DAILY_DETAIL_MAX_DAYS:
        result["daily"] = daily
    else:
        result["monthly"] = _monthly(variables, daily)
    result.update({
        "summary": summary,
        "comparison_to_normal": comparison,
        "metadata": {
            "provider": "Open-Meteo Historical Weather API",
            "model": MODEL,
            "data_type": "ERA5-Land / ERA5 reanalysis (weather model blended with observations, ~9-25 km); "
                         "not a rain-gauge/station record.",
            "retrieved_at": retrieved_at,
            "dates_are": "local calendar days in the timezone above",
        },
        "warnings": warnings,
    })
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(get_historical_weather(1.0157, 34.9865, "2024-03-01", "2024-05-31"), indent=2))
