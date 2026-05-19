"""Ex5 tools. Four tools the agent uses to research an Edinburgh booking.

Each tool:
  1. Reads its fixture from sample_data/ (DO NOT modify the fixtures).
  2. Logs its arguments and output into _TOOL_CALL_LOG (see integrity.py).
  3. Returns a ToolResult with success=True/False, output=dict, summary=str.

The grader checks for:
  * Correct parallel_safe flags (reads True, generate_flyer False).
  * Every tool's results appear in _TOOL_CALL_LOG.
  * Tools fail gracefully on missing fixtures or bad inputs (ToolError,
    not RuntimeError).
"""

from __future__ import annotations

import json
from pathlib import Path

from sovereign_agent.errors import ToolError
from sovereign_agent.session.directory import Session
from sovereign_agent.tools.registry import ToolRegistry, ToolResult, _RegisteredTool

from starter.edinburgh_research.integrity import _TOOL_CALL_LOG, record_tool_call

_SAMPLE_DATA = Path(__file__).parent / "sample_data"


# ---------------------------------------------------------------------------
# TODO 1 — venue_search
# ---------------------------------------------------------------------------
def venue_search(near: str, party_size: int, budget_max_gbp: int = 1000) -> ToolResult:
    """Search for Edinburgh venues near <near> that can seat the party.

    Reads sample_data/venues.json. Filters by:
      * open_now == True
      * area contains <near> (case-insensitive substring match)
      * seats_available_evening >= party_size
      * hire_fee_gbp + min_spend_gbp <= budget_max_gbp

    Returns a ToolResult with:
      output: {"near": ..., "party_size": ..., "results": [<venue dicts>], "count": int}
      summary: "venue_search(<near>, party=<N>): <count> result(s)"

    MUST call record_tool_call(...) before returning so the integrity
    check can see what data was produced.
    """
    # Spiral detection: LLMs sometimes loop on venue_search with varied args.
    search_count = sum(1 for r in _TOOL_CALL_LOG if r.tool_name == "venue_search")
    if search_count >= 3:
        return ToolResult(
            success=False,
            output={"error": "too_many_searches", "count": search_count},
            summary="STOP calling venue_search. Use the results you already have and proceed to get_weather, calculate_cost, and generate_flyer.",
        )

    data_file = _SAMPLE_DATA / "venues.json"
    if not data_file.exists():
        raise ToolError("SA_TOOL_DEPENDENCY_MISSING", "venues.json fixture not found")

    venues = json.loads(data_file.read_text(encoding="utf-8"))
    results = [
        v
        for v in venues
        if v["open_now"]
        and (near.lower() in v["area"].lower() or v["area"].lower() in near.lower())
        and v["seats_available_evening"] >= party_size
        and v["hire_fee_gbp"] + v["min_spend_gbp"] <= budget_max_gbp
    ]

    output = {"near": near, "party_size": party_size, "results": results, "count": len(results)}
    record_tool_call(
        "venue_search",
        {"near": near, "party_size": party_size, "budget_max_gbp": budget_max_gbp},
        output,
    )

    return ToolResult(
        success=True,
        output=output,
        summary=f"venue_search({near}, party={party_size}): {len(results)} result(s)",
    )


# ---------------------------------------------------------------------------
# TODO 2 — get_weather
# ---------------------------------------------------------------------------
def get_weather(city: str, date: str) -> ToolResult:
    """Look up the scripted weather for <city> on <date> (YYYY-MM-DD).

    Reads sample_data/weather.json. Returns:
      output: {"city": str, "date": str, "condition": str, "temperature_c": int, ...}
      summary: "get_weather(<city>, <date>): <condition>, <temp>C"

    If the city or date is not in the fixture, return success=False with
    a clear ToolError (SA_TOOL_INVALID_INPUT). Do NOT raise.

    MUST call record_tool_call(...) before returning.
    """
    data_file = _SAMPLE_DATA / "weather.json"
    if not data_file.exists():
        raise ToolError("SA_TOOL_DEPENDENCY_MISSING", "weather.json fixture not found")

    weather_data = json.loads(data_file.read_text(encoding="utf-8"))
    city_key = city.lower()
    city_data = weather_data.get(city_key)

    if city_data is None or date not in city_data:
        output = {"city": city, "date": date, "error": "not found"}
        record_tool_call("get_weather", {"city": city, "date": date}, output)
        return ToolResult(
            success=False,
            output=output,
            summary=f"get_weather({city}, {date}): not found",
            error=ToolError("SA_TOOL_INVALID_INPUT", f"no weather data for {city} on {date}"),
        )

    day = city_data[date]
    output = {"city": city, "date": date, **day}
    record_tool_call("get_weather", {"city": city, "date": date}, output)

    return ToolResult(
        success=True,
        output=output,
        summary=f"get_weather({city}, {date}): {day['condition']}, {day['temperature_c']}C",
    )


# ---------------------------------------------------------------------------
# TODO 3 — calculate_cost
# ---------------------------------------------------------------------------
def calculate_cost(
    venue_id: str,
    party_size: int,
    duration_hours: int,
    catering_tier: str = "bar_snacks",
) -> ToolResult:
    """Compute the total cost for a booking.

    Formula:
      base_per_head = base_rates_gbp_per_head[catering_tier]
      venue_mult    = venue_modifiers[venue_id]
      subtotal      = base_per_head * venue_mult * party_size * max(1, duration_hours)
      service       = subtotal * service_charge_percent / 100
      total         = subtotal + service + <venue's hire_fee_gbp + min_spend_gbp>
      deposit_rule  = per deposit_policy thresholds

    Returns:
      output: {
        "venue_id": str,
        "party_size": int,
        "duration_hours": int,
        "catering_tier": str,
        "subtotal_gbp": int,
        "service_gbp": int,
        "total_gbp": int,
        "deposit_required_gbp": int,
      }
      summary: "calculate_cost(<venue>, <party>): total £<N>, deposit £<M>"

    MUST call record_tool_call(...) before returning.
    """
    catering_file = _SAMPLE_DATA / "catering.json"
    venues_file = _SAMPLE_DATA / "venues.json"

    if not catering_file.exists():
        raise ToolError("SA_TOOL_DEPENDENCY_MISSING", "catering.json fixture not found")
    if not venues_file.exists():
        raise ToolError("SA_TOOL_DEPENDENCY_MISSING", "venues.json fixture not found")

    catering = json.loads(catering_file.read_text(encoding="utf-8"))
    venues = json.loads(venues_file.read_text(encoding="utf-8"))

    venue = next((v for v in venues if v["id"] == venue_id), None)
    if venue is None:
        return ToolResult(
            success=False,
            output={"venue_id": venue_id, "error": "venue not found"},
            summary=f"calculate_cost({venue_id}): venue not found",
            error=ToolError("SA_TOOL_INVALID_INPUT", f"unknown venue_id: {venue_id}"),
        )

    if catering_tier not in catering["base_rates_gbp_per_head"]:
        return ToolResult(
            success=False,
            output={"catering_tier": catering_tier, "error": "unknown tier"},
            summary=f"calculate_cost: unknown catering_tier {catering_tier}",
            error=ToolError("SA_TOOL_INVALID_INPUT", f"unknown catering_tier: {catering_tier}"),
        )

    base_per_head = catering["base_rates_gbp_per_head"][catering_tier]
    venue_mult = catering["venue_modifiers"].get(venue_id, 1.0)
    subtotal = int(base_per_head * venue_mult * party_size * max(1, duration_hours))
    service = int(subtotal * catering["service_charge_percent"] / 100)
    total = subtotal + service + venue["hire_fee_gbp"] + venue["min_spend_gbp"]

    if total < 300:
        deposit = 0
    elif total <= 1000:
        deposit = int(total * 0.20)
    else:
        deposit = int(total * 0.30)

    output = {
        "venue_id": venue_id,
        "party_size": party_size,
        "duration_hours": duration_hours,
        "catering_tier": catering_tier,
        "subtotal_gbp": subtotal,
        "service_gbp": service,
        "total_gbp": total,
        "deposit_required_gbp": deposit,
    }
    record_tool_call(
        "calculate_cost",
        {
            "venue_id": venue_id,
            "party_size": party_size,
            "duration_hours": duration_hours,
            "catering_tier": catering_tier,
        },
        output,
    )

    return ToolResult(
        success=True,
        output=output,
        summary=f"calculate_cost({venue_id}, {party_size}): total £{total}, deposit £{deposit}",
    )


# ---------------------------------------------------------------------------
# TODO 4 — generate_flyer
# ---------------------------------------------------------------------------
def generate_flyer(session: Session, event_details: dict) -> ToolResult:
    """Produce an HTML flyer and write it to workspace/flyer.html.

    event_details is expected to contain at least:
      venue_name, venue_address, date, time, party_size, condition,
      temperature_c, total_gbp, deposit_required_gbp

    Write a self-contained HTML flyer (inline CSS, no external assets). Tag every key fact with data-testid="<n>" so the integrity check can parse it.

    Write a formatted HTML flyer with an H1 title, the event
    facts, a weather summary, and the cost breakdown.

    Returns:
      output: {"path": "workspace/flyer.html", "bytes_written": int}
      summary: "generate_flyer: wrote <path> (<N> chars)"

    MUST call record_tool_call(...) before returning — the integrity
    check compares the flyer's contents against earlier tool outputs.

    IMPORTANT: this tool MUST be registered with parallel_safe=False
    because it writes a file.
    """
    workspace = session.workspace_dir
    workspace.mkdir(parents=True, exist_ok=True)
    flyer_path = workspace / "flyer.html"

    d = event_details
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Edinburgh Pub Event</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 620px; margin: 40px auto; padding: 24px; border: 2px solid #333; border-radius: 10px; background: #fafafa; }}
  h1 {{ color: #2c3e50; margin-bottom: 4px; }}
  h2 {{ color: #555; font-size: 1em; margin-top: 20px; }}
  dl {{ display: grid; grid-template-columns: 160px 1fr; gap: 6px 12px; margin: 0; }}
  dt {{ font-weight: bold; color: #444; }}
  dd {{ margin: 0; }}
</style>
</head>
<body>
<h1>Edinburgh Pub Event</h1>
<h2>Venue</h2>
<dl>
  <dt>Name</dt><dd data-testid="venue_name">{d.get("venue_name", "")}</dd>
  <dt>Address</dt><dd data-testid="venue_address">{d.get("venue_address", "")}</dd>
  <dt>Date</dt><dd data-testid="date">{d.get("date", "")}</dd>
  <dt>Time</dt><dd data-testid="time">{d.get("time", "")}</dd>
  <dt>Party size</dt><dd data-testid="party_size">{d.get("party_size", "")}</dd>
</dl>
<h2>Weather</h2>
<dl>
  <dt>Condition</dt><dd data-testid="condition">{d.get("condition", "")}</dd>
  <dt>Temperature</dt><dd data-testid="temperature_c">{d.get("temperature_c", "")}°C</dd>
</dl>
<h2>Cost</h2>
<dl>
  <dt>Total</dt><dd data-testid="total_gbp">£{d.get("total_gbp", "")}</dd>
  <dt>Deposit required</dt><dd data-testid="deposit_required_gbp">£{d.get("deposit_required_gbp", "")}</dd>
</dl>
</body>
</html>"""

    flyer_path.write_text(html, encoding="utf-8")
    bytes_written = len(html)

    output = {"path": "workspace/flyer.html", "bytes_written": bytes_written}
    record_tool_call("generate_flyer", {"event_details": event_details}, output)

    return ToolResult(
        success=True,
        output=output,
        summary=f"generate_flyer: wrote workspace/flyer.html ({bytes_written} chars)",
    )


# ---------------------------------------------------------------------------
# Registry builder — DO NOT MODIFY the name, signature, or registration calls.
# The grader imports and calls this to pick up your tools.
# ---------------------------------------------------------------------------
def build_tool_registry(session: Session) -> ToolRegistry:
    """Build a session-scoped tool registry with all four Ex5 tools plus
    the sovereign-agent builtins (read_file, write_file, list_files,
    handoff_to_structured, complete_task).

    DO NOT change the tool names — the tests and grader call them by name.
    """
    from sovereign_agent.tools.builtin import make_builtin_registry

    reg = make_builtin_registry(session)

    # venue_search
    reg.register(
        _RegisteredTool(
            name="venue_search",
            description="Search Edinburgh venues by area, party size, and max budget.",
            fn=venue_search,
            parameters_schema={
                "type": "object",
                "properties": {
                    "near": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "budget_max_gbp": {"type": "integer", "default": 1000},
                },
                "required": ["near", "party_size"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"near": "Haymarket", "party_size": 6, "budget_max_gbp": 800},
                    "output": {"count": 1, "results": [{"id": "haymarket_tap"}]},
                }
            ],
        )
    )

    # get_weather
    reg.register(
        _RegisteredTool(
            name="get_weather",
            description="Get scripted weather for a city on a YYYY-MM-DD date.",
            fn=get_weather,
            parameters_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["city", "date"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"city": "Edinburgh", "date": "2026-04-25"},
                    "output": {"condition": "cloudy", "temperature_c": 12},
                }
            ],
        )
    )

    # calculate_cost
    reg.register(
        _RegisteredTool(
            name="calculate_cost",
            description="Compute total cost and deposit for a booking.",
            fn=calculate_cost,
            parameters_schema={
                "type": "object",
                "properties": {
                    "venue_id": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "duration_hours": {"type": "integer"},
                    "catering_tier": {
                        "type": "string",
                        "enum": ["drinks_only", "bar_snacks", "sit_down_meal", "three_course_meal"],
                        "default": "bar_snacks",
                    },
                },
                "required": ["venue_id", "party_size", "duration_hours"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # pure compute, no shared state
            examples=[
                {
                    "input": {
                        "venue_id": "haymarket_tap",
                        "party_size": 6,
                        "duration_hours": 3,
                    },
                    "output": {"total_gbp": 540, "deposit_required_gbp": 0},
                }
            ],
        )
    )

    # generate_flyer — parallel_safe=False because it writes a file
    def _flyer_adapter(event_details: dict) -> ToolResult:
        return generate_flyer(session, event_details)

    reg.register(
        _RegisteredTool(
            name="generate_flyer",
            description="Write an HTML flyer for the event to workspace/flyer.html.",
            fn=_flyer_adapter,
            parameters_schema={
                "type": "object",
                "properties": {"event_details": {"type": "object"}},
                "required": ["event_details"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=False,  # writes a file — MUST be False
            examples=[
                {
                    "input": {
                        "event_details": {
                            "venue_name": "Haymarket Tap",
                            "date": "2026-04-25",
                            "party_size": 6,
                        }
                    },
                    "output": {"path": "workspace/flyer.html"},
                }
            ],
        )
    )

    return reg


__all__ = [
    "build_tool_registry",
    "venue_search",
    "get_weather",
    "calculate_cost",
    "generate_flyer",
]
