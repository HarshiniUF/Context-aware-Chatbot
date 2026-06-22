# WSP Contextual Agricultural Chatbot

A context-driven agricultural advisory system. It synthesizes weather, soil, and farmer
context to answer farmer questions — but the design principle is that all that context is
used to *calibrate* the advice, never *cited* in it. The farmer gets expert-sounding,
specific recommendations, not a data report.

---

## 1. Two Chatbots in This Repo

### `wsp_unified_forecast.py` — Main chatbot (run this)
Full GATE-context pipeline: farmer profile + soil (iSDAsoil) + daily forecast (Open-Meteo)
+ seasonal forecast (ECMWF SEAS5), all synthesized through `UNIFIED_PROMPT` in `wsp_config.py`.

```bash
python wsp_unified_forecast.py            # interactive chat
python wsp_unified_forecast.py demo       # sample questions, no input needed
python wsp_unified_forecast.py --single   # daily forecast only (no seasonal)
```

### `simple_context_chatbot.py` — Minimal chatbot
Uses only **location, crop, and date** — nothing else. No soil, no weather. The prompt
(`SIMPLE_PROMPT` in that file) explicitly instructs the LLM *not* to reference soil or
weather, since none is provided. Useful for quick, lightweight Q&A or as a baseline to
compare against the full context-driven answers.

```bash
python simple_context_chatbot.py
```

---

## 2. Core Design Principle: Context Shapes, Never Cites

`UNIFIED_PROMPT` (in `wsp_config.py`) is built around one rule: every context
dimension — soil pH/texture, seasonal outlook, daily rain timing, growth stage — must be
internalized during reasoning, but **none of it may appear in the final answer**. No soil
values, no forecast dates, no mm figures, no seasonal categories, no provider names, no
coordinates.

The pipeline still does the full reasoning (crop growth-stage inference, cross-context
conflict resolution, risk prioritization) — it just expresses the result as direct
agronomic advice ("apply 30–40 kg N/ha, banded near the row") instead of a citation
("because soil nitrogen is low and rain is forecast for June 22").

If you're modifying the prompt, the two enforcement points are:
- **STEP 6 (Context Internalization Check)** — the explicit pre-write filter
- **RESPONSE RULES** (`✗` entries) — the hard prohibitions and banned phrases

---

## 3. Date Handling: Today vs. Scenario Questions

- If the question names a date/season ("middle of June", "next planting season") →
  `date_source: "user_explicit"`, and that date becomes the operating context.
- If no date is mentioned → defaults to today (`date_source: "default_today"`).
- **Live weather/soil fetches only run when the resolved date equals today.** For any
  other date, provider calls are skipped and the LLM reasons from soil + farmer context
  only (no live forecast data exists for a future/past date anyway).

Full details: [`DOCS_DATE_POLICY.md`](./DOCS_DATE_POLICY.md).

Crop and date are both extracted via LLM (`extract_crop_and_date_json()` in
`wsp_config.py`), with regex fallback if the LLM call fails. Details:
[`CROP_EXTRACTION_UPGRADE.md`](./CROP_EXTRACTION_UPGRADE.md),
[`LLM_EXTRACTION_FINAL_SUMMARY.md`](./LLM_EXTRACTION_FINAL_SUMMARY.md).

---

## 4. Context Sources

| Source | Provider | What it supplies | Module |
|---|---|---|---|
| Daily forecast | Open-Meteo (free, ~1km, 1–16 days) | Rain timing, peak/total rainfall | `wsp1_openmeteo.py` |
| Seasonal forecast | ECMWF SEAS5 via Copernicus CDS | Tercile probabilities, monthly rainfall category | inline in `wsp_unified_forecast.py` (`fetch_seasonal_forecast`) |
| Soil | iSDAsoil API (Africa, 30m resolution) | Organic carbon, N, pH, texture, risk flags | `wsp_soil_isda.py`, `wsp_soil_integration.py` |
| Farmer profile | User input / hardcoded defaults | Crop, scale, region | `wsp_unified_forecast.py` |

**Note:** `DAILY_FORECAST_WSP` and `SEASONAL_FORECAST_WSP` in `wsp_config.py` also list
`chirps`, `noaacpc`, `iri` as options — these prototype modules live in `other_wsp/`, not
the project root, so they won't import as-is. Only `openmeteo` (daily) and `ecmwf`
(seasonal) are wired up and runnable in this directory.

For ECMWF specifically: when used as the **seasonal** provider, `wsp_unified_forecast.py`
calls Copernicus CDS directly (its own inline `cdsapi` logic) rather than going through
`wsp3_ecmwf.py`. `wsp3_ecmwf.py` is only invoked if `DAILY_FORECAST_WSP = "ecmwf"`.

---

## 5. LLM Models

Two different models are used for two different jobs, both via the NaviGator API
(`wsp_config.py` → `get_llm()`):

- **Answer generation** (`UNIFIED_PROMPT`, `SIMPLE_PROMPT`): `gpt-5`
- **Crop/date extraction** (`extract_crop_from_question`, `extract_date_from_question`):
  `gpt-oss-120b` (cheaper, structured-output calls)

---

## 6. Setup

```bash
pip install -r requirements.txt
```

`.env` file required:
```
OPENAI_API_KEY=your-navigator-key
CLIENT_ID=your-client-id
CLIENT_SECRET=your-client-secret
ISDASOIL_USERNAME=your-isda-username     # for soil data
ISDASOIL_PASSWORD=your-isda-password
CDS_API_KEY=your-cds-api-key             # for ECMWF SEAS5 seasonal forecast
```
Optional: `USE_UTC_DATES=true` to anchor "today" to UTC instead of local system time
(see `get_today_datetime()` in `wsp_config.py`).

### Switching providers
```python
# wsp_config.py
DAILY_FORECAST_WSP = "openmeteo"   # tested option
SEASONAL_FORECAST_WSP = "ecmwf"    # tested option
```

---

## 7. File Structure

```
wsp_config.py              ← UNIFIED_PROMPT, LLM setup, crop/date extraction, provider config
wsp_unified_forecast.py    ← main orchestrator — RUN THIS for dual forecast + soil
simple_context_chatbot.py  ← minimal chatbot (location + crop + date only)
wsp1_openmeteo.py          ← daily forecast provider (Open-Meteo)
wsp3_ecmwf.py              ← ECMWF open-data + CDS seasonal fetchers
wsp_soil_isda.py           ← iSDAsoil API client, texture classification, risk interpretation
wsp_soil_integration.py    ← formats soil data into prompt-ready variables
other_wsp/                 ← parked prototypes (CHIRPS, NOAA CPC, IRI) — not wired into root
requirements.txt           ← dependencies (see file for per-provider install notes)
DOCS_DATE_POLICY.md        ← date-anchoring and provider-fetch logic
CROP_EXTRACTION_UPGRADE.md ← LLM-based crop detection design notes
LLM_EXTRACTION_FINAL_SUMMARY.md ← extraction system implementation summary
```

---

## 8. Quick Test

```bash
python wsp_unified_forecast.py
🌾 Your question: Are there organic alternatives to NPK fertilizer for my farm?
🌾 Which crop? Maize
```

Expect a 200–250 word answer with specific rates/timing/placement, no raw weather or soil
data cited, and a growth-stage inference framed agronomically (e.g., "late vegetative,
knee-high to pre-tasseling") rather than tied to a calendar date.
