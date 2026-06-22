"""
=============================================================
iSDAsoil Integration Module — Soil Property Data
Via iSDA Africa REST API
=============================================================

INPUTS  : latitude, longitude, username, password
OUTPUTS : Soil chemical properties, soil physical properties,
          soil nutrient data in JSON format

AVAILABLE SOIL PROPERTIES:
  - Carbon, Organic (0-20cm, 20-50cm, 50-100cm)
  - Nitrogen, Total (0-20cm, 20-50cm, 50-100cm)
  - pH (0-20cm, 20-50cm)
  - Cation Exchange Capacity (0-20cm, 20-50cm)
  - Bulk Density (0-20cm, 20-50cm, 50-100cm)
  - Clay, Silt, Sand percentages (0-20cm, 20-50cm)
  - And 20+ more soil properties at different depths

SETUP (one time):
  1. Register at: https://isda-africa.com/api/registration
  2. Create username and password
  3. Add to .env file:
       ISDASOIL_USERNAME=your_username
       ISDASOIL_PASSWORD=your_password

RUN EXAMPLE:
  from wsp_soil_isda import get_soil_data, format_soil_output
  soil_data = get_soil_data(latitude=1.02, longitude=35.24)
  print(format_soil_output(soil_data))
=============================================================
"""

import os
import json
import sys
import requests
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# ISDA SOIL API CONFIGURATION
# ─────────────────────────────────────────────────────────────

ISDA_API_BASE = "https://api.isda-africa.com"
ISDA_LOGIN_ENDPOINT = f"{ISDA_API_BASE}/login"
ISDA_SOILPROPERTY_ENDPOINT = f"{ISDA_API_BASE}/isdasoil/v2/soilproperty"
ISDA_LAYERS_ENDPOINT = f"{ISDA_API_BASE}/isdasoil/v2/layers"

# Token cache to avoid repeated login calls within 55 minutes
_TOKEN_CACHE = {
    "token": None,
    "expires_at": None,
}

# ─────────────────────────────────────────────────────────────
# SOIL PROPERTY DEFINITIONS & METADATA
# ─────────────────────────────────────────────────────────────

SOIL_PROPERTIES_DICT = {
    # CHEMICAL PROPERTIES
    "carbon_organic": {
        "name": "Carbon, Organic",
        "unit": "%",
        "depths": ["0-20", "20-50", "50-100"],
        "category": "chemical",
        "importance": "high",
        "description": "Percentage of organic carbon in soil. Indicates soil health, fertility, carbon sequestration potential, and microbial activity.",
        "recommendation_factors": [
            "Crop nutritional supply (N, P, K availability)",
            "Soil water retention capacity",
            "Soil structure and stability",
            "Microbial activity for disease suppression"
        ]
    },
    "nitrogen_total": {
        "name": "Nitrogen, Total",
        "unit": "g/kg or mg/kg",
        "depths": ["0-20", "20-50", "50-100"],
        "category": "nutrient",
        "importance": "high",
        "description": "Total nitrogen content in soil. Essential nutrient for crop growth, determines fertilizer needs.",
        "recommendation_factors": [
            "Fertilizer requirement estimation",
            "Nitrogen topdressing timing and rate",
            "Crop growth potential",
            "Yield prediction"
        ]
    },
    "ph": {
        "name": "Soil pH",
        "unit": "pH units",
        "depths": ["0-20", "20-50"],
        "category": "chemical",
        "importance": "high",
        "description": "Acidity/alkalinity of soil. Determines nutrient availability and optimal fertilizer choice.",
        "recommendation_factors": [
            "Nutrient availability (especially P, K, Mg, Ca)",
            "Aluminum toxicity risk (low pH)",
            "Lime requirement for acidic soils",
            "Fungicide effectiveness"
        ]
    },
    "cec": {
        "name": "Cation Exchange Capacity",
        "unit": "cmol(+)/kg",
        "depths": ["0-20", "20-50"],
        "category": "chemical",
        "importance": "medium",
        "description": "Soil's ability to hold nutrient cations. Indicates soil fertility capacity.",
        "recommendation_factors": [
            "Fertilizer holding capacity",
            "Leaching risk assessment",
            "Nutrient buffering capacity",
            "Soil degradation status"
        ]
    },
    "bulk_density": {
        "name": "Bulk Density",
        "unit": "g/cm³",
        "depths": ["0-20", "20-50", "50-100"],
        "category": "physical",
        "importance": "medium",
        "description": "Mass of soil per unit volume. Indicates soil compaction and water infiltration capacity.",
        "recommendation_factors": [
            "Soil compaction assessment",
            "Water infiltration rate",
            "Root penetration depth",
            "Tillage requirements"
        ]
    },
    "clay": {
        "name": "Clay Content",
        "unit": "%",
        "depths": ["0-20", "20-50"],
        "category": "physical",
        "importance": "medium",
        "description": "Percentage of clay particles (<0.002mm). Affects water retention and workability.",
        "recommendation_factors": [
            "Water holding capacity",
            "Swelling/shrinking potential",
            "Compaction risk",
            "Crust formation risk"
        ]
    },
    "clay_content": {
        "name": "Clay Content",
        "unit": "%",
        "depths": ["0-20", "20-50"],
        "category": "physical",
        "importance": "medium",
        "description": "Percentage of clay particles (<0.002mm). Affects water retention and workability.",
        "recommendation_factors": [
            "Water holding capacity",
            "Swelling/shrinking potential",
            "Compaction risk",
            "Crust formation risk"
        ]
    },
    "silt_content": {
        "name": "Silt Content",
        "unit": "%",
        "depths": ["0-20", "20-50"],
        "category": "physical",
        "importance": "low",
        "description": "Percentage of silt particles (0.002-0.05mm).",
        "recommendation_factors": [
            "Soil workability",
            "Wind erosion risk",
            "Water erosion susceptibility"
        ]
    },
    "sand": {
        "name": "Sand Content",
        "unit": "%",
        "depths": ["0-20", "20-50"],
        "category": "physical",
        "importance": "medium",
        "description": "Percentage of sand particles (0.05-2mm). Affects water drainage and nutrient retention.",
        "recommendation_factors": [
            "Drainage rate",
            "Nutrient leaching risk",
            "Water holding capacity",
            "Compaction resistance"
        ]
    },
    "sand_content": {
        "name": "Sand Content",
        "unit": "%",
        "depths": ["0-20", "20-50"],
        "category": "physical",
        "importance": "medium",
        "description": "Percentage of sand particles (0.05-2mm). Affects water drainage and nutrient retention.",
        "recommendation_factors": [
            "Drainage rate",
            "Nutrient leaching risk",
            "Water holding capacity",
            "Compaction resistance"
        ]
    },
    "phosphorous_extractable": {
        "name": "Extractable Phosphorus",
        "unit": "mg/kg or ppm",
        "depths": ["0-20"],
        "category": "nutrient",
        "importance": "high",
        "description": "Available phosphorus in soil. Critical for root development and energy transfer in plants.",
        "recommendation_factors": [
            "Phosphorus fertilizer requirement",
            "Crop growth and root development",
            "Yield potential",
            "Timing of P application"
        ]
    },
    "potassium_extractable": {
        "name": "Extractable Potassium",
        "unit": "mg/kg or ppm",
        "depths": ["0-20"],
        "category": "nutrient",
        "importance": "high",
        "description": "Available potassium in soil. Essential for plant water regulation, disease resistance, and yield quality.",
        "recommendation_factors": [
            "Potassium fertilizer requirement",
            "Crop disease resistance",
            "Fruit/grain quality",
            "Water use efficiency"
        ]
    },
}

# ─────────────────────────────────────────────────────────────
# SOIL TEXTURE CLASSIFICATION TABLE
# ─────────────────────────────────────────────────────────────

TEXTURE_CLASSIFICATION = {
    "Sand": {"sand": (85, 100), "clay": (0, 10), "silt": (0, 15)},
    "Loamy Sand": {"sand": (70, 90), "clay": (0, 15), "silt": (0, 30)},
    "Sandy Loam": {"sand": (43, 85), "clay": (0, 20), "silt": (0, 50)},
    "Loam": {"sand": (23, 52), "clay": (7, 27), "silt": (28, 50)},
    "Silt Loam": {"sand": (0, 50), "clay": (0, 27), "silt": (50, 80)},
    "Silt": {"sand": (0, 20), "clay": (0, 12), "silt": (80, 100)},
    "Sandy Clay Loam": {"sand": (45, 80), "clay": (20, 35), "silt": (0, 28)},
    "Clay Loam": {"sand": (20, 45), "clay": (27, 40), "silt": (15, 53)},
    "Silty Clay Loam": {"sand": (0, 20), "clay": (27, 40), "silt": (60, 73)},
    "Sandy Clay": {"sand": (45, 65), "clay": (35, 55), "silt": (0, 20)},
    "Silty Clay": {"sand": (0, 20), "clay": (40, 60), "silt": (40, 60)},
    "Clay": {"sand": (0, 45), "clay": (40, 100), "silt": (0, 40)},
}

TEXTURE_CHARACTERISTICS = {
    "Sand": {
        "water_retention": "Low - drains quickly",
        "fertility": "Low - nutrients leach easily",
        "workability": "Easy to work",
        "erosion_risk": "High wind erosion",
        "compaction": "Low compaction risk",
        "crop_suitability": "Drought-tolerant crops, needs frequent irrigation"
    },
    "Loamy Sand": {
        "water_retention": "Low-Medium",
        "fertility": "Low-Medium",
        "workability": "Easy",
        "erosion_risk": "Medium wind erosion",
        "compaction": "Low compaction risk",
        "crop_suitability": "Root vegetables, lighter crops"
    },
    "Sandy Loam": {
        "water_retention": "Medium",
        "fertility": "Medium",
        "workability": "Good",
        "erosion_risk": "Medium",
        "compaction": "Low-Medium compaction risk",
        "crop_suitability": "Most vegetables, fruits, cereals"
    },
    "Loam": {
        "water_retention": "Good - balanced drainage",
        "fertility": "Good - good nutrient availability",
        "workability": "Excellent",
        "erosion_risk": "Low-Medium",
        "compaction": "Medium compaction risk",
        "crop_suitability": "Ideal for most crops"
    },
    "Silt Loam": {
        "water_retention": "Medium-High",
        "fertility": "Good",
        "workability": "Good",
        "erosion_risk": "Medium-High water erosion",
        "compaction": "Medium compaction risk",
        "crop_suitability": "Cereals, legumes, excellent productivity"
    },
    "Silt": {
        "water_retention": "High - tight when dry",
        "fertility": "Medium",
        "workability": "Difficult - crusts easily",
        "erosion_risk": "High water erosion",
        "compaction": "High compaction risk",
        "crop_suitability": "Cereals with drainage management"
    },
    "Sandy Clay Loam": {
        "water_retention": "Medium",
        "fertility": "Medium",
        "workability": "Moderate",
        "erosion_risk": "Low-Medium",
        "compaction": "Medium compaction risk",
        "crop_suitability": "Diverse crops with good drainage"
    },
    "Clay Loam": {
        "water_retention": "High - holds moisture",
        "fertility": "Good-High",
        "workability": "Moderate - sticky when wet",
        "erosion_risk": "Low water erosion",
        "compaction": "High compaction risk",
        "crop_suitability": "Most crops, needs drainage management"
    },
    "Silty Clay Loam": {
        "water_retention": "High",
        "fertility": "High",
        "workability": "Difficult",
        "erosion_risk": "High water erosion",
        "compaction": "Very high compaction risk",
        "crop_suitability": "Cereals, legumes with drainage"
    },
    "Sandy Clay": {
        "water_retention": "Medium-High",
        "fertility": "Medium-High",
        "workability": "Sticky - difficult",
        "erosion_risk": "Low",
        "compaction": "High compaction risk",
        "crop_suitability": "Diverse crops, structural management needed"
    },
    "Silty Clay": {
        "water_retention": "Very High",
        "fertility": "High",
        "workability": "Very difficult - tight when dry",
        "erosion_risk": "Low erosion risk",
        "compaction": "Very high compaction risk",
        "crop_suitability": "Limited - needs intensive drainage"
    },
    "Clay": {
        "water_retention": "Very High - waterlogging risk",
        "fertility": "High - nutrient holding",
        "workability": "Very difficult",
        "erosion_risk": "Very low",
        "compaction": "Very high compaction risk",
        "crop_suitability": "Limited, must manage waterlogging"
    },
}

# ─────────────────────────────────────────────────────────────
# AUTHENTICATION & TOKEN MANAGEMENT
# ─────────────────────────────────────────────────────────────

def get_isda_token(username: str = None, password: str = None) -> str:
    """
    Authenticates with iSDAsoil API and returns access token.
    Caches token for 55 minutes to avoid repeated login calls.
    
    Args:
        username: iSDA username (defaults to ISDASOIL_USERNAME env var)
        password: iSDA password (defaults to ISDASOIL_PASSWORD env var)
    
    Returns:
        Bearer token (str) for subsequent API calls
    
    Raises:
        ValueError if credentials are missing or invalid
        requests.RequestException if API call fails
    """
    global _TOKEN_CACHE
    
    # Check if cached token is still valid
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires_at"]:
        if datetime.now() < _TOKEN_CACHE["expires_at"]:
            return _TOKEN_CACHE["token"]
    
    # Get credentials from parameters or environment
    if not username:
        username = os.getenv("ISDASOIL_USERNAME")
    if not password:
        password = os.getenv("ISDASOIL_PASSWORD")
    
    if not username or not password:
        raise ValueError(
            "❌ iSDA credentials missing!\n"
            "   Set environment variables:\n"
            "   ISDASOIL_USERNAME=your_username\n"
            "   ISDASOIL_PASSWORD=your_password\n"
            "   Or register at: https://isda-africa.com/api/registration"
        )
    
    try:
        payload = {"username": username, "password": password}
        response = requests.post(ISDA_LOGIN_ENDPOINT, data=payload, timeout=10)
        response.raise_for_status()
        
        token = response.json().get("access_token")
        if not token:
            raise ValueError("No access token in response")
        
        # Cache token for 55 minutes (API token expires in 60 minutes)
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires_at"] = datetime.now() + timedelta(minutes=55)
        
        return token
    
    except requests.exceptions.RequestException as e:
        raise requests.RequestException(
            f"❌ Failed to authenticate with iSDAsoil API: {e}\n"
            f"   Check your credentials and ensure you're registered at:\n"
            f"   https://isda-africa.com/api/registration"
        )


# REMOVED: infer_texture_from_components() and classify_texture()
# 
# These functions were injecting hardcoded defaults when API failed.
# Now we simply report texture_usda_class as unavailable with the HTTP error.
# No fallback, no inference, no assumptions.

# ─────────────────────────────────────────────────────────────
# FETCH SOIL DATA
# ─────────────────────────────────────────────────────────────

def get_soil_data(
    latitude: float,
    longitude: float,
    properties: list = None,
    depths: list = None
) -> dict:
    """
    Fetches soil properties from iSDAsoil API for a given location.
    
    Args:
        latitude: Location latitude (-90 to 90)
        longitude: Location longitude (-180 to 180)
        properties: List of property names to fetch (default: all key properties)
        depths: List of depth ranges as strings, e.g. ["0-20", "20-50"]
                (default: all available depths)
    
    Returns:
        Dictionary with soil properties, values, uncertainties, and metadata
    
    Raises:
        ValueError if location is outside Africa or in water/desert
        requests.RequestException if API call fails
    """
    
    # Validate coordinates
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError(f"Invalid coordinates: lat={latitude}, lon={longitude}")
    
    # Default to key soil properties if none specified
    if not properties:
        properties = [
            "carbon_organic",
            "nitrogen_total",
            "ph",
            "sand_content",      # ← Correct API name (NOT "sand")
            "clay_content",      # ← Correct API name (NOT "clay")
            "silt_content",
        ]
    
    # Default to 0-20cm depth (topsoil, most relevant for agriculture)
    if not depths:
        depths = ["0-20"]
    
    # Get authentication token
    try:
        token = get_isda_token()
    except Exception as e:
        raise RuntimeError(f"Authentication failed: {e}")
    
    # Prepare request headers
    headers = {"Authorization": f"Bearer {token}"}
    
    # Build base query parameters (required by API)
    base_params = {
        "lat": latitude,
        "lon": longitude,
    }
    
    try:
        # Fetch all requested properties
        all_data = {
            "metadata": {
                "latitude": latitude,
                "longitude": longitude,
                "requested_at": datetime.now().isoformat(),
                "source": "iSDAsoil API v2",
                "coverage": "Africa only (30m resolution)",
                "api_url": ISDA_SOILPROPERTY_ENDPOINT,
            },
            "properties": {},
            "fetch_status": {}  # ← Track success/failure per property
        }
        
        for prop in properties:
            try:
                # Default depth is 0-20cm for soil properties
                # This matches the official iSDA API documentation
                query_params = {**base_params, "property": prop, "depth": "0-20"}
                
                print(f"[iSDA] Querying: {ISDA_SOILPROPERTY_ENDPOINT}")
                print(f"[iSDA]   Params: lat={query_params['lat']}, lon={query_params['lon']}, property={query_params['property']}, depth={query_params['depth']}")
                
                response = requests.get(
                    ISDA_SOILPROPERTY_ENDPOINT,
                    params=query_params,
                    headers=headers,
                    timeout=15
                )
                response.raise_for_status()
                
                prop_data = response.json()
                if "property" in prop_data and prop in prop_data["property"]:
                    all_data["properties"][prop] = {
                        "data": prop_data["property"][prop],
                        "metadata": SOIL_PROPERTIES_DICT.get(prop, {})
                    }
                    all_data["fetch_status"][prop] = "✅ fetched"
                    
                    # Extract and display the actual value
                    prop_entries = prop_data["property"][prop]
                    if prop_entries and len(prop_entries) > 0:
                        first_entry = prop_entries[0]
                        value = first_entry.get("value", {}).get("value", "N/A")
                        unit = first_entry.get("value", {}).get("unit", "")
                        depth = first_entry.get("depth", {}).get("value", "0-20")
                        
                        # Format value display
                        value_str = f"{value} {unit}".strip() if value != "N/A" else "N/A"
                        print(f"[iSDA] ✅ '{prop}' fetched successfully")
                        print(f"[iSDA]    └─ Value (depth {depth}cm): {value_str}")
                    else:
                        print(f"[iSDA] ✅ '{prop}' fetched successfully")
                else:
                    all_data["fetch_status"][prop] = "⚠️ empty response"
                    print(f"[iSDA] ⚠️  '{prop}' returned empty response")
            
            except requests.exceptions.HTTPError as e:
                if response.status_code == 404:
                    # Property not available at this location
                    msg = f"❌ not available at this location (HTTP 404)"
                    all_data["fetch_status"][prop] = msg
                    print(f"[iSDA] {msg} — '{prop}' will NOT be included")
                elif response.status_code == 422:
                    # Outside iSDA coverage for this property
                    msg = f"❌ outside iSDA coverage at ({latitude}, {longitude}) (HTTP 422)"
                    all_data["fetch_status"][prop] = msg
                    print(f"[iSDA] {msg} — '{prop}' will NOT be included")
                else:
                    msg = f"❌ HTTP {response.status_code} error"
                    all_data["fetch_status"][prop] = msg
                    print(f"[iSDA] {msg} — '{prop}' skipped")
        
        # Print fetch summary
        print(f"[iSDA] Fetch summary:")
        for prop, status in all_data["fetch_status"].items():
            print(f"[iSDA]   {prop}: {status}")
        
        if not all_data["properties"]:
            raise ValueError(
                f"❌ No soil data available for location ({latitude}, {longitude})\n"
                "   iSDAsoil covers Africa only. Check if location is in Africa,\n"
                "   and not in a water body or desert."
            )
        
        return all_data
    
    except requests.exceptions.Timeout:
        raise requests.RequestException("❌ Request timeout — iSDAsoil API not responding")
    except requests.exceptions.RequestException as e:
        raise requests.RequestException(f"❌ Failed to fetch soil data: {e}")

# ─────────────────────────────────────────────────────────────
# PARSE & FORMAT SOIL DATA
# ─────────────────────────────────────────────────────────────

def classify_soil_texture(sand_pct: float, clay_pct: float, silt_pct: float) -> dict:
    """
    Classifies soil texture based on sand, clay, and silt percentages.
    Uses USDA soil texture triangle classification.
    
    Args:
        sand_pct: Sand percentage (0-100)
        clay_pct: Clay percentage (0-100)
        silt_pct: Silt percentage (0-100)
    
    Returns:
        Dictionary with texture class and characteristics:
        {
            "texture_class": "Clay Loam",
            "percentages": {"sand": 30, "clay": 35, "silt": 35},
            "characteristics": {...},
            "confidence": "High" | "Medium" | "Low"
        }
    """
    # Validate input percentages
    total = sand_pct + clay_pct + silt_pct
    confidence = "High"
    
    if total < 95 or total > 105:
        # Percentages don't add up to ~100, reduce confidence
        confidence = "Medium"
        # Normalize to 100% by proportional adjustment
        if total > 0:
            sand_pct = (sand_pct / total) * 100
            clay_pct = (clay_pct / total) * 100
            silt_pct = (silt_pct / total) * 100
    
    # Match against TEXTURE_CLASSIFICATION table
    for texture_name, ranges in TEXTURE_CLASSIFICATION.items():
        sand_min, sand_max = ranges["sand"]
        clay_min, clay_max = ranges["clay"]
        silt_min, silt_max = ranges["silt"]
        
        # Check if all three percentages fall within ranges for this texture
        if (sand_min <= sand_pct <= sand_max and
            clay_min <= clay_pct <= clay_max and
            silt_min <= silt_pct <= silt_max):
            
            return {
                "texture_class": texture_name,
                "percentages": {
                    "sand": round(sand_pct, 1),
                    "clay": round(clay_pct, 1),
                    "silt": round(silt_pct, 1)
                },
                "characteristics": TEXTURE_CHARACTERISTICS.get(texture_name, {}),
                "confidence": confidence
            }
    
    # If no exact match, find closest texture by clay content (primary determinant)
    closest_texture = min(
        TEXTURE_CLASSIFICATION.keys(),
        key=lambda t: abs(clay_pct - (TEXTURE_CLASSIFICATION[t]["clay"][0] + TEXTURE_CLASSIFICATION[t]["clay"][1]) / 2)
    )
    
    return {
        "texture_class": closest_texture,
        "percentages": {
            "sand": round(sand_pct, 1),
            "clay": round(clay_pct, 1),
            "silt": round(silt_pct, 1)
        },
        "characteristics": TEXTURE_CHARACTERISTICS.get(closest_texture, {}),
        "confidence": "Low - No exact match found"
    }


def extract_soil_values(soil_data: dict) -> dict:
    """
    Extracts soil property values from raw API response.
    Applies back-transformation for log-encoded properties.
    Handles uncertainty ranges and multiple depths.
    
    Args:
        soil_data: Raw output from get_soil_data()
    
    Returns:
        Dictionary with organized soil values by property and depth
    """
    extracted = {
        "soil_chemical": {},
        "soil_physical": {},
        "soil_nutrients": {},
        "fetch_status": soil_data.get("fetch_status", {}),  # ← Preserve fetch status
        "location": {
            "latitude": soil_data["metadata"]["latitude"],
            "longitude": soil_data["metadata"]["longitude"],
        }
    }
    
    for prop_name, prop_info in soil_data["properties"].items():
        metadata = prop_info["metadata"]
        category = metadata.get("category", "unknown")
        
        if not prop_info["data"]:
            continue
        
        # Extract value and uncertainty for each depth
        for depth_data in prop_info["data"]:
            depth = depth_data.get("depth", {}).get("value", "unknown")
            
            if "value" in depth_data:
                value_info = depth_data["value"]
                value = value_info.get("value")
                
                # ✅ IMPORTANT: iSDAsoil REST API returns already-scaled values (NOT log-encoded)
                # The API returns: carbon_organic in units where 15.4 ≈ 1.54% (i.e., value × 10)
                # We store raw value here; display code divides by 10 to get percentage
                # 
                # (The exp(x/10)-1 back-transformation is ONLY for GeoTIFF raster downloads,
                #  not for the REST API endpoint. REST API values are direct measurements.)
                
                if prop_name == "carbon_organic" and value is not None:
                    # API returns scaled value: 15.4 means 1.54% organic carbon
                    # Store as-is; will be divided by 10 in display functions
                    value = round(value, 2)
                
                elif prop_name == "nitrogen_total" and value is not None:
                    # API returns scaled value: 1.5 means 0.15% total nitrogen  
                    # Store as-is; will be divided by 10 in display functions
                    value = round(value, 2)
                
                # texture_usda_class handling removed — do not infer or convert
                
                uncertainty = None
                if "uncertainty" in depth_data and depth_data["uncertainty"]:
                    unc = depth_data["uncertainty"][0]
                    uncertainty = {
                        "lower": unc.get("lower_bound"),
                        "upper": unc.get("upper_bound"),
                    }
                
                entry = {
                    "depth": depth,
                    "value": value,
                    "unit": metadata.get("unit", "N/A"),
                    "uncertainty": uncertainty,
                }
                
                # Categorize by property type
                if category == "chemical":
                    if prop_name not in extracted["soil_chemical"]:
                        extracted["soil_chemical"][prop_name] = []
                    extracted["soil_chemical"][prop_name].append(entry)
                
                elif category == "physical":
                    if prop_name not in extracted["soil_physical"]:
                        extracted["soil_physical"][prop_name] = []
                    extracted["soil_physical"][prop_name].append(entry)
                
                elif category == "nutrient":
                    if prop_name not in extracted["soil_nutrients"]:
                        extracted["soil_nutrients"][prop_name] = []
                    extracted["soil_nutrients"][prop_name].append(entry)
    
    return extracted

# ─────────────────────────────────────────────────────────────
# SOIL DATA INTERPRETATION FOR FARMING RECOMMENDATIONS
# ─────────────────────────────────────────────────────────────

def interpret_soil_for_recommendations(extracted_soil: dict) -> dict:
    """
    Interprets soil properties into actionable farming recommendations.
    
    Args:
        extracted_soil: Output from extract_soil_values()
    
    Returns:
        Dictionary with interpretation, risk flags, and recommendations
    """
    interpretation = {
        "location": extracted_soil["location"],
        "soil_health_summary": "",
        "critical_factors": [],
        "recommendations": [],
        "risk_flags": [],
        "details": {}
    }
    
    # ─ Carbon & Organic Matter ─
    carbon_data = extracted_soil["soil_chemical"].get("carbon_organic", [])
    if carbon_data:
        carbon_020 = next((c["value"] for c in carbon_data if c["depth"] == "0-20"), None)
        if carbon_020 is not None:
            carbon_pct = carbon_020 / 10  # Convert g/kg to percentage
            if carbon_pct < 1.0:
                interpretation["risk_flags"].append(
                    f"⚠️  LOW ORGANIC MATTER: {carbon_pct:.2f}% at 0-20cm (optimal >2%)\n"
                    "   Soil structure, water retention, and microbial activity are compromised."
                )
                interpretation["recommendations"].append(
                    "→ URGENT: Increase organic matter through:\n"
                    "  • Crop residue retention (mulching)\n"
                    "  • Compost or manure application (5-10 t/ha annually)\n"
                    "  • Green manure crops (legumes)\n"
                    "  • Reduced/conservation tillage"
                )
            elif carbon_pct < 2.0:
                interpretation["critical_factors"].append(
                    f"Moderate organic matter: {carbon_pct:.2f}% at 0-20cm (target: >2.5%)"
                )
            else:
                interpretation["critical_factors"].append(
                    f"Good organic matter: {carbon_pct:.2f}% at 0-20cm"
                )
    
    # ─ Nitrogen ─
    nitrogen_data = extracted_soil["soil_nutrients"].get("nitrogen_total", [])
    if nitrogen_data:
        nitrogen_020 = next((n["value"] for n in nitrogen_data if n["depth"] == "0-20"), None)
        if nitrogen_020 is not None:
            nitrogen_pct = nitrogen_020 / 10  # Convert g/kg to percentage
            if nitrogen_pct < 0.1:
                interpretation["risk_flags"].append(
                    f"⚠️  VERY LOW NITROGEN: {nitrogen_pct:.3f}% (need fertilization)\n"
                    "   Crop growth will be severely limited."
                )
                interpretation["recommendations"].append(
                    "→ FERTILIZER NEEDED: Apply nitrogen at planting + topdress\n"
                    "  • Planting rate: 50-75 kg N/ha (e.g., DAP or CAN)\n"
                    "  • Topdress at V4-V6: 100-150 kg N/ha CAN (Calcium Ammonium Nitrate)"
                )
            elif nitrogen_pct < 0.2:
                interpretation["critical_factors"].append(
                    f"Low nitrogen: {nitrogen_pct:.3f}% (fertilizer recommended)"
                )
                interpretation["recommendations"].append(
                    "→ Moderate nitrogen fertilization recommended"
                )
            else:
                interpretation["critical_factors"].append(
                    f"Adequate nitrogen: {nitrogen_pct:.3f}%"
                )
    
    # ─ Soil pH ─
    ph_data = extracted_soil["soil_chemical"].get("ph", [])
    if ph_data:
        ph_020 = next((p["value"] for p in ph_data if p["depth"] == "0-20"), None)
        if ph_020 is not None:
            if ph_020 < 5.5:
                interpretation["risk_flags"].append(
                    f"⚠️  ACIDIC SOIL: pH {ph_020:.1f} (too acidic, <5.5)\n"
                    "   Aluminum toxicity risk; nutrient availability reduced."
                )
                interpretation["recommendations"].append(
                    "→ LIME APPLICATION RECOMMENDED:\n"
                    "  • Target pH 6.0-6.5 for most crops\n"
                    "  • Apply agricultural lime 1-2 t/ha\n"
                    "  • Incorporate before planting"
                )
            elif ph_020 < 6.0:
                interpretation["critical_factors"].append(
                    f"Slightly acidic: pH {ph_020:.1f} (consider lime if <5.8)"
                )
            elif ph_020 > 7.5:
                interpretation["risk_flags"].append(
                    f"⚠️  ALKALINE SOIL: pH {ph_020:.1f} (too alkaline, >7.5)\n"
                    "   Iron, Manganese, Zinc deficiencies likely."
                )
                interpretation["recommendations"].append(
                    "→ MICRONUTRIENT MANAGEMENT:\n"
                    "  • Foliar spray of Fe, Mn, Zn chelates\n"
                    "  • Or ground application of sulfur (if possible)"
                )
            else:
                interpretation["critical_factors"].append(
                    f"Optimal pH: {ph_020:.1f}"
                )
    
    # Texture-based logic removed: recommendations should rely on available
    # quantitative properties (clay, sand, bulk_density) rather than USDA class.
    
    # ─ Bulk Density (compaction indicator) ─
    bd_data = extracted_soil["soil_physical"].get("bulk_density", [])
    if bd_data:
        bd_020 = next((b["value"] for b in bd_data if b["depth"] == "0-20"), None)
        if bd_020 is not None:
            if bd_020 > 1.4:
                interpretation["risk_flags"].append(
                    f"⚠️  SOIL COMPACTION: Bulk density {bd_020:.2f} g/cm³ (>1.4 indicates compaction)\n"
                    "   Root penetration restricted; water infiltration reduced."
                )
                interpretation["recommendations"].append(
                    "→ REMEDIATE COMPACTION:\n"
                    "  • Deep ripping/subsoiling (if available)\n"
                    "  • Reduce tillage frequency\n"
                    "  • Grow deep-rooted crops or green manure"
                )
            else:
                interpretation["critical_factors"].append(
                    f"Good soil structure: Bulk density {bd_020:.2f} g/cm³"
                )
    
    # Generate summary
    if interpretation["risk_flags"]:
        interpretation["soil_health_summary"] = "⚠️  CAUTION NEEDED: Multiple soil constraints detected"
    elif interpretation["critical_factors"]:
        interpretation["soil_health_summary"] = "✓ Generally suitable, with specific optimizations needed"
    else:
        interpretation["soil_health_summary"] = "✓ Good soil conditions"
    
    return interpretation

# ─────────────────────────────────────────────────────────────
# FORMAT OUTPUT FOR CHATBOT INTEGRATION
# ─────────────────────────────────────────────────────────────

def format_soil_output(soil_data: dict, extracted: dict = None) -> str:
    """
    Formats soil data into readable output for chatbot/terminal display.
    
    Args:
        soil_data: Raw output from get_soil_data()
        extracted: Output from extract_soil_values() (will be computed if not provided)
    
    Returns:
        Formatted string for display
    """
    if not extracted:
        extracted = extract_soil_values(soil_data)
    
    interpretation = interpret_soil_for_recommendations(extracted)
    
    output = []
    output.append("\n" + "=" * 80)
    output.append("SOIL PROPERTY ANALYSIS — iSDAsoil Data")
    output.append("=" * 80)
    output.append(f"\nLocation: Lat {interpretation['location']['latitude']:.2f}, "
                  f"Lon {interpretation['location']['longitude']:.2f}")
    output.append(f"Status: {interpretation['soil_health_summary']}\n")
    
    # ─ Critical Factors ─
    if interpretation["critical_factors"]:
        output.append("KEY SOIL PROPERTIES:")
        output.append("─" * 80)
        for factor in interpretation["critical_factors"]:
            output.append(f"  • {factor}")
        output.append("")
    
    # ─ Risk Flags ─
    if interpretation["risk_flags"]:
        output.append("⚠️  RISK FLAGS:")
        output.append("─" * 80)
        for risk in interpretation["risk_flags"]:
            output.append(f"  {risk}")
        output.append("")
    
    # ─ Recommendations ─
    if interpretation["recommendations"]:
        output.append("RECOMMENDED ACTIONS:")
        output.append("─" * 80)
        for rec in interpretation["recommendations"]:
            output.append(f"  {rec}")
        output.append("")
    
    # ─ Detailed Data Table ─
    output.append("\nDETAILED SOIL PROPERTIES:")
    output.append("─" * 80)
    
    output.append("\n[CHEMICAL PROPERTIES]")
    for prop, values in extracted["soil_chemical"].items():
        prop_info = SOIL_PROPERTIES_DICT.get(prop, {})
        prop_name = prop_info.get("name", prop)
        output.append(f"\n  {prop_name} ({prop_info.get('description', '')})")
        for v in values:
            unc_str = ""
            if v["uncertainty"]:
                unc_str = f" ± {v['uncertainty']['lower']:.2f}–{v['uncertainty']['upper']:.2f}"
            output.append(f"    → {v['depth']}: {v['value']:.2f} {v['unit']}{unc_str}")
    
    output.append("\n[PHYSICAL PROPERTIES]")
    for prop, values in extracted["soil_physical"].items():
        prop_info = SOIL_PROPERTIES_DICT.get(prop, {})
        prop_name = prop_info.get("name", prop)
        output.append(f"\n  {prop_name} ({prop_info.get('description', '')})")
        for v in values:
            if v["value"] is not None:
                if isinstance(v["value"], (int, float)):
                    output.append(f"    → {v['depth']}: {v['value']:.2f} {v['unit']}")
                else:
                    output.append(f"    → {v['depth']}: {v['value']} {v['unit']}")
    
    output.append("\n[SOIL NUTRIENTS]")
    for prop, values in extracted["soil_nutrients"].items():
        prop_info = SOIL_PROPERTIES_DICT.get(prop, {})
        prop_name = prop_info.get("name", prop)
        output.append(f"\n  {prop_name}")
        for v in values:
            unc_str = ""
            if v["uncertainty"]:
                unc_str = f" ± {v['uncertainty']['lower']:.2f}–{v['uncertainty']['upper']:.2f}"
            output.append(f"    → {v['depth']}: {v['value']:.3f} {v['unit']}{unc_str}")
    
    output.append("\n" + "=" * 80 + "\n")
    
    return "\n".join(output)

# ─────────────────────────────────────────────────────────────
# SAVE SOIL DATA TO JSON
# ─────────────────────────────────────────────────────────────

def save_soil_data(
    soil_data: dict,
    extracted: dict = None,
    filename: str = None
) -> str:
    """
    Saves soil data to JSON file for integration with other modules.
    
    Args:
        soil_data: Output from get_soil_data()
        extracted: Output from extract_soil_values()
        filename: Custom filename (default: isdasoil_lat_lon.json)
    
    Returns:
        Path to saved file
    """
    if not extracted:
        extracted = extract_soil_values(soil_data)
    
    interpretation = interpret_soil_for_recommendations(extracted)
    
    output = {
        "metadata": soil_data["metadata"],
        "extracted_values": extracted,
        "interpretation": interpretation,
        "generated_at": datetime.now().isoformat(),
    }
    
    if not filename:
        lat = soil_data["metadata"]["latitude"]
        lon = soil_data["metadata"]["longitude"]
        filename = f"isdasoil_{lat:.2f}_{lon:.2f}.json"
    
    with open(filename, "w") as f:
        json.dump(output, f, indent=2)
    
    return filename

# ─────────────────────────────────────────────────────────────
# MAIN - STANDALONE USAGE
# ─────────────────────────────────────────────────────────────

def main():
    """
    Standalone script for testing soil data retrieval.
    """
    print("\n" + "=" * 80)
    print("iSDAsoil Standalone Script — Soil Property Data Retrieval")
    print("=" * 80)
    
    # Get user inputs
    while True:
        try:
            lat = float(input("\n📍 Enter Latitude  (e.g. 1.02 for Kenya): ").strip())
            if -90 <= lat <= 90:
                break
            print("   ⚠️  Latitude must be between -90 and 90.")
        except ValueError:
            print("   ⚠️  Please enter a valid number.")
    
    while True:
        try:
            lon = float(input("📍 Enter Longitude (e.g. 35.00 for Kenya): ").strip())
            if -180 <= lon <= 180:
                break
            print("   ⚠️  Longitude must be between -180 and 180.")
        except ValueError:
            print("   ⚠️  Please enter a valid number.")
    
    region = input("🗺️  Enter Region Name (optional, e.g. Trans Nzoia, Kenya): ").strip()
    
    print(f"\n⏳ Fetching soil data from iSDAsoil API...")
    print(f"   Location: {region} ({lat}, {lon})")
    
    try:
        # Fetch soil data
        soil_data = get_soil_data(latitude=lat, longitude=lon)
        extracted = extract_soil_values(soil_data)
        
        # Display output
        output = format_soil_output(soil_data, extracted)
        print(output)
        
        # Save to file
        filename = save_soil_data(soil_data, extracted)
        print(f"✅ Data saved to: {filename}\n")
    
    except ValueError as e:
        print(f"\n❌ {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
