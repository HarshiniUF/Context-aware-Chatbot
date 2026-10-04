"""
=============================================================
TOOL AGENT — the LLM decides which tools to call
=============================================================

Flow:  question → LLM (3 tools bound) → LLM calls 0..n tools
       → tool results fed back → LLM answers

Tools come from agent_tools.py (resolve_location, get_weather_forecast,
get_soil_profile), in one of two ways:
  local mode (default): called directly as LangChain tools
  --mcp mode          : called through mcp_server.py over stdio (real MCP)

System prompt = SKILL.md (Contextual GATE skill, used for every question)
               + optional tool-use instructions (--rules FILE)
               + today's date and the default farm location.
Compare runs with and without --rules to see the effect of the instructions.
The old "fetch everything, then UNIFIED_PROMPT" pipeline in
wsp_unified_forecast.py is untouched; --compare runs it side by side.

Usage:
  python tool_agent.py                         # interactive chat
  python tool_agent.py -q "Should I spray tomorrow?"
  python tool_agent.py --test                  # run the test question set
  python tool_agent.py --test --compare        # ... and the old pipeline, for comparison
  python tool_agent.py --test --mcp            # tools via the MCP server
  python tool_agent.py --rules tool_rules.md   # SKILL.md + tool-use instructions
  python tool_agent.py --skill OTHER.md        # use another skill file instead of SKILL.md
  python tool_agent.py --no-default-location   # don't tell the LLM about the default farm
  python tool_agent.py --no-confirm            # skip the location + crop confirmation

When the LLM calls resolve_location (chat and -q modes), the farmer confirms
the location and the crop before the LLM continues. Questions that need no
location lookup are answered without any confirmation. --test never asks.

--test writes a Markdown report to test_results/ (questions, tool calls with
inputs, answers, and old-pipeline answers when --compare is used).
=============================================================
"""

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from agent_tools import TOOL_DESCRIPTIONS, TOOL_FUNCTIONS
from wsp_config import (
    get_llm, _extract_crop_fallback,
    DEFAULT_LATITUDE, DEFAULT_LONGITUDE, DEFAULT_LOCATION_NAME, DEFAULT_TIMEZONE,
)

MAX_TOOL_ROUNDS = 6
QUIT_WORDS = ("quit", "exit", "q")
RESULTS_DIR = "test_results"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SKILL_FILE = os.path.join(PROJECT_DIR, "SKILL.md")

TEST_QUESTIONS = [
    ("no tools",              "What is the average maize yield in Kenya?"),
    ("weather",               "Should I spray my maize tomorrow?"),
    ("soil",                  "How much lime should I add to my field?"),
    ("weather + soil",        "Should I top-dress urea on my maize this week?"),
    ("location",              "I farm near Nairobi. When should I plant beans?"),
    ("coarse location + soil", "I grow groundnut in Senegal. Is the soil good for it?"),
    ("past date",             "How much rain fell in the middle of June on my farm?"),
]


# ─────────────────────────────────────────────────────────────
# TOOLBOXES — same interface for local and MCP tools
#   .specs          → what bind_tools() receives
#   await .call()   → dict result for one tool call
# ─────────────────────────────────────────────────────────────
class LocalToolbox:
    """Calls the agent_tools functions directly (validated by their signatures)."""

    def __init__(self):
        self.tools = {
            name: StructuredTool.from_function(fn, name=name, description=TOOL_DESCRIPTIONS[name])
            for name, fn in TOOL_FUNCTIONS.items()
        }
        self.specs = list(self.tools.values())

    async def call(self, name: str, args: dict) -> dict:
        tool = self.tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"Unknown tool '{name}'"}
        try:
            # tools do blocking HTTP; keep the event loop free
            return await asyncio.to_thread(tool.invoke, args)
        except Exception as e:  # invalid arguments from the LLM, network errors, ...
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class MCPToolbox:
    """Starts mcp_server.py over stdio and calls its tools through an MCP client."""

    def __init__(self, client):
        self.client = client
        self.specs = []

    @classmethod
    @contextlib.asynccontextmanager
    async def connect(cls):
        from mcp.client import Client
        from mcp.client.stdio import StdioServerParameters

        params = StdioServerParameters(command=sys.executable,
                                       args=[os.path.join(PROJECT_DIR, "mcp_server.py")],
                                       cwd=PROJECT_DIR)
        async with Client(params) as client:
            box = cls(client)
            for t in (await client.list_tools()).tools:
                box.specs.append({"type": "function", "function": {
                    "name": t.name, "description": t.description or "", "parameters": t.input_schema}})
            yield box

    async def call(self, name: str, args: dict) -> dict:
        try:
            r = await self.client.call_tool(name, args)
        except Exception as e:
            return {"ok": False, "error": f"MCP call failed: {type(e).__name__}: {e}"}
        if r.is_error:
            text = r.content[0].text if r.content else "unknown error"
            return {"ok": False, "error": text}
        if r.structured_content is not None:
            data = r.structured_content
            # tools returning dict come back either as the dict or wrapped as {"result": dict}
            return data["result"] if set(data) == {"result"} else data
        return json.loads(r.content[0].text)


# ─────────────────────────────────────────────────────────────
# SYSTEM PROMPT (minimal — tool-selection rules come later)
# ─────────────────────────────────────────────────────────────
def _read_markdown(path: str) -> str:
    """File contents without a leading YAML front-matter block (--- ... ---)."""
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:].strip()
    return text


def build_system_prompt(skill_file: str = DEFAULT_SKILL_FILE, rules_file: Optional[str] = None,
                        use_default_location: bool = True) -> str:
    """
    SKILL.md (how to reason) + optional tool-use instructions + runtime facts.
    The opening lines are the same with or without --rules, so the only
    difference between the two runs is the instructions themselves.
    """
    parts = [
        "You are AU, an agronomy advisor answering a farmer's question. Apply the Contextual GATE "
        "skill below to every question. You have tools for location lookup, weather and soil data.",
        _read_markdown(skill_file),
    ]
    if rules_file:
        parts.append("# Tool-Use Instructions\n\n" + _read_markdown(rules_file))

    # "Today" is the farm's local date, not the computer's: in the evening in the US it is
    # already the next day in Kenya, and the weather tool returns local dates at the location.
    farm_now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    facts = [f"Today's date at the farm ({DEFAULT_TIMEZONE}): {farm_now:%Y-%m-%d} ({farm_now:%A}), "
             f"local time {farm_now:%H:%M}.",
             "Weather tool dates are local calendar days at the requested location, each with its "
             "weekday; use those dates and weekdays exactly as returned. For a location in another "
             "timezone, its 'today' is the first day of a forecast fetched without start_date."]
    if use_default_location:
        facts.append(f"The farmer's farm is at {DEFAULT_LOCATION_NAME} "
                     f"(lat {DEFAULT_LATITUDE}, lon {DEFAULT_LONGITUDE}, timezone {DEFAULT_TIMEZONE}) "
                     "unless they name another location.")
    parts.append("# Session Facts\n\n" + "\n".join(facts))
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────
# FARMER CONFIRMATION — only when the LLM calls resolve_location:
# the farmer confirms (or corrects) the location AND the crop.
# Questions that need no location lookup are never interrupted.
# ─────────────────────────────────────────────────────────────
class FarmerConfirmation:
    """Terminal confirmation of location + crop for one question."""

    def __init__(self, question: str):
        self.question = question
        self.crop_done = False
        self.crop: Optional[str] = None
        self.wait_seconds = 0.0  # time spent waiting for the farmer (excluded from timings)

    async def _input(self, prompt: str) -> str:
        start = time.time()
        reply = (await asyncio.to_thread(input, prompt)).strip()
        self.wait_seconds += time.time() - start
        return reply

    @staticmethod
    def _pick(result: dict, candidate: dict) -> dict:
        return {**result, **candidate, "ambiguous": False, "candidates": [], "match": "exact"}

    async def review_location(self, args: dict, result: dict, toolbox) -> dict:
        """Show the looked-up location; let the farmer confirm, pick a candidate, or type another place."""
        queried = args.get("place") or f"{args.get('latitude')}, {args.get('longitude')}"
        corrected = False
        while True:
            print(f"\n   📍 Location check — Claude looked up \"{queried}\":")
            if result.get("found"):
                candidates = result.get("candidates") or []
                if (result.get("ambiguous") or result.get("match") == "approximate") and candidates:
                    print("      No exact match. Closest places:" if result.get("match") == "approximate"
                          else f"      {len(candidates)} places match:")
                    for i, c in enumerate(candidates, 1):
                        print(f"        {i}. {c['name']}  ({c['latitude']:.4f}, {c['longitude']:.4f}) | {c['precision']}")
                    reply = await self._input("      Pick a number (Enter = 1), or type another place: ")
                    if not reply:
                        result = self._pick(result, candidates[0])
                        break
                    if reply.isdigit() and 1 <= int(reply) <= len(candidates):
                        result = self._pick(result, candidates[int(reply) - 1])
                        break
                else:
                    print(f"      → {result['name']}  ({result['latitude']:.4f}, {result['longitude']:.4f}) "
                          f"| {result['precision']}")
                    reply = await self._input("      Press Enter to confirm, or type another place: ")
                    if not reply:
                        break
            else:
                print(f"      ⚠️  {result.get('error')}")
                reply = await self._input("      Type a place to look up, or press Enter to continue without one: ")
                if not reply:
                    return result
            # farmer typed another place → look it up and confirm again
            queried, corrected = reply, True
            result = await toolbox.call("resolve_location", {"place": reply})

        await self._review_crop()
        result = {**result, "confirmed_by_farmer": True,
                  "farmer_crop": self.crop or "not specified",
                  "note": ("The farmer corrected the location. " if corrected else "") +
                          "Use these confirmed coordinates for every weather or soil tool call."}
        print(f"      ✅ Using: {result['name']} ({result['latitude']:.4f}, {result['longitude']:.4f})"
              f" | crop: {self.crop or 'not specified'}")
        return result

    async def _review_crop(self) -> None:
        """Confirm the crop once per question (detected from the question with the keyword matcher)."""
        if self.crop_done:
            return
        self.crop_done = True
        detected = _extract_crop_fallback(self.question)
        if detected:
            reply = await self._input(f"   🌱 Crop: {detected} (from your question) — Enter to confirm, or type the crop: ")
        else:
            reply = await self._input("   🌱 Crop: not mentioned — type the crop (Enter to skip): ")
        if reply:
            self.crop = _extract_crop_fallback(reply) or reply.strip().capitalize()
        else:
            self.crop = detected


# ─────────────────────────────────────────────────────────────
# AGENT LOOP
# ─────────────────────────────────────────────────────────────
def _short(result: dict) -> str:
    """One-line summary of a tool result for the trace."""
    if result.get("ok") is False or result.get("found") is False:
        return f"FAILED: {str(result.get('error'))[:200]}"
    if "found" in result:
        return (f"{result['name']} ({result['latitude']}, {result['longitude']}), "
                f"precision={result['precision']}, ambiguous={result['ambiguous']}")
    if "period" in result:
        p = result["period"]
        return f"{p['days']} days {p['start_date']} → {p['end_date']}, vars={result['variables']}"
    if "depths_cm" in result:
        return f"depths={result['depths_cm']}, properties={list(result.get('properties', {}))}"
    return "ok"


def _coords_differ(args: dict, location: dict, tolerance_deg: float = 0.05) -> bool:
    """True if a tool call's coordinates are more than ~5 km from a confirmed location."""
    if "latitude" not in args or "longitude" not in args:
        return False
    return (abs(args["latitude"] - location["latitude"]) > tolerance_deg or
            abs(args["longitude"] - location["longitude"]) > tolerance_deg)


async def run_agent(question: str, system_prompt: str, toolbox, llm=None, verbose: bool = True,
                    confirmation: Optional[FarmerConfirmation] = None) -> dict:
    """
    Run one question through the tool-calling loop.
    With `confirmation`, every resolve_location result is confirmed by the farmer
    (location + crop) before the LLM sees it.
    Returns {"answer": str, "tool_calls": [{"name", "args", "result"}], "rounds": int}.
    """
    base_llm = llm or get_llm()
    llm_with_tools = base_llm.bind_tools(toolbox.specs)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=question)]
    trace = []

    for round_no in range(1, MAX_TOOL_ROUNDS + 1):
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)
        if not response.tool_calls:
            return {"answer": response.content.strip(), "tool_calls": trace, "rounds": round_no}

        def show(call, result):
            if verbose:
                print(f"   🔧 {call['name']}({json.dumps(call['args'])})")
                print(f"      → {_short(result)}")

        # location lookups first, one at a time, so the farmer can confirm each one
        results = {}
        for call in response.tool_calls:
            if call["name"] == "resolve_location":
                result = await toolbox.call(call["name"], call["args"])
                show(call, result)
                if confirmation:
                    result = await confirmation.review_location(call["args"], result, toolbox)
                results[call["id"]] = result
        # weather/soil calls made in the same turn used coordinates the LLM guessed before the
        # location was confirmed; if they point elsewhere, don't run them — ask for a re-call
        confirmed = [r for r in results.values() if r.get("confirmed_by_farmer")]
        others = []
        for call in (c for c in response.tool_calls if c["id"] not in results):
            far = confirmed and all(_coords_differ(call["args"], loc) for loc in confirmed)
            if far:
                loc = confirmed[-1]
                results[call["id"]] = {"ok": False, "error": (
                    f"Not run: the farmer confirmed the location {loc['name']} "
                    f"(lat {loc['latitude']}, lon {loc['longitude']}). Call again with these coordinates.")}
                show(call, results[call["id"]])
            else:
                others.append(call)
        # the remaining tool calls in this turn are independent → run them in parallel
        for call, result in zip(others, await asyncio.gather(*(toolbox.call(c["name"], c["args"]) for c in others))):
            show(call, result)
            results[call["id"]] = result

        for call in response.tool_calls:
            result = results[call["id"]]
            trace.append({"name": call["name"], "args": call["args"], "result": result})
            messages.append(ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"]))

    # Out of rounds: force a final answer without more tool calls
    messages.append(HumanMessage(content="Answer now using the information you already have."))
    response = await base_llm.bind_tools(toolbox.specs, tool_choice="none").ainvoke(messages)
    return {"answer": response.content.strip(), "tool_calls": trace, "rounds": MAX_TOOL_ROUNDS}


# ─────────────────────────────────────────────────────────────
# OLD PIPELINE (for --compare): fetch everything → UNIFIED_PROMPT
# ─────────────────────────────────────────────────────────────
def run_old_pipeline(question: str) -> str:
    """Non-interactive version of wsp_unified_forecast.run_chatbot for one question."""
    from location_resolver import resolve_location
    from wsp_config import DEFAULT_FARM_SCALE_HA, extract_crop_and_date_json, extract_location_from_question
    from wsp_unified_forecast import answer_with_dual_forecast

    extraction = extract_crop_and_date_json(question)
    lat, lon, region = DEFAULT_LATITUDE, DEFAULT_LONGITUDE, DEFAULT_LOCATION_NAME
    place = extract_location_from_question(question)
    if place:
        loc = resolve_location(place)
        if loc["found"]:  # no user to ask here: take the best match
            lat, lon, region = loc["latitude"], loc["longitude"], loc["name"]
    farmer_context = {"crop": extraction["extracted_crop"] or "unspecified", "region": region,
                      "latitude": lat, "longitude": lon, "scale_ha": DEFAULT_FARM_SCALE_HA}
    # the old pipeline prints progress, and cdsapi/cfgrib log through `logging`;
    # silence both so the comparison output stays readable
    logging.disable(logging.WARNING)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return answer_with_dual_forecast(question, farmer_context, lat, lon,
                                             seasonal_forecast_days=100,
                                             forced_context_date=extraction["context_date"])
    finally:
        logging.disable(logging.NOTSET)


def _in_daemon_thread(fn, *args) -> asyncio.Future:
    """
    Run a blocking function in a daemon thread. Unlike asyncio.to_thread, a daemon
    thread doesn't keep the program alive after Ctrl+C (the old pipeline can take a minute).
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def settle(setter, value):
        if not future.done():
            setter(value)

    def worker():
        try:
            result, setter = fn(*args), future.set_result
        except BaseException as e:
            result, setter = e, future.set_exception
        try:
            loop.call_soon_threadsafe(settle, setter, result)
        except RuntimeError:  # event loop already closed (user quit)
            pass

    threading.Thread(target=worker, daemon=True).start()
    return future


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
async def ask(question: str, system_prompt: str, toolbox, compare: bool = False, confirm: bool = False) -> dict:
    print(f"\n❓ {question}")
    record = {"question": question, "tool_calls": [], "answer": None, "error": None,
              "seconds": None, "old_answer": None}
    confirmation = FarmerConfirmation(question) if confirm else None
    start = time.time()
    try:
        out = await run_agent(question, system_prompt, toolbox, confirmation=confirmation)
        record.update(answer=out["answer"], tool_calls=out["tool_calls"])
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"
    waited = confirmation.wait_seconds if confirmation else 0.0
    record["seconds"] = round(time.time() - start - waited, 1)

    if record["error"]:
        print(f"⚠️  Could not generate an answer: {record['error']}")
    else:
        called = [c["name"] for c in record["tool_calls"]] or ["(no tools)"]
        print(f"   🧰 Tools used: {', '.join(called)}   ({record['seconds']} s)")
        print("─" * 70)
        print(record["answer"])
        print("─" * 70)

    if compare:
        print("   ⏳ Old pipeline (fetch everything → UNIFIED_PROMPT; the ECMWF seasonal download "
              "can take ~1 min)...")
        try:
            record["old_answer"] = await _in_daemon_thread(run_old_pipeline, question)
        except Exception as e:
            record["old_answer"] = f"⚠️ Old pipeline failed: {type(e).__name__}: {e}"
        print("   📜 OLD PIPELINE ANSWER:")
        print(record["old_answer"])
        print("─" * 70)
    return record


def write_report(records: list, labels: list, mode: str, system_prompt: str, prompt_label: str) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"tool_agent_{datetime.now():%Y%m%d_%H%M%S}.md")
    lines = [f"# Tool agent test run — {datetime.now():%Y-%m-%d %H:%M}", "",
             f"- Tool mode: {mode}", f"- Model: {get_llm().model_name}",
             f"- Prompt: {prompt_label}", "",
             "## Summary", "", "| # | Type | Question | Tools called | Time |", "|---|---|---|---|---|"]
    for i, (label, r) in enumerate(zip(labels, records), 1):
        tools = ", ".join(c["name"] for c in r["tool_calls"]) or ("ERROR" if r["error"] else "none")
        lines.append(f"| {i} | {label} | {r['question']} | {tools} | {r['seconds']} s |")
    lines += ["", "## System prompt", "", "```", system_prompt, "```"]
    for i, (label, r) in enumerate(zip(labels, records), 1):
        lines += ["", f"## {i}. {r['question']}", "", f"*Expected: {label}*", "", "**Tool calls:**", ""]
        if r["tool_calls"]:
            for c in r["tool_calls"]:
                lines.append(f"- `{c['name']}({json.dumps(c['args'])})` → {_short(c['result'])}")
        else:
            lines.append("- none")
        lines += ["", "**Answer (tool agent):**", "", r["error"] and f"⚠️ {r['error']}" or r["answer"]]
        if r["old_answer"] is not None:
            lines += ["", "**Answer (old pipeline):**", "", r["old_answer"]]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


async def main_async(args) -> None:
    system_prompt = build_system_prompt(args.skill, args.rules, not args.no_default_location)
    prompt_label = os.path.basename(args.skill) + (f" + {os.path.basename(args.rules)}" if args.rules
                                                   else " (no tool-use instructions)")
    mode = "MCP (mcp_server.py over stdio)" if args.mcp else "local (LangChain tools)"

    async with (MCPToolbox.connect() if args.mcp else contextlib.nullcontext(LocalToolbox())) as toolbox:
        print(f"Tool mode: {mode} — tools: {', '.join(s['function']['name'] if isinstance(s, dict) else s.name for s in toolbox.specs)}")
        print(f"Prompt   : {prompt_label}")
        if args.question:
            await ask(args.question, system_prompt, toolbox, args.compare, confirm=not args.no_confirm)
        elif args.test:
            labels, records = [], []
            try:
                for label, q in TEST_QUESTIONS:
                    records.append(await ask(q, system_prompt, toolbox, args.compare))
                    labels.append(label)
            except (asyncio.CancelledError, KeyboardInterrupt):
                print(f"\n⏹️  Stopped after {len(records)} of {len(TEST_QUESTIONS)} questions.")
            if records:
                print(f"\n📄 Report saved: {write_report(records, labels, mode, system_prompt, prompt_label)}")
        else:
            print("Tool agent — the LLM decides which tools to call. Type 'quit' to exit.")
            while True:
                question = (await asyncio.to_thread(input, "\n🌾 You: ")).strip()
                if question.lower() in QUIT_WORDS:
                    break
                if question:
                    await ask(question, system_prompt, toolbox, args.compare, confirm=not args.no_confirm)


def main():
    parser = argparse.ArgumentParser(description="LLM-driven tool selection agent")
    parser.add_argument("-q", "--question", help="Ask one question and exit")
    parser.add_argument("--test", action="store_true", help="Run the built-in test questions and save a report")
    parser.add_argument("--compare", action="store_true", help="Also answer with the old pipeline")
    parser.add_argument("--mcp", action="store_true", help="Call tools through the MCP server (stdio)")
    parser.add_argument("--skill", default=DEFAULT_SKILL_FILE,
                        help="Skill file used as the base system prompt (default: SKILL.md)")
    parser.add_argument("--rules", help="Tool-use instructions file appended after the skill")
    parser.add_argument("--no-confirm", action="store_true",
                        help="Don't ask the farmer to confirm location/crop (--test never asks)")
    parser.add_argument("--no-default-location", action="store_true",
                        help="Don't tell the LLM where the default farm is")
    args = parser.parse_args()
    for path in filter(None, (args.skill, args.rules)):
        if not os.path.isfile(path):
            parser.error(f"file not found: {path}")
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nGoodbye! 🌾")


if __name__ == "__main__":
    main()
