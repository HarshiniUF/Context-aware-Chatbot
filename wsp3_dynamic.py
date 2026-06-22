# -*- coding: utf-8 -*-
"""
=============================================================
DSSAT Weather File Generator — WSP 3: ECMWF Open Data
=============================================================

DATA SOURCE : ECMWF IFS HRES via ecmwf-opendata (free, no account)
PROVIDES    : TMAX, TMIN, SRAD, RAIN, WIND, DEWP — all fields
AUTO-DETECT : Historical dates → Open-Meteo Archive (ERA5-based)
              Future/recent   → ECMWF Open Data (GRIB2 from S3)

NOTE: ECMWF Open Data only has the last ~30 hours of model runs.
For historical date ranges, the code automatically falls back to
Open-Meteo Archive API (ERA5-based) which gives full variable coverage.

SETUP:
  pip install ecmwf-opendata cfgrib xarray eccodes
  pip install openmeteo-requests requests-cache retry-requests
  pip install pandas numpy requests geopy
=============================================================
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import requests
import openmeteo_requests
import requests_cache
from retry_requests import retry
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable


# ─────────────────────────────────────────────────────────────
# GEOCODING
# ─────────────────────────────────────────────────────────────

def get_location_details(latitude: float, longitude: float) -> Dict[str, str]:
    try:
        geolocator = Nominatim(user_agent="dssat_ecmwf_script")
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
# ECMWF / ERA5 FETCHER (auto-detects historical vs forecast)
# ─────────────────────────────────────────────────────────────

def fetch_daily_climate(
    latitude: float, longitude: float,
    start_date: str, end_date: str,
    model: str = "best_match",
    daily_vars: list = None,
    **kwargs
) -> pd.DataFrame:
    """
    Fetches daily climate data for DSSAT.

    AUTO-DETECTS endpoint:
      Historical (before today - 7 days):
        → Open-Meteo Archive API (ERA5-based, all variables available)
        → URL: https://archive-api.open-meteo.com/v1/archive

      Recent / Future (within last 7 days or ahead):
        → Open-Meteo Forecast API (ECMWF IFS model)
        → URL: https://api.open-meteo.com/v1/forecast
        → model: ecmwf_ifs025 (ECMWF's own model)

      Mixed range:
        → Automatically splits, fetches both, concatenates.

    All DSSAT variables: TMAX, TMIN, SRAD, RAIN, DEWP, WIND — all direct.
    No cumulative differencing needed — Open-Meteo returns daily sums directly.
    """
    if daily_vars is None:
        daily_vars = [
            "temperature_2m_max",
            "temperature_2m_min",
            "temperature_2m_mean",
            "dewpoint_2m_max",
            "wind_speed_10m_mean",
            "wind_speed_10m_max",
            "precipitation_sum",
            "shortwave_radiation_sum",
        ]

    cache_session = requests_cache.CachedSession(".ecmwf_dssat_cache", expire_after=3600)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    client        = openmeteo_requests.Client(session=retry_session)

    today    = datetime.utcnow().date()
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d").date()
    cutoff   = today - timedelta(days=7)

    MAX_FORECAST_DAYS = 15
    forecast_cap = today + timedelta(days=MAX_FORECAST_DAYS)
    if end_dt > forecast_cap:
        print(f"  ⚠️  End date {end_date} exceeds max forecast horizon.")
        print(f"  ⚠️  Capping to {forecast_cap} (today + {MAX_FORECAST_DAYS} days).")
        end_dt   = forecast_cap
        end_date = forecast_cap.strftime("%Y-%m-%d")

    # ── CASE 1: Fully historical ────────────────────────────
    if end_dt <= cutoff:
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude"  : latitude,
            "longitude" : longitude,
            "daily"     : daily_vars,
            "start_date": start_date,
            "end_date"  : end_date,
            "timezone"  : "auto",
        }
        print(f"  Historical range → Open-Meteo Archive (ERA5-based) ...")

    # ── CASE 2: Spans historical + forecast ─────────────────
    elif start_dt < cutoff:
        print(f"  Mixed range → splitting into historical + forecast parts ...")
        hist_end    = cutoff.strftime("%Y-%m-%d")
        fcast_start = (cutoff + timedelta(days=1)).strftime("%Y-%m-%d")
        df_hist  = fetch_daily_climate(latitude, longitude, start_date,   hist_end,    model, daily_vars)
        df_fcast = fetch_daily_climate(latitude, longitude, fcast_start,  end_date,    model, daily_vars)
        combined = pd.concat([df_hist, df_fcast])
        print(f"  Combined: {len(combined)} total days.")
        return combined

    # ── CASE 3: Recent / future ──────────────────────────────
    else:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude"  : latitude,
            "longitude" : longitude,
            "daily"     : daily_vars,
            "models"    : "ecmwf_ifs025",   # ECMWF IFS model via Open-Meteo
            "start_date": start_date,
            "end_date"  : end_date,
            "timezone"  : "auto",
        }
        print(f"  Forecast range → Open-Meteo (ECMWF IFS model) ...")

    response = client.weather_api(url, params=params)[0]
    daily    = response.Daily()

    start = pd.Timestamp(daily.Time(), unit="s", tz="UTC")
    end   = pd.Timestamp(daily.TimeEnd(), unit="s", tz="UTC")
    dates = pd.date_range(
        start=start, end=end,
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left"
    )

    data = {"date": dates}
    for i, var in enumerate(daily_vars):
        try:
            data[var] = daily.Variables(i).ValuesAsNumpy()
        except Exception:
            data[var] = np.full(len(dates), np.nan)

    df = pd.DataFrame(data).set_index("date")

    # Rename dewpoint column to match expected name
    if "dewpoint_2m_max" in df.columns:
        df = df.rename(columns={"dewpoint_2m_max": "dewpoint_2m_mean"})

    print(f"  ECMWF (ERA5/IFS): {len(df)} days fetched.")
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
    df = df.copy()

    # TAV and AMP — use actual temperature data if available
    tmax_col = df['temperature_2m_max'].dropna()
    tmin_col = df['temperature_2m_min'].dropna()

    if len(tmax_col) > 0 and len(tmin_col) > 0:
        df['daily_mean'] = (df['temperature_2m_max'] + df['temperature_2m_min']) / 2
        TAV = round(df['daily_mean'].mean(), 1)
        monthly_means = df.groupby(df.index.month)['daily_mean'].mean()
        AMP = round(monthly_means.max() - monthly_means.min(), 1) if len(monthly_means) > 1 else -99.0
    else:
        TAV = -99.0
        AMP = -99.0

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
    daily_data['RAIN'] = df['precipitation_sum'].fillna(-99.0).round(1)
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
    print(f"   TAV: {TAV}°C  AMP: {AMP}°C")
    print_qa_report(qa_report)
    WeatherFileCritic(output_file).print_critique()


# ─────────────────────────────────────────────────────────────
# MAIN GENERATOR
# ─────────────────────────────────────────────────────────────

def generate_weather_for_location(
    latitude: float, longitude: float,
    start_date: str = "2024-01-01",
    end_date:   str = "2024-12-31",
    model: str = "best_match",
) -> str:
    print(f"\n--- WSP3 ECMWF/ERA5 | ({latitude}, {longitude}) ---")
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
    output_file = f"WSP3_{country_code}_{latitude}_{longitude}.WTH"

    print("Fetching ECMWF/ERA5 data...")
    df = fetch_daily_climate(latitude, longitude, start_date, end_date, model=model)
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