# -*- coding: utf-8 -*-
"""
=============================================================
DSSAT Weather File Generator — WSP 2: CHC CHIRPS / CHIRPS-GEFS
=============================================================

DATA SOURCE : CHC CHIRPS-GEFS (forecast) + CHIRPS observed (historical)
PROVIDES    : RAIN only (precipitation-only dataset)
MISSING     : TMAX, TMIN, SRAD, DEWP, WIND → filled with -99

AUTO-DETECT:
  Historical dates (before today - 7 days):
    → CHIRPS v2.0 observed via ClimateSERV (Dataset ID 0)
    → Actual gauge-satellite merged observed rainfall

  Recent / Future (within last 7 days or ahead):
    → CHIRPS-GEFS forecast via ClimateSERV (Dataset ID 26)
    → Bias-corrected GEFS precipitation forecast

NOTE: CHIRPS/CHIRPS-GEFS is precipitation-only.
DSSAT fields TMAX, TMIN, SRAD, DEWP, WIND will be -99.

SETUP:
  pip install climateserv pandas numpy requests geopy
=============================================================
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import requests
import climateserv
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable


# ─────────────────────────────────────────────────────────────
# GEOCODING
# ─────────────────────────────────────────────────────────────

def get_location_details(latitude: float, longitude: float) -> Dict[str, str]:
    try:
        geolocator = Nominatim(user_agent="dssat_chirps_script")
        location = geolocator.reverse((latitude, longitude), exactly_one=True, language='en')
        if location and location.address:
            addr = location.raw.get('address', {})
            city    = addr.get('city', addr.get('town', addr.get('village')))
            state   = addr.get('state')
            country = addr.get('country')
            country_code = addr.get('country_code', 'XX').upper()
            parts = [p for p in [city, state, country] if p]
            return {'address': ', '.join(parts), 'country': country,
                    'state': state, 'country_code': country_code}
    except GeocoderUnavailable as e:
        print(f"\n{'!'*70}\n🛑 GEOCODING FAILED: {e}\n{'!'*70}\n")
    except Exception as e:
        print(f"Geocoding error: {e}")
    return {'address': f"Site at {latitude:.2f}, {longitude:.2f}",
            'country': None, 'state': None, 'country_code': 'NOGEO'}


# ─────────────────────────────────────────────────────────────
# CLIMATESERV RESPONSE PARSER
# ─────────────────────────────────────────────────────────────

def _extract_records(raw) -> list:
    """Normalise any ClimateSERV response shape into flat list of dicts."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception as e:
            raise RuntimeError(f"Cannot parse ClimateSERV JSON: {e}")

    if isinstance(raw, list):
        result = []
        for item in raw:
            if isinstance(item, str):
                try: item = json.loads(item)
                except: continue
            if isinstance(item, dict):
                result.append(item)
        return result

    if isinstance(raw, dict):
        for key in ("data", "results", "records", "timeseries", "values"):
            if key in raw and isinstance(raw[key], list):
                return _extract_records(raw[key])
        sample = list(raw.keys())[:3]
        if all(_looks_like_date(k) for k in sample):
            return [{"date": k, "value": v} for k, v in raw.items()]
        for v in raw.values():
            if isinstance(v, list) and v:
                return _extract_records(v)

    raise RuntimeError(f"Unrecognised ClimateSERV response: {type(raw)}")


def _looks_like_date(s: str) -> bool:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try: datetime.strptime(str(s), fmt); return True
        except: pass
    return False


def _extract_mm(val) -> float:
    """Extract float mm from potentially nested value field."""
    if val is None: return 0.0
    if isinstance(val, (int, float)): return max(float(val), 0.0)
    if isinstance(val, dict):
        # Try keys in preference order — use max for best rain estimate
        for k in ("max", "avg", "mean", "value", "total", "sum"):
            if k in val and isinstance(val[k], (int, float)):
                return max(float(val[k]), 0.0)
        for v in val.values():
            if isinstance(v, (int, float)): return max(float(v), 0.0)
    return 0.0


# ─────────────────────────────────────────────────────────────
# CLIMATESERV FETCHER (single date range, single dataset)
# ─────────────────────────────────────────────────────────────

# Dataset IDs in ClimateSERV
CHIRPS_OBSERVED_ID  = 0    # CHIRPS v2.0 daily observed (historical)
CHIRPS_GEFS_ID      = 26   # CHIRPS-GEFS daily forecast (future)

def _fetch_climateserv(
    dataset_id: int,
    latitude: float, longitude: float,
    start_date: str, end_date: str,
    label: str = "CHIRPS",
) -> dict:
    """
    Fetches precipitation from ClimateSERV for a single date range.
    Returns dict keyed by date string → mm value.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d")
    delta    = 0.05

    geometry_coords = [
        [longitude - delta, latitude - delta],
        [longitude + delta, latitude - delta],
        [longitude + delta, latitude + delta],
        [longitude - delta, latitude + delta],
        [longitude - delta, latitude - delta],
    ]

    print(f"  Fetching {label} (dataset {dataset_id}) "
          f"{start_date} → {end_date} ...")

    try:
        raw = climateserv.api.request_data(
            dataset_id,
            "Average",
            start_dt.strftime("%m/%d/%Y"),
            end_dt.strftime("%m/%d/%Y"),
            geometry_coords,
            "", "",
            "memory_object",
        )
    except Exception as e:
        print(f"  ⚠️  ClimateSERV error: {e}. Rain will be 0 for this period.")
        return {}

    try:
        records = _extract_records(raw)
    except Exception as e:
        print(f"  ⚠️  Parse error: {e}. Rain will be 0 for this period.")
        return {}

    rain_by_date = {}
    for record in records:
        raw_date = record.get("date", record.get("time", record.get("Date", "")))
        try:
            if "-" in str(raw_date):
                parsed = datetime.strptime(str(raw_date), "%Y-%m-%d").strftime("%Y-%m-%d")
            else:
                parsed = datetime.strptime(str(raw_date), "%m/%d/%Y").strftime("%Y-%m-%d")
        except Exception:
            parsed = str(raw_date)

        val_field = record.get("value", record.get("Value", record.get("data", 0.0)))
        mm = _extract_mm(val_field)
        rain_by_date[parsed] = round(mm, 2)

    nonzero = sum(1 for v in rain_by_date.values() if v > 0)
    print(f"  {label}: {len(rain_by_date)} records, {nonzero} rainy days.")
    return rain_by_date


# ─────────────────────────────────────────────────────────────
# MAIN FETCHER (auto-detects historical vs forecast)
# ─────────────────────────────────────────────────────────────

def fetch_daily_climate(
    latitude: float, longitude: float,
    start_date: str, end_date: str,
    **kwargs
) -> pd.DataFrame:
    """
    Fetches CHIRPS precipitation with auto-detection:

      Historical dates → CHIRPS v2.0 observed (Dataset 0)
                         Actual satellite+gauge merged rainfall
                         Available from 1981 to present (~2-5 day latency)

      Forecast dates   → CHIRPS-GEFS forecast (Dataset 26)
                         Bias-corrected GEFS, up to 15 days ahead

      Mixed range      → Splits automatically, fetches both, merges.

    Input  : latitude, longitude, start_date (YYYY-MM-DD), end_date (YYYY-MM-DD)
    Output : DataFrame with RAIN populated, all others NaN (written as -99)
    """
    today    = datetime.utcnow().date()
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d").date()
    cutoff   = today - timedelta(days=7)   # safe boundary

    MAX_FORECAST_DAYS = 15
    forecast_cap = today + timedelta(days=MAX_FORECAST_DAYS)
    if end_dt > forecast_cap:
        print(f"  ⚠️  End date {end_date} exceeds max forecast horizon.")
        print(f"  ⚠️  Capping to {forecast_cap} (today + {MAX_FORECAST_DAYS} days).")
        end_dt   = forecast_cap
        end_date = forecast_cap.strftime("%Y-%m-%d")

    rain_by_date = {}

    # ── Historical portion ───────────────────────────────────
    if start_dt <= cutoff:
        hist_end = min(end_dt, cutoff).strftime("%Y-%m-%d")
        hist_rain = _fetch_climateserv(
            CHIRPS_OBSERVED_ID, latitude, longitude,
            start_date, hist_end,
            label="CHIRPS observed"
        )
        rain_by_date.update(hist_rain)

    # ── Forecast portion ─────────────────────────────────────
    if end_dt > cutoff:
        fcast_start = max(start_dt, cutoff + timedelta(days=1)).strftime("%Y-%m-%d")
        fcast_rain  = _fetch_climateserv(
            CHIRPS_GEFS_ID, latitude, longitude,
            fcast_start, end_date,
            label="CHIRPS-GEFS forecast"
        )
        rain_by_date.update(fcast_rain)

    # ── Build full date range DataFrame ─────────────────────
    date_range = pd.date_range(start=start_date, end=end_date, freq="D")
    n = len(date_range)

    data = {
        "date"                    : date_range,
        "temperature_2m_max"      : np.full(n, np.nan),
        "temperature_2m_min"      : np.full(n, np.nan),
        "temperature_2m_mean"     : np.full(n, np.nan),
        "dewpoint_2m_mean"        : np.full(n, np.nan),
        "wind_speed_10m_mean"     : np.full(n, np.nan),
        "wind_speed_10m_max"      : np.full(n, np.nan),
        "precipitation_sum"       : [rain_by_date.get(d.strftime("%Y-%m-%d"), 0.0)
                                     for d in date_range],
        "shortwave_radiation_sum" : np.full(n, np.nan),
    }

    df = pd.DataFrame(data).set_index("date")

    total_rain  = df["precipitation_sum"].sum()
    rainy_days  = (df["precipitation_sum"] > 0).sum()
    print(f"  Final: {n} days | {rainy_days} rainy days | "
          f"{total_rain:.1f} mm total rain")
    print(f"  NOTE: TMAX, TMIN, SRAD, DEWP, WIND not available → -99 in DSSAT.")
    return df


# ─────────────────────────────────────────────────────────────
# ELEVATION
# ─────────────────────────────────────────────────────────────

def get_elevation(latitude: float, longitude: float) -> float:
    try:
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={latitude},{longitude}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()['results'][0]['elevation']
    except Exception as e:
        print(f"Warning: Elevation fetch failed: {e}. Using -99.")
        return -99


# ─────────────────────────────────────────────────────────────
# QA
# ─────────────────────────────────────────────────────────────

def quality_assurance_check(daily_data: pd.DataFrame) -> Dict[str, any]:
    qa_report = {
        'total_records': len(daily_data),
        'columns_checked': ['SRAD', 'TMAX', 'TMIN', 'RAIN'],
        'missing_values': {}, 'has_issues': False, 'quality_score': 100.0
    }
    total_missing = 0
    for col in qa_report['columns_checked']:
        if col in daily_data.columns:
            mask  = daily_data[col] == -99.0
            count = mask.sum()
            if count > 0:
                qa_report['has_issues'] = True
                qa_report['missing_values'][col] = {
                    'count': int(count),
                    'percentage': round((count / len(daily_data)) * 100, 2),
                    'first_5_dates': daily_data[mask]['DATE'].tolist()[:5]
                }
                total_missing += count
    total_possible = len(daily_data) * len(qa_report['columns_checked'])
    if total_possible > 0:
        qa_report['quality_score'] = round(
            ((total_possible - total_missing) / total_possible) * 100, 2)
    return qa_report

def print_qa_report(qa_report: Dict[str, any]) -> None:
    print("\n" + "="*70)
    print("📋 QUALITY ASSURANCE REPORT")
    print("="*70)
    print(f"Total Records : {qa_report['total_records']}")
    print(f"Quality Score : {qa_report['quality_score']}%")
    if qa_report['has_issues']:
        print("\n⚠️  MISSING VALUES (-99):")
        for col, info in qa_report['missing_values'].items():
            print(f"  {col}: {info['count']} ({info['percentage']}%)")
    else:
        print("\n✅ NO MISSING VALUES — All checks passed!")
    print("="*70 + "\n")


# ─────────────────────────────────────────────────────────────
# CRITIC
# ─────────────────────────────────────────────────────────────

class WeatherFileCritic:
    def __init__(self, weather_file):
        self.weather_file = weather_file
        self.issues = []; self.warnings = []

    def read_weather_file(self):
        with open(self.weather_file) as f: lines = f.readlines()
        data_start = next(
            (i+1 for i,l in enumerate(lines) if l.strip().startswith('@  DATE')), None)
        if data_start is None:
            self.issues.append("No data header"); return lines, pd.DataFrame()
        records = []
        for line in lines[data_start:]:
            if line.strip():
                try:
                    records.append({
                        'DATE': int(line[0:7]), 'SRAD': float(line[7:13]),
                        'TMAX': float(line[13:19]), 'TMIN': float(line[19:25]),
                        'RAIN': float(line[25:31])
                    })
                except: self.warnings.append(f"Parse error: {line.strip()}")
        return lines, pd.DataFrame(records)

    def critique(self):
        lines, df = self.read_weather_file()
        if not lines[0].startswith('$WEATHER DATA :'): self.issues.append("Bad header")
        if df.empty: self.issues.append("No records")
        status = "FAILED" if self.issues else "PASSED WITH WARNINGS" if self.warnings else "PASSED"
        return {'status': status, 'issues': self.issues,
                'warnings': self.warnings, 'total_records': len(df)}

    def print_critique(self):
        r = self.critique()
        print("\n" + "="*70 + "\n🔍 CRITIC AGENT REVIEW\n" + "="*70)
        print(f"File: {self.weather_file} | Status: {r['status']} | Records: {r['total_records']}")
        for i in r['issues']:   print(f"  ❌ {i}")
        for w in r['warnings']: print(f"  ⚠️  {w}")
        if not r['issues'] and not r['warnings']: print("  ✅ ALL CHECKS PASSED!")
        print("="*70 + "\n")


# ─────────────────────────────────────────────────────────────
# DSSAT FILE WRITER
# ─────────────────────────────────────────────────────────────

def create_dssat_weather_file(
    df: pd.DataFrame, latitude: float, longitude: float,
    site_name: str, insi: str, output_file: str
) -> None:
    df   = df.copy()
    TAV  = -99.0
    AMP  = -99.0
    elev = get_elevation(latitude, longitude)

    header_lines = [
        f"$WEATHER DATA : {site_name}", "",
        "@ INSI      LAT     LONG  ELEV   TAV   AMP REFHT WNDHT",
        f"  {insi:>4}   {latitude:>6.2f}   {longitude:>6.2f}  "
        f"{elev:>3.0f}.  {TAV:>4.1f}  {AMP:>4.1f}   2.0  10.0",
        "@  DATE  SRAD  TMAX  TMIN  RAIN  DEWP  WIND"
    ]

    df['dssat_date'] = df.index.year * 1000 + df.index.dayofyear
    daily_data = pd.DataFrame({'DATE': df['dssat_date'].astype(int)})
    daily_data['SRAD'] = df['shortwave_radiation_sum'].fillna(-99.0).round(1)
    daily_data['TMAX'] = df['temperature_2m_max'].fillna(-99.0).round(1)
    daily_data['TMIN'] = df['temperature_2m_min'].fillna(-99.0).round(1)
    daily_data['RAIN'] = df['precipitation_sum'].fillna(0.0).round(1)
    daily_data['DEWP'] = df.get('dewpoint_2m_mean',
        pd.Series(index=df.index, dtype=float)).fillna(-99.0).round(1)
    daily_data['WIND'] = df.get('wind_speed_10m_mean',
        pd.Series(index=df.index, dtype=float)).fillna(-99.0).round(1)

    qa_report = quality_assurance_check(daily_data)
    with open(output_file, 'w') as f:
        f.write('\n'.join(header_lines) + '\n')
        for _, row in daily_data.iterrows():
            f.write(
                f"{int(row['DATE']):<7}"
                f"{row['SRAD']:6.1f}{row['TMAX']:6.1f}{row['TMIN']:6.1f}"
                f"{row['RAIN']:6.1f}{row['DEWP']:6.1f}{row['WIND']:6.1f}\n"
            )

    print(f"✅ DSSAT file created: {output_file}")
    print(f"   📍 {site_name}")
    print(f"   📅 {daily_data['DATE'].iloc[0]} → {daily_data['DATE'].iloc[-1]}")
    print(f"   🌧  Total rain: {daily_data['RAIN'].sum():.1f} mm")
    print_qa_report(qa_report)
    WeatherFileCritic(output_file).print_critique()


# ─────────────────────────────────────────────────────────────
# MAIN GENERATOR
# ─────────────────────────────────────────────────────────────

def generate_weather_for_location(
    latitude: float, longitude: float,
    start_date: str = "2024-01-01",
    end_date:   str = "2024-12-31",
) -> str:
    print(f"\n--- WSP2 CHIRPS/CHIRPS-GEFS | ({latitude}, {longitude}) ---")
    loc  = get_location_details(latitude, longitude)
    address      = loc['address']
    country_code = loc['country_code']
    country_name = loc.get('country')
    state_name   = loc.get('state')

    if country_name:
        insi = country_name[:2].upper() + (state_name[:2].upper() if state_name else country_name[:2].upper())
    else:
        insi = "XXXX"

    print(f"Location: {address} | INSI: {insi}")
    output_file = f"WSP2_{country_code}_{latitude}_{longitude}.WTH"

    print("Fetching CHIRPS data...")
    df = fetch_daily_climate(latitude, longitude, start_date, end_date)
    create_dssat_weather_file(df, latitude, longitude,
                               site_name=address, insi=insi, output_file=output_file)
    print(f"--- Complete: {address} ---")
    return output_file


def main():
    generate_weather_for_location(
        latitude=6.84, longitude=-2.19,
        start_date='2025-01-01', end_date='2025-12-31'
    )

if __name__ == "__main__":
    main()