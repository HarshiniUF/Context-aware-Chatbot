# Context-Aware Chatbot — Workflow Changes

## 1. Old vs New Workflow

| | Old (`wsp_unified_forecast.py`) | New (`tool_agent.py`) |
|---|---|---|
| Data fetching | Fixed pipeline: fetches daily forecast, seasonal forecast and soil for **every** question | **LLM decides** which tools to call (0, 1 or several) per question |
| Prompt | `UNIFIED_PROMPT` | **SKILL.md** (Contextual GATE) for every question |
| Inputs | Asks location + crop every time | Confirms location + crop when the location tool is used |
| Model | gpt-5 | **claude-4.6-sonnet** (via NaviGator; switchable with `LLM_MODEL`) |

```
Question → LLM (SKILL.md + 5 tools) → calls tools it needs → farmer confirms location/crop → answer
```

## 2. The Five Tools (exposed as an MCP server)

| Tool | Source | Returns |
|---|---|---|
| `resolve_location` | **GeoNames API** | Coordinates, timezone, precision (town / county / state / country), ambiguity + candidates |
| `get_weather_forecast` | Open-Meteo | Daily rain, temperature, ET₀, wind, humidity, soil moisture; today + up to 16 days ahead |
| `get_historical_weather` | Open-Meteo Archive (ERA5 reanalysis) | Past daily weather from 1940 to yesterday (monthly totals for long periods); rain & temperature vs the 1991–2020 normal for the same days (% of normal, wetter/drier, rank among 30 years) |
| `get_seasonal_forecast` | ECMWF SEAS5 (Copernicus CDS) | Monthly rainfall & temperature for the next ~5–6 months vs the normal climate (% of normal, wetter/drier/near normal); 1° grid |
| `get_soil_profile` | iSDAsoil (30 m) | Texture, pH, organic carbon, N/P/K, CEC, etc. at 0–20 / 20–50 cm, with 90% ranges |

- `mcp_server.py` serves the tools over the Model Context Protocol (input/output schemas, read-only).
- `agent_tools.py` holds the single definition of each tool (names, descriptions, inputs) used by both the MCP server and the agent.

## 3. Key Changes

1. **LLM-driven tool selection** — no hardcoded rules yet; the LLM chooses tools from the question, SKILL.md and the tool descriptions.
2. **SKILL.md as system prompt** for every question; tool-use instructions can be added separately (`--rules file`) to compare with/without them.
3. **Location + crop confirmation** — when the LLM calls the location tool, the farmer confirms/corrects the place and the crop before the LLM continues.
4. **GeoNames for location** (same as the DSSAT project) — now finds counties, states and regions (e.g. Trans Nzoia, Kaolack Region), handles accents and typos.
5. **Weather fixes** — past dates beyond 90 days work (Historical Forecast API); dates are local to the farm, with weekdays.
6. **Date fix** — "today" uses the farm's local date (Kenya), not the computer's.
7. **Seasonal forecast as a tool** — the old pipeline always fetched ECMWF SEAS5; now the LLM calls it only for season/planning questions. Fixed old-code issues: months were labelled one month late, negative longitudes (e.g. Senegal) picked the wrong grid point, and "above/below normal" compared forecast months with each other instead of the normal climate (now uses the SEAS5 hindcast climate mean).
8. **Safety guard** — weather/soil calls with unconfirmed (guessed) coordinates are blocked and redone with the confirmed location.

## 4. Design Principle

| Handled by **code** (always enforced) | Handled by **LLM + instructions** (judgement) |
|---|---|
| Location/crop confirmation, correct dates, blocking wrong coordinates | Which tools to call, which variables/depths, how to answer |

## 5. Test Results So Far (no tool-use instructions)

| Question | Expected tools | LLM called | Result |
|---|---|---|---|
| Maize yield in Kenya / DAP vs CAN / maize maturity | none | none | ✅ |
| Rain in next 3 days | weather | weather | ✅ |
| Is my soil acidic? / phosphorus for beans | soil | soil | ✅ |
| Top-dress urea near Nakuru | location, weather, soil | location, weather, soil | ✅ |
| Heat in Kaolack this week | location, weather | location, weather | ✅ |
| Kisumu soil for rice | location, soil | + weather | ⚠️ extra tool |

**Observations**
- Tool choice is mostly correct without instructions.
- Weaknesses: extra weather call for a long-term suitability question; long, table-heavy answers; local facts from memory can be wrong (e.g. maize variety maturity groups for Kitale).
- Questions about "my farm" use the default farm (Kitale) without confirmation — to be addressed.

## 6. Next Steps

1. Finish testing with varied questions (no instructions).
2. Write tool-use instructions from the observed gaps (when to call / not call each tool, which inputs per decision).
3. Re-run the same questions with instructions and compare.
