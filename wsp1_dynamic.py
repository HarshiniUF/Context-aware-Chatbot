#with quality assurance
#new weather format in dssat
# -*- coding: utf-8 -*-
"""DSSAT Weather Data Fetcher with Quality Assurance
Fetch climate data from Open-Meteo API and convert to DSSAT weather format.
Uses the robust 'geopy' library for reverse geocoding and includes all QA/Critic features.
Final version with all features and corrected header alignment.
INSI code is now dynamically generated from Country and State/Region names.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import requests
import openmeteo_requests
from typing import Dict, List, Tuple
# Import geopy for robust reverse geocoding
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable

def get_location_details(latitude: float, longitude: float) -> Dict[str, str]:
    """
    Performs reverse geocoding to get address details from coordinates using geopy.
    
    Returns a dictionary with address, country name, state/region name, and country code.
    """
    try:
        # Initialize the geolocator with a unique user_agent
        geolocator = Nominatim(user_agent="dssat_weather_script_by_harshini")
        
        # Perform the reverse geocoding lookup
        location = geolocator.reverse((latitude, longitude), exactly_one=True, language='en')
        
        if location and location.address:
            address_details = location.raw.get('address', {})
            city = address_details.get('city', address_details.get('town', address_details.get('village')))
            state = address_details.get('state')
            country = address_details.get('country')
            country_code = address_details.get('country_code', 'XX').upper()
            
            # Construct a clean address string
            parts = [part for part in [city, state, country] if part]
            address = ', '.join(parts)
            
            # Return all necessary components for INSI generation
            return {'address': address, 'country': country, 'state': state, 'country_code': country_code}
            
    except GeocoderUnavailable as e:   
        
        print("\n" + "!"*70)
        print("🛑 CRITICAL WARNING: REVERSE GEOCODING FAILED.")
        print(f"   Could not connect to the geocoding service. Error: {e}")
        print("   This may be due to a network issue or firewall.")
        print("   The script will continue with a generic site name.")
        print("!"*70 + "\n")
    except Exception as e:
        print(f"An unexpected error occurred during geocoding: {e}")
        
    # Fallback dictionary with None for names
    return {'address': f"Site at {latitude:.2f}, {longitude:.2f}", 'country': None, 'state': None, 'country_code': 'NOGEO'}

def fetch_daily_climate(
    latitude: float, longitude: float, start_date: str, end_date: str,
    model: str = "EC_Earth3P_HR", daily_vars = None,
) -> pd.DataFrame:
    """Fetch daily climate data for a given location."""
    if daily_vars is None:
        daily_vars = [
            "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
            "dewpoint_2m_mean", "wind_speed_10m_mean", "wind_speed_10m_max",
            "precipitation_sum", "shortwave_radiation_sum",
        ]
    client = openmeteo_requests.Client()
    url = "https://climate-api.open-meteo.com/v1/climate"
    params = {"latitude": latitude, "longitude": longitude, "start_date": start_date, "end_date": end_date, "models": [model], "daily": daily_vars}
    response = client.weather_api(url, params=params)[0]
    daily = response.Daily()
    index = pd.date_range(start=pd.to_datetime(daily.Time(), unit="s", utc=True), end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True), freq=pd.Timedelta(seconds=daily.Interval()), inclusive="left")
    data = {"date": index}
    for i, var in enumerate(daily_vars):
        if daily.Variables(i):
            data[var] = daily.Variables(i).ValuesAsNumpy()
        else:
            data[var] = np.full(len(index), np.nan)
    return pd.DataFrame(data).set_index("date")

def get_elevation(latitude: float, longitude: float) -> float:
    """Get elevation using Open Elevation API."""
    try:
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={latitude},{longitude}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()['results'][0]['elevation']
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not fetch elevation: {e}. Using default -99.")
        return -99

def quality_assurance_check(daily_data: pd.DataFrame) -> Dict[str, any]:
    """Perform quality assurance checks on the weather data."""
    qa_report = {
        'total_records': len(daily_data), 'columns_checked': ['SRAD', 'TMAX', 'TMIN', 'RAIN'],
        'missing_values': {}, 'has_issues': False, 'quality_score': 100.0
    }
    total_missing = 0
    for col in qa_report['columns_checked']:
        if col in daily_data.columns:
            missing_mask = daily_data[col] == -99.0
            missing_count = missing_mask.sum()
            if missing_count > 0:
                qa_report['has_issues'] = True
                qa_report['missing_values'][col] = {
                    'count': int(missing_count),
                    'percentage': round((missing_count / len(daily_data)) * 100, 2),
                    'first_5_dates': daily_data[missing_mask]['DATE'].tolist()[:5]
                }
                total_missing += missing_count
    total_possible = len(daily_data) * len(qa_report['columns_checked'])
    if total_possible > 0:
        qa_report['quality_score'] = round(((total_possible - total_missing) / total_possible) * 100, 2)
    return qa_report

def print_qa_report(qa_report: Dict[str, any]) -> None:
    """Print a formatted quality assurance report."""
    print("\n" + "="*70); print("📋 QUALITY ASSURANCE REPORT"); print("="*70)
    print(f"Total Records: {qa_report['total_records']}")
    print(f"Columns Checked: {', '.join(qa_report['columns_checked'])}")
    print(f"Overall Quality Score: {qa_report['quality_score']}%")
    if qa_report['has_issues']:
        print("\n⚠️  MISSING VALUES DETECTED (-99):")
        for col, info in qa_report['missing_values'].items():
            print(f"\n  {col}:")
            print(f"    - Missing Count: {info['count']} ({info['percentage']}%)")
            print(f"    - First affected dates: {info['first_5_dates']}")
    else:
        print("\n✅ NO MISSING VALUES DETECTED - All checks passed!")
    print("="*70 + "\n")

class WeatherFileCritic:
    """Critic agent to review and validate generated DSSAT weather files."""
    def __init__(self, weather_file: str):
        self.weather_file = weather_file; self.issues = []; self.warnings = []; self.info = []
    def read_weather_file(self) -> Tuple[List[str], pd.DataFrame]:
        with open(self.weather_file, 'r') as f: lines = f.readlines()
        data_start = next((i + 1 for i, l in enumerate(lines) if l.strip().startswith('@  DATE')), None)
        if data_start is None: self.issues.append("Could not find data section header"); return lines, pd.DataFrame()
        data_records = []
        for line in lines[data_start:]:
            if line.strip():
                try:
                    data_records.append({
                        'DATE': int(line[0:7].strip()), 'SRAD': float(line[7:13].strip()),
                        'TMAX': float(line[13:19].strip()), 'TMIN': float(line[19:25].strip()),
                        'RAIN': float(line[25:31].strip())
                    })
                except (ValueError, IndexError): self.warnings.append(f"Could not parse line: {line.strip()}")
        return lines, pd.DataFrame(data_records)
    def critique(self) -> Dict[str, any]:
        lines, df = self.read_weather_file()
        if not lines[0].startswith('$WEATHER DATA :'): self.issues.append("Header format incorrect (expected '$WEATHER DATA : ...')")
        if df.empty: self.issues.append("No data records found")
        status = "FAILED" if self.issues else "PASSED WITH WARNINGS" if self.warnings else "PASSED"
        return {'status': status, 'issues': self.issues, 'warnings': self.warnings, 'total_records': len(df)}
    def print_critique(self):
        report = self.critique()
        print("\n" + "="*70); print("🔍 CRITIC AGENT REVIEW"); print("="*70)
        print(f"File: {self.weather_file}\nStatus: {report['status']}\nTotal Records: {report['total_records']}")
        if report['issues']: print(f"\n❌ CRITICAL ISSUES:"); [print(f"  - {i}") for i in report['issues']]
        if report['warnings']: print(f"\n⚠️  WARNINGS:"); [print(f"  - {w}") for w in report['warnings']]
        if not report['issues'] and not report['warnings']: print("\n✅ ALL CHECKS PASSED!")
        print("="*70 + "\n")

def create_dssat_weather_file(df: pd.DataFrame, latitude: float, longitude: float, 
                             site_name: str, insi: str, output_file: str) -> None:
    """Creates a DSSAT weather file from climate DataFrame."""
    df = df.copy()
    df['daily_mean'] = (df['temperature_2m_max'] + df['temperature_2m_min']) / 2
    TAV = df['daily_mean'].mean()
    df['month'] = df.index.month
    monthly_means = df.groupby('month')['daily_mean'].mean()
    AMP = monthly_means.max() - monthly_means.min()
    elev = get_elevation(latitude, longitude)
    
    # header_title = "@ INSI      LAT     LONG  ELEV   TAV   AMP REFHT WNDHT"
    # header_data_line = (
    #     f"  {insi:>4}   "
    #     f"{latitude:>6.2f}   "
    #     f"{longitude:>6.2f}  "
    #     f"{elev:>3.0f}.  "
    #     f"{TAV:>2.1f}   "
    #     f"{AMP:>2.1f}   "
    #     f"{2.0:>2.1f}  "
    #     f"{10.0:>2.1f}"
    # )

    header_title = "@ INSI      LAT     LONG  ELEV   TAV   AMP REFHT WNDHT"
    header_data_line = (
        f"  {insi:>4}   "
        f"{latitude:>6.2f}   "
        f"{longitude:>6.2f}  "
        f"{elev:>3.0f}.  "
        f"{TAV:>2.1f}   "
        f"{AMP:>2.1f}   "
        f"{2.0:>1.1f}  "
        f"{10.0:>2.1f}"
    )
    

    header_lines = [
        f"$WEATHER DATA : {site_name}", "",
        header_title,
        header_data_line,
        "@  DATE  SRAD  TMAX  TMIN  RAIN  DEWP  WIND"
    ]
    
    df['dssat_date'] = df.index.year * 1000 + df.index.dayofyear
    daily_data = pd.DataFrame({'DATE': df['dssat_date'].astype(int)})
    daily_data['SRAD'] = df['shortwave_radiation_sum'].fillna(-99.0).round(1)
    daily_data['TMAX'] = df['temperature_2m_max'].fillna(-99.0).round(1)
    daily_data['TMIN'] = df['temperature_2m_min'].fillna(-99.0).round(1)
    daily_data['RAIN'] = df['precipitation_sum'].fillna(-99.0).round(1)
    daily_data['DEWP'] = df.get('dewpoint_2m_mean', pd.Series(index=df.index, dtype=float)).fillna(-99.0).round(1)
    daily_data['WIND'] = df.get('wind_speed_10m_mean', pd.Series(index=df.index, dtype=float)).fillna(-99.0).round(1)
    
    qa_report = quality_assurance_check(daily_data)
    
    with open(output_file, 'w') as f:
        f.write('\n'.join(header_lines) + '\n')
        for _, row in daily_data.iterrows():
            f.write(f"{int(row['DATE']):<7}{row['SRAD']:6.1f}{row['TMAX']:6.1f}{row['TMIN']:6.1f}{row['RAIN']:6.1f}{row['DEWP']:6.1f}{row['WIND']:6.1f}\n")
            
    print(f"✅ DSSAT weather file created: {output_file}")
    print(f"   📍 Location: {site_name}")
    print(f"   📅 Period: {daily_data['DATE'].iloc[0]} to {daily_data['DATE'].iloc[-1]}")
    
    print_qa_report(qa_report)
    WeatherFileCritic(output_file).print_critique()

def generate_weather_for_location(latitude: float, longitude: float,
                                start_date: str = "2024-01-01", end_date: str = "2025-12-31",
                                model: str = "EC_Earth3P_HR") -> str:
    """Fully automated function to generate a weather file for a specific location."""
    print(f"\n--- Starting process for coordinates: ({latitude}, {longitude}) ---")
    location_info = get_location_details(latitude, longitude)
    
    address = location_info['address']
    country_code = location_info['country_code']
    country_name = location_info.get('country')
    state_name = location_info.get('state')

    # --- NEW LOGIC FOR DYNAMIC INSI CODE ---
    if country_name:
        country_part = country_name[:2].upper()
        # If a state/region exists, use its first two letters. Otherwise, reuse the country part.
        state_part = state_name[:2].upper() if state_name else country_part
        insi = country_part + state_part
    else:
        # Fallback if geocoding completely fails
        insi = "XXXX"

    print(f"Found location: {address} (Country Code: {country_code})")
    print(f"Generated INSI code: {insi}") # For user confirmation
    
    output_file = f"{country_code}_{latitude}_{longitude}.WTH"
    
    print("Fetching climate data...")
    df = fetch_daily_climate(latitude, longitude, start_date, end_date, model)
    
    # Pass the new 'insi' code to the writer function
    create_dssat_weather_file(df, latitude, longitude, site_name=address, insi=insi, output_file=output_file)
    
    print(f"--- Process complete for {address} ---")
    return output_file

def main():
    """Main function to demonstrate usage."""
    # Example 1: Kitale, Kenya to test KETR logic
    generate_weather_for_location(
        latitude=1.016, 
        longitude=35.000, # Approx. Kitale in Trans-Nzoia
        start_date='2024-01-01', 
        end_date='2024-12-31'
    )
    
    # Example 2: Adama, Oromia, Ethiopia
    generate_weather_for_location(
        latitude=8.54, 
        longitude=39.27,
        start_date="2024-01-01", 
        end_date="2024-12-31"
    )

if __name__ == "__main__":
    main()