"""
=============================================================
MCP SERVER — agro-context tools
=============================================================

Exposes the 5 tools from agent_tools.py over the Model Context Protocol:
  resolve_location, get_weather_forecast, get_historical_weather, get_seasonal_forecast,
  get_soil_profile

Run:
  python mcp_server.py                         # stdio (for MCP clients / tool_agent.py --mcp)
  python mcp_server.py --http                  # streamable HTTP on http://127.0.0.1:8000/mcp
  mcp dev mcp_server.py                        # open in the MCP Inspector (needs Node.js)
  python mcp_server.py --self-test             # list tools and call each one in-process

Requires: pip install "mcp[cli]" (v2), GEONAMES_USERNAME / ISDASOIL_USERNAME / ISDASOIL_PASSWORD
in .env, and a Copernicus CDS account in ~/.cdsapirc (seasonal forecast)
=============================================================
"""

import argparse
import asyncio
import contextlib
import functools
import json
import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from agent_tools import TOOL_DESCRIPTIONS, TOOL_FUNCTIONS

SERVER_INSTRUCTIONS = (
    "Agricultural context tools. resolve_location turns a place name into coordinates; "
    "get_weather_forecast, get_historical_weather, get_seasonal_forecast and get_soil_profile take "
    "those coordinates. Past weather comes from get_historical_weather, future weather from "
    "get_weather_forecast. "
    "Soil data covers Africa only."
)

# All tools only read public/external data
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=True)


def _stdout_safe(fn):
    """On stdio, stdout carries the MCP protocol — send any stray print() to stderr instead."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with contextlib.redirect_stdout(sys.stderr):
            return fn(*args, **kwargs)
    return wrapper


def build_server() -> MCPServer:
    server = MCPServer("agro-context-tools", instructions=SERVER_INSTRUCTIONS, version="0.1.0",
                         log_level="WARNING")
    for name, fn in TOOL_FUNCTIONS.items():
        server.add_tool(_stdout_safe(fn), name=name, description=TOOL_DESCRIPTIONS[name],
                        annotations=READ_ONLY)
    return server


mcp = build_server()  # module-level name lets `mcp dev mcp_server.py` find the server


async def self_test() -> None:
    """List the tools and call each one through an in-memory MCP client."""
    from mcp.client import Client

    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
        print(f"Tools ({len(tools)}):")
        for t in tools:
            print(f"  • {t.name}: params={list(t.input_schema.get('properties', {}))}")

        loc = await client.call_tool("resolve_location", {"place": "Kaolack, Senegal"})
        loc_data = loc.structured_content or json.loads(loc.content[0].text)
        loc_data = loc_data.get("result", loc_data)
        print(f"\nresolve_location → {loc_data['name']} ({loc_data['latitude']}, {loc_data['longitude']})")
        lat, lon = loc_data["latitude"], loc_data["longitude"]

        calls = [
            ("get_weather_forecast", {"latitude": lat, "longitude": lon, "horizon_days": 3,
                                      "variables": ["precipitation", "wind_speed_max"]}),
            ("get_historical_weather", {"latitude": lat, "longitude": lon, "start_date": "2024-07-01",
                                        "end_date": "2024-09-30", "variables": ["precipitation"]}),
            ("get_soil_profile", {"latitude": lat, "longitude": lon, "properties": ["ph", "texture"]}),
            ("get_weather_forecast", {"latitude": lat, "longitude": lon, "horizon_days": 99}),  # invalid on purpose
        ]
        for name, args in calls:
            r = await client.call_tool(name, args)
            text = r.content[0].text if r.content else ""
            print(f"{name}({args}) → is_error={r.is_error}: {text[:160]}...")


def main():
    parser = argparse.ArgumentParser(description="MCP server for agro-context tools")
    parser.add_argument("--http", action="store_true", help="Serve over streamable HTTP instead of stdio")
    parser.add_argument("--self-test", action="store_true", help="Call each tool in-process and exit")
    args = parser.parse_args()

    if args.self_test:
        asyncio.run(self_test())
    elif args.http:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
