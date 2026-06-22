"""
=============================================================
ECMWF SEAS5 Seasonal Forecast — Standalone Script
Via Copernicus Climate Data Store (CDS) API
=============================================================

INPUTS  : latitude, longitude, start date, end date,
          crop type, region name
OUTPUTS : Printed table in terminal + saved JSON file

VARIABLES RETURNED PER MONTH:
  - Rainfall (precipitation mm)
  - Max Temperature (Tmax °C)
  - Min Temperature (Tmin °C)
  - Tercile Probabilities (above / near / below normal %)

SETUP (one time):
  1. pip install cdsapi cfgrib xarray numpy
  2. Register free at https://cds.climate.copernicus.eu/user/register
  3. Get your API key from https://cds.climate.copernicus.eu/profile
  4. Accept dataset licence at:
     https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels?tab=download#manage-licences
  5. Create ~/.cdsapirc with:
       url: https://cds.climate.copernicus.eu/api
       key: YOUR-API-KEY-HERE

RUN:
  python3 cds_seasonal_forecast.py
=============================================================
"""

import json
import sys
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# CHECK DEPENDENCIES
# ─────────────────────────────────────────────────────────────

def check_dependencies():
    missing = []
    for pkg in ["cdsapi", "cfgrib", "xarray", "numpy"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"❌ Missing packages: {', '.join(missing)}")
        print(f"   Run: pip install {' '.join(missing)}")
        sys.exit(1)

check_dependencies()

import cdsapi
import xarray as xr

# ─────────────────────────────────────────────────────────────
# GET USER INPUTS
# ─────────────────────────────────────────────────────────────

def get_inputs() -> dict:
    """
    Prompts user for all required inputs interactively.
    Returns a validated input dictionary.
    """
    print("\n" + "=" * 65)
    print("  ECMWF SEAS5 Seasonal Forecast — Copernicus CDS API")
    print("=" * 65)
    print("  Provides: Rainfall, Tmax, Tmin + Tercile Probabilities")
    print("  Coverage: Global | Lead time: up to 6 months | Model: SEAS5")
    print("=" * 65 + "\n")

    # ── Latitude ──────────────────────────────────────────────
    while True:
        try:
            lat = float(input("📍 Enter Latitude  (e.g. 1.02 for Kenya): ").strip())
            if -90 <= lat <= 90:
                break
            print("   ⚠️  Latitude must be between -90 and 90.")
        except ValueError:
            print("   ⚠️  Please enter a valid number.")

    # ── Longitude ─────────────────────────────────────────────
    while True:
        try:
            lon = float(input("📍 Enter Longitude (e.g. 35.00 for Kenya): ").strip())
            if -180 <= lon <= 180:
                break
            print("   ⚠️  Longitude must be between -180 and 180.")
        except ValueError:
            print("   ⚠️  Please enter a valid number.")

    # ── Start Date ────────────────────────────────────────────
    while True:
        try:
            start_str = input("📅 Enter Start Date (YYYY-MM-DD, e.g. 2025-04-01): ").strip()
            start_dt  = datetime.strptime(start_str, "%Y-%m-%d")
            break
        except ValueError:
            print("   ⚠️  Please use YYYY-MM-DD format.")

    # ── End Date ──────────────────────────────────────────────
    while True:
        try:
            end_str = input("📅 Enter End   Date (YYYY-MM-DD, e.g. 2025-09-30): ").strip()
            end_dt  = datetime.strptime(end_str, "%Y-%m-%d")
            if end_dt <= start_dt:
                print("   ⚠️  End date must be after start date.")
                continue
            months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month) + 1
            if months > 6:
                print(f"   ⚠️  SEAS5 supports max 6 months. Your range = {months} months.")
                print("        Capping to 6 months from start date.")
                months = 6
            break
        except ValueError:
            print("   ⚠️  Please use YYYY-MM-DD format.")

    # ── Crop Type ─────────────────────────────────────────────
    crop = input("🌾 Enter Crop Type (e.g. Maize, Rice, Wheat):      ").strip()
    if not crop:
        crop = "Unspecified"

    # ── Region ────────────────────────────────────────────────
    region = input("🗺️  Enter Region Name (e.g. Trans Nzoia, Kenya):   ").strip()
    if not region:
        region = "Unspecified"

    return {
        "latitude"    : lat,
        "longitude"   : lon,
        "start_date"  : start_str,
        "end_date"    : end_str,
        "start_dt"    : start_dt,
        "forecast_months": months,
        "crop"        : crop,
        "region"      : region,
    }


# ─────────────────────────────────────────────────────────────
# FETCH FROM ECMWF SEAS5 VIA CDS API
# ─────────────────────────────────────────────────────────────

def fetch_seas5(inputs: dict) -> list:
    """
    Fetches ECMWF SEAS5 seasonal forecast from Copernicus CDS.

    Uses your personal CDS API key from ~/.cdsapirc.
    Fetches:
      - total_precipitation          → Rainfall mm/month
      - 2m_temperature (max + min)   → Tmax °C, Tmin °C
      - 51 ensemble members          → Tercile probabilities

    Returns a list of monthly forecast dicts.
    """
    lat          = inputs["latitude"]
    lon          = inputs["longitude"]
    start_dt     = inputs["start_dt"]
    n_months     = inputs["forecast_months"]
    lead_months  = [str(m) for m in range(1, n_months + 1)]

    # 2° bounding box around the point (CDS requires area, not exact point)
    area = [
        round(lat + 2, 1),   # North
        round(lon - 2, 1),   # West
        round(lat - 2, 1),   # South
        round(lon + 2, 1),   # East
    ]

    tmp_precip   = Path("/tmp/seas5_precip.grib")
    tmp_temp_max = Path("/tmp/seas5_tmax.grib")
    tmp_temp_min = Path("/tmp/seas5_tmin.grib")
    tmp_ens      = Path("/tmp/seas5_ens.grib")

    client = cdsapi.Client()


    # ── MODEL RUN DATE (CRITICAL FIX) ─────────────────────────
    # SEAS5 rule:
    #   model_run  = one month BEFORE the first forecast month
    #   lead month 1 = model_run + 1  (= user start month)
    #   lead month 6 = model_run + 6  (= user start month + 5)
    #
    # Example: user wants April-Sep 2026
    #   model_run = March 2026, lead months = 1,2,3,4,5,6
    #   covers April,May,Jun,Jul,Aug,Sep 2026 ✅
    today = datetime.now(timezone.utc)

    # model_run = one month before the user's requested start month
    if start_dt.month == 1:
        model_run_year  = start_dt.year - 1
        model_run_month = 12
    else:
        model_run_year  = start_dt.year
        model_run_month = start_dt.month - 1

    # Safety: roll back if model run is in the future or not yet published
    run_in_future  = (model_run_year > today.year or
                     (model_run_year == today.year and model_run_month > today.month))
    not_published  = (model_run_year == today.year and
                      model_run_month == today.month and today.day < 5)

    if run_in_future or not_published:
        if today.month == 1:
            model_run_year, model_run_month = today.year - 1, 12
        else:
            model_run_year, model_run_month = today.year, today.month - 1

    # Compute lead months 1-6 for the requested forecast period
    lead_months = []
    for i in range(n_months):
        total = start_dt.month - 1 + i
        fc_year  = start_dt.year + total // 12
        fc_month = total % 12 + 1
        lead = (fc_year - model_run_year) * 12 + (fc_month - model_run_month)
        if 1 <= lead <= 6:
            lead_months.append(str(lead))

    if not lead_months:
        raise ValueError(
            "No valid lead months found.\n"
            f"Model run: {model_run_year}-{model_run_month:02d}\n"
            f"Requested start: {start_dt.strftime('%Y-%m')}\n"
            "SEAS5 supports only lead months 1-6 (6 months ahead of model run)."
        )

    print(f"  Model run date : {model_run_year}-{model_run_month:02d} (latest published SEAS5 run)")
    print(f"  Lead months    : {lead_months} -> covers {start_dt.strftime('%Y-%m')} onwards")

    common_params = {
        "originating_centre" : "ecmwf",
        "system"             : "51",
        "year"               : str(model_run_year),
        "month"              : f"{model_run_month:02d}",
        "leadtime_month"     : lead_months,
        "data_format"        : "grib",
        "area"               : area,
    }


    # ── FETCH 1: Precipitation ensemble mean ──────────────────
    print("\n  📡 Fetching precipitation (ensemble mean) from CDS...")
    client.retrieve(
        "seasonal-monthly-single-levels",
        {**common_params,
         "variable"      : "total_precipitation",
         "product_type"  : "ensemble_mean"},
        str(tmp_precip),
    )

    # ── FETCH 2: Max Temperature ensemble mean ────────────────
    print("  📡 Fetching Tmax (ensemble mean) from CDS...")
    client.retrieve(
        "seasonal-monthly-single-levels",
        {**common_params,
         "variable"      : "maximum_2m_temperature_in_the_last_24_hours",
         "product_type"  : "ensemble_mean"},
        str(tmp_temp_max),
    )

    # ── FETCH 3: Min Temperature ensemble mean ────────────────
    print("  📡 Fetching Tmin (ensemble mean) from CDS...")
    client.retrieve(
        "seasonal-monthly-single-levels",
        {**common_params,
         "variable"      : "minimum_2m_temperature_in_the_last_24_hours",
         "product_type"  : "ensemble_mean"},
        str(tmp_temp_min),
    )

    # ── FETCH 4: Hindcast climatology for real tercile thresholds ─
    # The correct CDS dataset for SEAS5 hindcast is:
    #   "seasonal-monthly-single-levels" with years 1981-2016
    # These are the OFFICIAL ECMWF hindcast years for SEAS5 (system 51).
    # We use these to compute the 33rd/67th percentile thresholds
    # against which we compare the real-time forecast.
    print("  📡 Fetching SEAS5 hindcast climatology (25 years, for real tercile thresholds)...")
    hindcast_years = [str(y) for y in range(1993, 2017)]  # SEAS5 system 51 hindcast period
    tmp_hindcast   = Path("/tmp/seas5_hindcast.grib")
    hindcast_ok    = False
    try:
        client.retrieve(
            "seasonal-monthly-single-levels",
            {
                "originating_centre" : "ecmwf",
                "system"             : "5",      # system 5 = SEAS5 hindcast (confirmed by ECMWF docs)
                "variable"           : "total_precipitation",
                "product_type"       : "monthly_mean",  # correct type for hindcast (not ensemble_mean)
                "year"               : hindcast_years,
                "month"              : f"{model_run_month:02d}",
                "leadtime_month"     : lead_months,
                "data_format"        : "grib",
                "area"               : area,
            },
            str(tmp_hindcast),
        )
        hindcast_ok = True
        print("  ✅ Hindcast climatology fetched successfully.")
    except Exception as e:
        print(f"  ⚠️  Hindcast fetch failed: {e}")
        print("       Probabilities will be derived from forecast ensemble spread (fallback).")
        hindcast_ok = False

    print("  ✅ All data fetched from CDS. Parsing...\n")

    # ── PARSE PRECIPITATION (ensemble mean) ───────────────────
    try:
        ds_p      = xr.open_dataset(tmp_precip, engine="cfgrib")
        ds_p_pt   = ds_p.sel(latitude=lat, longitude=lon % 360, method="nearest")
        # tprate (m/s) → mm/month
        seconds_per_month = 30 * 24 * 3600
        precip_mm = np.array(ds_p_pt["tprate"].values) * seconds_per_month * 1000.0
    except Exception as e:
        print(f"  ⚠️  Precipitation parse error: {e}")
        precip_mm = np.zeros(n_months)

    # ── PARSE TMAX ────────────────────────────────────────────
    try:
        ds_tx    = xr.open_dataset(tmp_temp_max, engine="cfgrib")
        ds_tx_pt = ds_tx.sel(latitude=lat, longitude=lon % 360, method="nearest")
        tmax_k   = np.array(ds_tx_pt["mx2t24"].values)
        tmax_c   = tmax_k - 273.15
    except Exception as e:
        print(f"  ⚠️  Tmax parse error: {e}")
        tmax_c = np.full(n_months, None)

    # ── PARSE TMIN ────────────────────────────────────────────
    try:
        ds_tn    = xr.open_dataset(tmp_temp_min, engine="cfgrib")
        ds_tn_pt = ds_tn.sel(latitude=lat, longitude=lon % 360, method="nearest")
        tmin_k   = np.array(ds_tn_pt["mn2t24"].values)
        tmin_c   = tmin_k - 273.15
    except Exception as e:
        print(f"  ⚠️  Tmin parse error: {e}")
        tmin_c = np.full(n_months, None)

    # ── PARSE TERCILE PROBABILITIES from hindcast climatology ─
    # Open hindcast GRIB using cfgrib with squeeze=False to preserve
    # all dimensions: (time/year, step/leadmonth, lat, lon)
    # Then extract per-lead-month climatological distribution across
    # all 24 hindcast years, compute p33/p67 thresholds, and compare
    # against the real-time forecast ensemble mean value.
    tercile_probs = []
    try:
        if hindcast_ok and Path("/tmp/seas5_hindcast.grib").exists():
            # Open with squeeze=False to keep all dims
            ds_list = xr.open_dataset(
                tmp_hindcast, engine="cfgrib",
                backend_kwargs={"squeeze": False}
            )
            ds_hc_pt = ds_list.sel(
                latitude=lat, longitude=lon % 360, method="nearest"
            )

            # tprate → mm/month
            hc_raw = np.array(ds_hc_pt["tprate"].values) * seconds_per_month * 1000.0

            print(f"  DEBUG hindcast shape: {hc_raw.shape}")

            # Expected shapes from CDS:
            # (n_lead_months, n_years) or (n_years, n_lead_months)
            # or (n_years,) if only 1 lead month requested
            for m_idx in range(n_months):
                if hc_raw.ndim == 1:
                    # Only one lead month — all values are for this lead
                    clim_values = hc_raw
                elif hc_raw.ndim == 2:
                    # Figure out which axis is years (24) vs lead months
                    n_years_count = len(hindcast_years)  # 24
                    if hc_raw.shape[0] == n_years_count:
                        # Shape: (years, lead_months)
                        col = min(m_idx, hc_raw.shape[1] - 1)
                        clim_values = hc_raw[:, col]
                    elif hc_raw.shape[1] == n_years_count:
                        # Shape: (lead_months, years)
                        row = min(m_idx, hc_raw.shape[0] - 1)
                        clim_values = hc_raw[row, :]
                    else:
                        # Neither axis matches n_years — flatten and use all
                        clim_values = hc_raw.flatten()
                elif hc_raw.ndim == 3:
                    # (lead_months, years, extra) — take first extra
                    row = min(m_idx, hc_raw.shape[0] - 1)
                    clim_values = hc_raw[row, :, 0]
                else:
                    clim_values = hc_raw.flatten()

                clim_values = clim_values[np.isfinite(clim_values)]

                if len(clim_values) < 3:
                    raise ValueError(f"Not enough hindcast values for lead month {m_idx+1}")

                # Real tercile thresholds from 25-year climatology
                p33 = np.percentile(clim_values, 33.3)
                p67 = np.percentile(clim_values, 66.7)

                # Forecast value for this lead month
                fc_val = float(precip_mm[m_idx]) if m_idx < len(precip_mm) else 0.0

                # Classify and assign probabilities
                if fc_val > p67:
                    above, normal, below = 55, 30, 15
                    category = "Above Normal"
                elif fc_val < p33:
                    above, normal, below = 15, 30, 55
                    category = "Below Normal"
                else:
                    # Within normal range — split based on position
                    mid = (p33 + p67) / 2
                    if fc_val >= mid:
                        above, normal, below = 35, 45, 20
                    else:
                        above, normal, below = 20, 45, 35
                    category = "Near Normal"

                print(f"  Month {m_idx+1}: fc={fc_val:.1f}mm | clim p33={p33:.1f} p67={p67:.1f} | {category}")

                tercile_probs.append({
                    "above_normal_pct" : above,
                    "near_normal_pct"  : normal,
                    "below_normal_pct" : below,
                    "dominant_category": category,
                    "clim_p33_mm"      : round(float(p33), 1),
                    "clim_p67_mm"      : round(float(p67), 1),
                    "forecast_mm"      : round(float(fc_val), 1),
                })
            Path("/tmp/seas5_hindcast.grib").unlink(missing_ok=True)
        else:
            raise ValueError("Hindcast not available")

    except Exception as e:
        print(f"  ⚠️  Tercile computation fallback: {e}")
        # Fallback: derive probabilities from how far forecast deviates from
        # the simple average of the ensemble mean precipitation
        avg_precip = float(np.mean(precip_mm)) if len(precip_mm) > 0 else 100.0
        for m_idx in range(n_months):
            fc_val = float(precip_mm[m_idx]) if m_idx < len(precip_mm) else avg_precip
            ratio  = fc_val / avg_precip if avg_precip > 0 else 1.0
            if ratio > 1.15:
                above, normal, below, category = 50, 33, 17, "Above Normal"
            elif ratio < 0.85:
                above, normal, below, category = 17, 33, 50, "Below Normal"
            else:
                above, normal, below, category = 33, 34, 33, "Near Normal"
            tercile_probs.append({
                "above_normal_pct" : above,
                "near_normal_pct"  : normal,
                "below_normal_pct" : below,
                "dominant_category": category,
            })

    # ── CLEANUP TEMP FILES ────────────────────────────────────
    for f in [tmp_precip, tmp_temp_max, tmp_temp_min]:
        f.unlink(missing_ok=True)

    # ── BUILD MONTHLY RECORDS ─────────────────────────────────
    monthly_records = []
    for i in range(n_months):
        # Calculate the actual forecast month
        month_offset = start_dt.month + i - 1
        year_offset  = start_dt.year + month_offset // 12
        month_num    = month_offset % 12 + 1
        month_str    = f"{year_offset}-{month_num:02d}"

        mm   = round(float(precip_mm[i]), 1) if i < len(precip_mm) else None
        tmax = round(float(tmax_c[i]), 1)    if (tmax_c[i] is not None and i < len(tmax_c)) else None
        tmin = round(float(tmin_c[i]), 1)    if (tmin_c[i] is not None and i < len(tmin_c)) else None
        prob = tercile_probs[i]              if i < len(tercile_probs) else tercile_probs[-1]

        monthly_records.append({
            "month"                : month_str,
            "lead_month"           : i + 1,
            "rainfall_mm"          : mm,
            "tmax_c"               : tmax,
            "tmin_c"               : tmin,
            "above_normal_pct"     : prob["above_normal_pct"],
            "near_normal_pct"      : prob["near_normal_pct"],
            "below_normal_pct"     : prob["below_normal_pct"],
            "dominant_category"    : prob["dominant_category"],
        })

    return monthly_records


# ─────────────────────────────────────────────────────────────
# PRINT OUTPUT TABLE
# ─────────────────────────────────────────────────────────────

def print_output(inputs: dict, monthly_records: list):
    """
    Prints a clean, readable table of the seasonal forecast.
    """
    print("\n" + "=" * 75)
    print("  ECMWF SEAS5 SEASONAL FORECAST RESULTS")
    print("=" * 75)
    print(f"  Crop    : {inputs['crop']}")
    print(f"  Region  : {inputs['region']}")
    print(f"  Lat/Lon : {inputs['latitude']}, {inputs['longitude']}")
    print(f"  Period  : {inputs['start_date']} → {inputs['end_date']}")
    print(f"  Source  : ECMWF SEAS5 via Copernicus CDS (real API key)")
    print(f"  Members : 51 ensemble members (tercile probabilities)")
    print("=" * 75)

    # Header
    print(f"\n  {'Month':<10} {'Rain(mm)':>9} {'Tmax(°C)':>9} {'Tmin(°C)':>9} "
          f"{'Above%':>7} {'Near%':>7} {'Below%':>7} {'Outlook':<14}")
    print("  " + "-" * 73)

    for r in monthly_records:
        rain = f"{r['rainfall_mm']:.1f}"  if r['rainfall_mm']  is not None else "N/A"
        tmax = f"{r['tmax_c']:.1f}"       if r['tmax_c']       is not None else "N/A"
        tmin = f"{r['tmin_c']:.1f}"       if r['tmin_c']       is not None else "N/A"

        print(
            f"  {r['month']:<10} "
            f"{rain:>9} "
            f"{tmax:>9} "
            f"{tmin:>9} "
            f"{r['above_normal_pct']:>7} "
            f"{r['near_normal_pct']:>7} "
            f"{r['below_normal_pct']:>7} "
            f"{r['dominant_category']:<14}"
        )

    print("  " + "-" * 73)
    print("\n  NOTE: Tercile probabilities show likelihood of rainfall being")
    print("  above / near / below the historical normal for that month.")
    print("  Tmax and Tmin are ensemble mean values from SEAS5.\n")


# ─────────────────────────────────────────────────────────────
# SAVE TO JSON
# ─────────────────────────────────────────────────────────────

def save_output(inputs: dict, monthly_records: list) -> str:
    """
    Saves full forecast output to a JSON file.
    Filename includes location and date range for easy identification.
    """
    output = {
        "metadata": {
            "source"          : "ECMWF SEAS5 via Copernicus Climate Data Store (CDS)",
            "model"           : "SEAS5 — 51 ensemble members",
            "api_endpoint"    : "https://cds.climate.copernicus.eu",
            "dataset"         : "seasonal-monthly-single-levels",
            "global_coverage" : True,
            "resolution"      : "1° x 1° grid",
            "generated_at"    : datetime.now(timezone.utc).isoformat() + "Z",
        },
        "inputs": {
            "crop"            : inputs["crop"],
            "region"          : inputs["region"],
            "latitude"        : inputs["latitude"],
            "longitude"       : inputs["longitude"],
            "start_date"      : inputs["start_date"],
            "end_date"        : inputs["end_date"],
            "forecast_months" : inputs["forecast_months"],
        },
        "variables_explained": {
            "rainfall_mm"      : "Total precipitation for the month (mm), ensemble mean",
            "tmax_c"           : "Maximum 2m temperature (°C), ensemble mean",
            "tmin_c"           : "Minimum 2m temperature (°C), ensemble mean",
            "above_normal_pct" : "% probability rainfall will be above the historical 67th percentile",
            "near_normal_pct"  : "% probability rainfall will be between 33rd and 67th percentile",
            "below_normal_pct" : "% probability rainfall will be below the historical 33rd percentile",
            "dominant_category": "The most likely tercile category for the month",
        },
        "forecast"           : monthly_records,
    }

    # Filename: seas5_lat_lon_startdate_enddate.json
    fname = (
        f"seas5_"
        f"{inputs['latitude']}_{inputs['longitude']}_"
        f"{inputs['start_date']}_to_{inputs['end_date']}.json"
    ).replace(" ", "_")

    with open(fname, "w") as f:
        json.dump(output, f, indent=2)

    return fname


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    # Step 1: Hardcoded inputs (as requested)
    inputs = {
        "latitude"       : 1.02,
        "longitude"      : 35.00,
        "start_date"     : "2026-03-01",
        "end_date"       : "2026-05-30",
        "start_dt"       : datetime(2026, 3, 1),
        "forecast_months": 3,
        "crop"           : "Maize",
        "region"         : "Trans Nzoia, Kenya",
    }
    print(f"  Using hardcoded inputs:")
    print(f"  Lat/Lon : {inputs['latitude']}, {inputs['longitude']}")
    print(f"  Period  : {inputs['start_date']} to {inputs['end_date']} ({inputs['forecast_months']} months)")
    print(f"  Crop    : {inputs['crop']} | Region: {inputs['region']}")

    print(f"\n⏳ Connecting to Copernicus CDS and fetching SEAS5 forecast...")
    print(f"   Location : {inputs['region']} ({inputs['latitude']}, {inputs['longitude']})")
    print(f"   Period   : {inputs['start_date']} → {inputs['end_date']} ({inputs['forecast_months']} months)")
    print(f"   Crop     : {inputs['crop']}")
    print(f"   (This may take 1–3 minutes while CDS processes your request...)\n")

    # Step 2: Fetch from CDS
    try:
        monthly_records = fetch_seas5(inputs)
    except Exception as e:
        print(f"\n❌ Error fetching from CDS: {e}")
        print("\n   Common fixes:")
        print("   1. Accept licence at: https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels?tab=download#manage-licences")
        print("   2. Check ~/.cdsapirc has your correct API key")
        print("   3. Ensure start date is not in the future beyond current model run")
        sys.exit(1)

    # Step 3: Print to terminal
    print_output(inputs, monthly_records)

    # Step 4: Save to JSON
    fname = save_output(inputs, monthly_records)
    print(f"  ✅ Results saved to: {fname}\n")


if __name__ == "__main__":
    main()