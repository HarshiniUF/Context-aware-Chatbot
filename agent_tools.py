"""
=============================================================
AGENT TOOLS — single definition of the 3 tools the LLM can call
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

from location_resolver import resolve_location as _resolve_location
from soil_tool import get_soil_profile as _get_soil_profile
from weather_tool import get_weather_forecast as _get_weather_forecast

WeatherVariable = Literal[
    "precipitation", "precipitation_probability", "precipitation_hours",
    "temperature_max", "temperature_min", "temperature_mean", "et0",
    "relative_humidity_mean", "wind_speed_max", "wind_gusts_max",
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
                    "Past dates (including months or years back) return what the weather was.")] = None,
) -> dict[str, Any]:
    return _get_weather_forecast(latitude, longitude, horizon_days=horizon_days,
                                 variables=variables, start_date=start_date)


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
        "Daily weather for a location from Open-Meteo: up to 16 days ahead, or any past period via "
        "start_date. Variables include rain, rain probability, temperature, reference "
        "evapotranspiration (ET0), humidity, wind, solar radiation and topsoil moisture. Returns "
        "daily values, units and a per-variable summary.",
    "get_soil_profile":
        "Soil properties for a location in Africa from iSDAsoil (30 m resolution): texture, "
        "sand/silt/clay, organic carbon, pH, nitrogen, extractable nutrients (P, K, Ca, Mg, S, Zn, "
        "Fe, Al), CEC, bulk density, stoniness, bedrock depth, slope and fertility constraints, at "
        "0-20 and/or 20-50 cm. Values come with 90% uncertainty ranges. These are static soil "
        "properties; for current soil moisture use get_weather_forecast (soil_moisture_0_7cm).",
}

TOOL_FUNCTIONS = {
    "resolve_location": resolve_location,
    "get_weather_forecast": get_weather_forecast,
    "get_soil_profile": get_soil_profile,
}
