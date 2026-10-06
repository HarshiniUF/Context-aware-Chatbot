"""
=============================================================
SEASONAL TOOL — get_seasonal_forecast
Coordinates → monthly rainfall and temperature outlook for the
coming months, compared with the normal climate for those months
=============================================================

Uses ECMWF SEAS5 (system 51) from the Copernicus Climate Data Store:
  dataset "seasonal-monthly-single-levels"
  credentials: ~/.cdsapirc (CDS account)

For each forecast month it compares the forecast ensemble mean with the
hindcast climate mean (ECMWF's own re-forecasts of past years for the
same start month and lead), so "wetter/drier than normal" is relative to
the normal climate of that month, not to the other forecast months.

Facts verified against the downloaded GRIB files:
  - forecastMonth 1 = the month the forecast was started (verifyingMonth
    of lead 1 equals the start month), so leads are read from the file,
    not computed.
  - The grid is global 1°, longitudes 0.5..359.5 → negative longitudes
    must be converted (-16 → 344) before picking the grid cell.
  - A new forecast is published on the 13th of each month; the global
    file (~3 MB, ~40-60 s to download) is cached per start month, so
    later calls for any location are instant.

Never raises: returns {"ok": False, "error": ...} on failure.

Output (dict):
  {
    "ok": bool, "error": str or None,
    "location": {"requested_latitude", "requested_longitude", "grid_latitude", "grid_longitude"},
    "forecast_start_month": "YYYY-MM",
    "months": [{"month": "YYYY-MM", "month_name": "October 2026",
                "precipitation": {"forecast_mm", "normal_mm", "anomaly_mm", "percent_of_normal", "category"},
                "temperature": {"forecast_c", "normal_c", "anomaly_c", "category"}}, ...],
    "season_total": {"forecast_mm", "normal_mm", "percent_of_normal", "category"},
    "metadata": {...},
  }
=============================================================
"""

import calendar
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(PROJECT_DIR, ".cache", "seasonal")
DATASET = "seasonal-monthly-single-levels"
SYSTEM = "51"                      # SEAS5 operational system
HINDCAST_PERIOD = "1993-2016"      # SEAS5 re-forecast years behind the climate mean
RELEASE_DAY = 13                   # C3S publishes the new forecast on the 13th of each month
LEADS = ["1", "2", "3", "4", "5", "6"]
MAX_MONTHS_AHEAD = 6

# Category thresholds (simple, transparent rules on the ensemble mean — not calibrated probabilities)
WET_DRY_PERCENT = 20       # ≥ +20% of normal rainfall → wetter, ≤ -20% → drier
WARM_COOL_C = 0.5          # ≥ +0.5 °C → warmer, ≤ -0.5 °C → cooler
DRY_SEASON_NORMAL_MM = 10  # normal monthly rainfall below this → dry-season month, % of normal not meaningful


def _error(message: str, **extra) -> dict:
    return {"ok": False, "error": message, **extra}


def _start_months(now: datetime) -> list:
    """Forecast start months to try, newest first: this month once released (13th), else last month."""
    this_month = (now.year, now.month)
    last_month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    return [this_month, last_month] if now.day >= RELEASE_DAY else [last_month]


def _cache_path(year: int, month: int) -> str:
    return os.path.join(CACHE_DIR, f"seas5_{year}{month:02d}_tp_t2m.grib")


def _download(year: int, month: int) -> str:
    """Download (once) the global forecast + hindcast climate mean for one start month."""
    path = _cache_path(year, month)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    import cdsapi  # imported here so the other tools work without CDS installed

    os.makedirs(CACHE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".part")
    os.close(fd)
    try:
        cdsapi.Client(quiet=True, progress=False).retrieve(DATASET, {
            "originating_centre": "ecmwf",
            "system": SYSTEM,
            "year": str(year),
            "month": f"{month:02d}",
            "leadtime_month": LEADS,
            "variable": ["total_precipitation", "2m_temperature"],
            "product_type": ["ensemble_mean", "hindcast_climate_mean"],
            "data_format": "grib",
        }, tmp)
        os.replace(tmp, path)  # atomic: a half-written file is never used
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def _read_point(path: str, latitude: float, longitude: float) -> tuple:
    """
    Values at the grid cell nearest to the point.
    Returns ({(shortName, dataType, "YYYY-MM"): value}, grid_lat, grid_lon).
    """
    import eccodes

    values, grid = {}, None
    with open(path, "rb") as f:
        while (h := eccodes.codes_grib_new_from_file(f)) is not None:
            try:
                if grid is None:
                    lat0 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees")
                    lon0 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
                    dlat = eccodes.codes_get(h, "jDirectionIncrementInDegrees")
                    dlon = eccodes.codes_get(h, "iDirectionIncrementInDegrees")
                    ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
                    j = min(max(round((lat0 - latitude) / dlat), 0), nj - 1)      # rows run north → south
                    i = round(((longitude % 360) - lon0) / dlon) % ni              # grid uses 0..360 longitudes
                    grid = (j * ni + i, lat0 - j * dlat, ((lon0 + i * dlon + 180) % 360) - 180)
                month = str(eccodes.codes_get(h, "verifyingMonth"))
                key = (eccodes.codes_get(h, "shortName"), eccodes.codes_get(h, "dataType"), f"{month[:4]}-{month[4:]}")
                values[key] = float(eccodes.codes_get_values(h)[grid[0]])
            finally:
                eccodes.codes_release(h)
    return values, grid[1], grid[2]


def _rain_category(forecast_mm: float, normal_mm: float) -> tuple:
    if normal_mm < DRY_SEASON_NORMAL_MM:
        return None, "dry-season month (normally < 10 mm; % of normal not meaningful)"
    percent = round(100 * forecast_mm / normal_mm)
    if percent >= 100 + WET_DRY_PERCENT:
        return percent, "wetter than normal"
    if percent <= 100 - WET_DRY_PERCENT:
        return percent, "drier than normal"
    return percent, "near normal"


def _temp_category(anomaly_c: float) -> str:
    if anomaly_c >= WARM_COOL_C:
        return "warmer than normal"
    if anomaly_c <= -WARM_COOL_C:
        return "cooler than normal"
    return "near normal"


def get_seasonal_forecast(latitude: float, longitude: float, months_ahead: int = 3) -> dict:
    """
    Monthly rainfall and temperature outlook for the coming months.

    Args:
        latitude, longitude: location in decimal degrees
        months_ahead: number of months to return, starting with the current month (1-6)
    """
    retrieved_at = datetime.now(timezone.utc)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _error(f"Invalid coordinates: lat={latitude}, lon={longitude}")
    if not isinstance(months_ahead, int) or not 1 <= months_ahead <= MAX_MONTHS_AHEAD:
        return _error(f"months_ahead must be an integer from 1 to {MAX_MONTHS_AHEAD}")

    # ── Get the newest available forecast (cached per start month) ──
    path, start, failures = None, None, []
    for year, month in _start_months(retrieved_at):
        try:
            path, start = _download(year, month), (year, month)
            break
        except Exception as e:
            failures.append(f"{year}-{month:02d}: {type(e).__name__}: {str(e)[:200]}")
    if path is None:
        return _error("Could not download the ECMWF seasonal forecast from the Copernicus CDS "
                      f"(check ~/.cdsapirc). Tried: {'; '.join(failures)}")

    try:
        values, grid_lat, grid_lon = _read_point(path, latitude, longitude)
    except Exception as e:
        return _error(f"Could not read the seasonal forecast file: {type(e).__name__}: {e}")

    # ── Build monthly records from the current month onwards (earlier leads are already past) ──
    current = f"{retrieved_at.year}-{retrieved_at.month:02d}"
    months_available = sorted({m for (_, _, m) in values if m >= current})
    months = []
    for m in months_available[:months_ahead]:
        try:
            year, month = int(m[:4]), int(m[5:])
            seconds = calendar.monthrange(year, month)[1] * 86400
            rain_fc = values[("tprate", "em", m)] * seconds * 1000      # m/s → mm per month
            rain_nm = values[("tprate", "hcmean", m)] * seconds * 1000
            temp_fc = values[("2t", "em", m)] - 273.15                   # K → °C
            temp_nm = values[("2t", "hcmean", m)] - 273.15
        except KeyError:
            continue
        percent, rain_cat = _rain_category(rain_fc, rain_nm)
        months.append({
            "month": m,
            "month_name": f"{calendar.month_name[month]} {year}",
            "precipitation": {"forecast_mm": round(rain_fc, 1), "normal_mm": round(rain_nm, 1),
                              "anomaly_mm": round(rain_fc - rain_nm, 1), "percent_of_normal": percent,
                              "category": rain_cat},
            "temperature": {"forecast_c": round(temp_fc, 1), "normal_c": round(temp_nm, 1),
                            "anomaly_c": round(temp_fc - temp_nm, 1),
                            "category": _temp_category(temp_fc - temp_nm)},
        })
    if not months:
        return _error("The seasonal forecast has no data for the coming months at this location.")

    # Season total over the rainy months only: tiny dry-season normals would inflate the percentage
    rainy = [x for x in months if x["precipitation"]["normal_mm"] >= DRY_SEASON_NORMAL_MM]
    total_fc = sum(x["precipitation"]["forecast_mm"] for x in rainy)
    total_nm = sum(x["precipitation"]["normal_mm"] for x in rainy)
    total_pct, total_cat = _rain_category(total_fc, total_nm) if rainy else (None, "all dry-season months")

    return {
        "ok": True,
        "error": None,
        "location": {"requested_latitude": latitude, "requested_longitude": longitude,
                     "grid_latitude": grid_lat, "grid_longitude": grid_lon},
        "forecast_start_month": f"{start[0]}-{start[1]:02d}",
        "months": months,
        "season_total": {"months": [x["month"] for x in rainy], "forecast_mm": round(total_fc, 1),
                         "normal_mm": round(total_nm, 1), "percent_of_normal": total_pct,
                         "category": total_cat},
        "warnings": ([f"Only {len(months)} month(s) available from this forecast (requested {months_ahead})."]
                     if len(months) < months_ahead else []),
        "metadata": {
            "provider": "ECMWF SEAS5 via Copernicus Climate Data Store",
            "system": SYSTEM,
            "resolution": "1° grid (~110 km): regional outlook, not field-level",
            "normal_climate": f"SEAS5 hindcast climate mean ({HINDCAST_PERIOD}) for the same start month and lead",
            "statistic": "ensemble mean (51 members); categories use fixed thresholds, not probabilities",
            "category_rules": {"rain": f"±{WET_DRY_PERCENT}% of normal", "temperature": f"±{WARM_COOL_C} °C"},
            "retrieved_at": retrieved_at.isoformat(),
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_seasonal_forecast(1.0157, 34.9865, months_ahead=3), indent=2))
