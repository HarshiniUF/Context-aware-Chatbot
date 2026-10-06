"""
=============================================================
AGENT TOOLS — single definition of the 5 tools the LLM can call
=============================================================

Each tool is a plain function whose signature (types + Field descriptions)
IS the input schema, and whose TOOL_DESCRIPTIONS entry is what the LLM reads.
Both consumers build from this file, so they always match:

  mcp_server.py  → registers them on an MCP server (MCPServer.add_tool)
  tool_agent.py  → binds them to the LLM as LangChain tools (local mode)

All tools return a JSON-serializable dict and never raise on bad data
(they return {"ok": False, "error": ...} / {"found": False, "error": ...}).
=============================================================
"""

from typing import Annotated, Any, List, Literal, Optional

from pydantic import Field

from historical_weather_tool import get_historical_weather as _get_historical_weather
from location_resolver import resolve_location as _resolve_location
from seasonal_tool import get_seasonal_forecast as _get_seasonal_forecast
from soil_tool import get_soil_profile as _get_soil_profile
from weather_tool import get_weather_forecast as _get_weather_forecast

WeatherVariable = Literal[
    "precipitation", "precipitation_probability", "precipitation_hours",
    "temperature_max", "temperature_min", "temperature_mean", "et0",
    "relative_humidity_mean", "wind_speed_max", "wind_gusts_max",
    "solar_radiation", "sunshine_duration", "soil_moisture_0_7cm",
]
HistoricalVariable = Literal[
    "precipitation", "precipitation_hours", "temperature_max", "temperature_min",
    "temperature_mean", "et0", "relative_humidity_mean", "wind_speed_max", "wind_gusts_max",
    "solar_radiation", "sunshine_duration", "soil_moisture_0_7cm",
]
SoilProperty = Literal[
    "organic_carbon", "total_carbon", "nitrogen", "ph", "sand", "silt", "clay",
    "texture", "cec", "bulk_density", "stone_content", "bedrock_depth",
    "phosphorus", "potassium", "calcium", "magnesium", "sulphur", "zinc",
    "iron", "aluminium", "fertility_constraints", "slope",
]
SoilDepth = Literal["0-20", "20-50"]

Latitude = Annotated[float, Field(ge=-90, le=90, description="Latitude in decimal degrees.")]
Longitude = Annotated[float, Field(ge=-180, le=180, description="Longitude in decimal degrees.")]


# ─────────────────────────────────────────────────────────────
# TOOLS
# ─────────────────────────────────────────────────────────────
def resolve_location(
    place: Annotated[Optional[str], Field(
        description="Place name, e.g. 'Kitale, Kenya' or 'Kaolack, Senegal'. "
                    "Add region/country after commas to narrow the match.")] = None,
    latitude: Annotated[Optional[float], Field(
        ge=-90, le=90, description="Latitude, only if the farmer gave coordinates.")] = None,
    longitude: Annotated[Optional[float], Field(
        ge=-180, le=180, description="Longitude, only if the farmer gave coordinates.")] = None,
) -> dict[str, Any]:
    return _resolve_location(place, latitude, longitude)


def get_weather_forecast(
    latitude: Latitude,
    longitude: Longitude,
    horizon_days: Annotated[int, Field(ge=1, le=16, description="Number of days to return (1-16).")] = 7,
    variables: Annotated[Optional[List[WeatherVariable]], Field(
        description="Daily variables to return. Default: precipitation, precipitation_probability, "
                    "temperature_max, temperature_min, et0.")] = None,
    start_date: Annotated[Optional[str], Field(
        description="First day as YYYY-MM-DD. Default: today at the location. "
                    "For what the weather was on past days, use get_historical_weather.")] = None,
) -> dict[str, Any]:
    return _get_weather_forecast(latitude, longitude, horizon_days=horizon_days,
                                 variables=variables, start_date=start_date)


def get_historical_weather(
    latitude: Latitude,
    longitude: Longitude,
    start_date: Annotated[str, Field(description="First day as YYYY-MM-DD (1940-01-02 or later).")],
    end_date: Annotated[Optional[str], Field(
        description="Last day as YYYY-MM-DD, before today. Default: start_date (a single day). "
                    "Up to ~10 years per call.")] = None,
    variables: Annotated[Optional[List[HistoricalVariable]], Field(
        description="Daily variables to return. Default: precipitation, temperature_max, "
                    "temperature_min, et0.")] = None,
    compare_to_normal: Annotated[bool, Field(
        description="Compare the period's rain and temperature with the 1991-2020 normal for the same "
                    "calendar days (periods up to 366 days).")] = True,
) -> dict[str, Any]:
    return _get_historical_weather(latitude, longitude, start_date, end_date=end_date,
                                   variables=variables, compare_to_normal=compare_to_normal)


def get_seasonal_forecast(
    latitude: Latitude,
    longitude: Longitude,
    months_ahead: Annotated[int, Field(
        ge=1, le=6, description="Number of months to return, starting with the current month (1-6).")] = 3,
) -> dict[str, Any]:
    return _get_seasonal_forecast(latitude, longitude, months_ahead=months_ahead)


def get_soil_profile(
    latitude: Latitude,
    longitude: Longitude,
    depths: Annotated[Optional[List[SoilDepth]], Field(
        description="Soil depths in cm. Only '0-20' and '20-50' exist. Default: ['0-20'].")] = None,
    properties: Annotated[Optional[List[SoilProperty]], Field(
        description="Soil properties to return. Default: texture, sand, silt, clay, "
                    "organic_carbon, fertility_constraints.")] = None,
) -> dict[str, Any]:
    # The SoilGrids WRB soil-type lookup is slow (10-60 s) and often times out, so it is skipped here
    return _get_soil_profile(latitude, longitude, depths=depths, properties=properties,
                             include_soil_type=False)


# ─────────────────────────────────────────────────────────────
# DESCRIPTIONS (what the LLM reads when deciding which tool to call)
# ─────────────────────────────────────────────────────────────
TOOL_DESCRIPTIONS = {
    "resolve_location":
        "Convert a place name or farm coordinates into latitude, longitude, timezone and location "
        "precision (country / state / district / town / exact point). Reports when a name is "
        "ambiguous and lists the candidate places.",
    "get_weather_forecast":
        "Daily weather forecast for a location from Open-Meteo: today and up to 16 days ahead. "
        "Variables include rain, rain probability, temperature, reference evapotranspiration (ET0), "
        "humidity, wind, solar radiation and topsoil moisture. Returns daily values, units and a "
        "per-variable summary. For past days (what the weather was) use get_historical_weather.",
    "get_historical_weather":
        "Observed past weather for a location (ERA5 reanalysis via Open-Meteo), any period from 1940 "
        "up to yesterday: rain, temperature, ET0, humidity, wind, solar radiation, topsoil moisture. "
        "Periods up to 62 days return daily values, longer ones monthly totals. Also compares the "
        "period's rain and temperature with the 1991-2020 normal for the same calendar days (percent "
        "of normal, wetter/drier/near-normal, how many of the 30 years were drier). Use it for 'how "
        "much rain fell', 'was this season dry', 'what is normal rainfall here in October', and to "
        "check recent rain before advice on planting, fertilizer or spraying.",
    "get_seasonal_forecast":
        "Seasonal outlook from ECMWF SEAS5: monthly rainfall and temperature for the coming months "
        "(up to about 5-6), each compared with the normal climate for that month (percent of normal "
        "rainfall, temperature anomaly, and a wetter/drier/near-normal category). Coarse 1° (~110 km) "
        "regional outlook. The first call after a new monthly forecast may take about a minute.",
    "get_soil_profile":
        "Soil properties for a location in Africa from iSDAsoil (30 m resolution): texture, "
        "sand/silt/clay, organic carbon, pH, nitrogen, extractable nutrients (P, K, Ca, Mg, S, Zn, "
        "Fe, Al), CEC, bulk density, stoniness, bedrock depth, slope and fertility constraints, at "
        "0-20 and/or 20-50 cm. Values come with 90% uncertainty ranges. These are static soil "
        "properties; for current soil moisture use get_weather_forecast or get_historical_weather (soil_moisture_0_7cm).",
}

TOOL_FUNCTIONS = {
    "resolve_location": resolve_location,
    "get_weather_forecast": get_weather_forecast,
    "get_historical_weather": get_historical_weather,
    "get_seasonal_forecast": get_seasonal_forecast,
    "get_soil_profile": get_soil_profile,
}
