Date anchoring & provider usage (short)
=====================================

Purpose
-------
Explains how the system decides whether to fetch and include provider weather data in the LLM prompt depending on the resolved context date.

When context date == TODAY
--------------------------
- The extractor returns a `context_date` equal to today's date (default or explicit).
- The system will fetch daily and seasonal forecasts (where available) and soil data.
- The provided `start_date` (== today) is forwarded to providers when supported.
- The LLM prompt includes a `daily_weather_section` and weather summary keys.
- Provenance keys added to the prompt (only when providers are used):
  - `daily_requested_start_date`, `daily_fetched_start_date`, `daily_fetched_end_date`, `daily_start_date_honored`, `daily_provider_used`
  - `seasonal_requested_start_date`, `seasonal_fetched_start_date`, `seasonal_fetched_end_date`, `seasonal_start_date_honored`, `seasonal_provider_used`
  - Weather summary keys: `has_rain`, `num_rainy_days`, `next_rainy_day`, `peak_rain_day`, `peak_rain_mm`, `total_rain_mm`

When context date != TODAY
--------------------------
- The resolved `context_date` is a scenario date (past or future) different from today.
- Provider weather fetches (daily/seasonal) are skipped to avoid giving the LLM live weather numbers that don't match the scenario./
- Soil data is still fetched and used.
- The `daily_weather_section` is provided to the prompt as an empty string and `seasonal_category` is cleared to avoid implying seasonal data.
- Provider provenance and weather summary keys are not sent to the LLM (or are sent with `provider_used=False`).

Why this rule?
---------------
To avoid misleading answers: when a user asks about a non-today scenario (e.g., "middle of June"), we do not expose live provider forecasts to the LLM because those provider numbers are anchored to the provider's own retrieval dates and could cause incorrect, time-mismatched reasoning.

Overrides & operator controls
-----------------------------
- Force a date programmatically: pass `forced_context_date='YYYY-MM-DD'` to `answer_with_dual_forecast()`.
- Toggle how "today" is computed: set the environment variable `USE_UTC_DATES=1` to force UTC-based `today` (default is local system date).

Quick test snippets
-------------------
Run these in the repo venv to check behavior:
 
1) No explicit date (should use providers):

```bash
source venv/bin/activate
python3 - <<'PY'
from wsp_config import extract_crop_and_date_json, get_today_str
from wsp_unified_forecast import answer_with_dual_forecast
print('today anchor:', get_today_str())
q = 'My peanut field in Peanut Basin, Senegal. For this season, how much yield can I expect?'
ex = extract_crop_and_date_json(q)
print('extraction:', ex)
ans = answer_with_dual_forecast(q, {'crop':'Peanut','region':'Peanut Basin'}, 14.5, -16.0, forced_context_date=ex['context_date'])
print('answer length:', len(ans))
PY
```

2) Explicit non-today (should skip providers):

```bash
source venv/bin/activate
python3 - <<'PY'
from wsp_config import extract_crop_and_date_json
from wsp_unified_forecast import answer_with_dual_forecast
q = 'It is the middle of June and my peanut field is infested. How much yield can I expect?'
ex = extract_crop_and_date_json(q)
print('extraction:', ex)
ans = answer_with_dual_forecast(q, {'crop':'Peanut','region':'Peanut Basin'}, 14.5, -16.0, forced_context_date=ex['context_date'])
print('answer length:', len(ans))
PY
```
