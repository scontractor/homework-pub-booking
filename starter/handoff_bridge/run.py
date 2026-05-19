"""Ex7 — reference solution runner. Scripts a two-round round-trip:
round 1: loop picks haymarket_tap (8 seats), structured rejects (party=12 > cap=8)
round 2: loop picks royal_oak (16 seats), structured accepts."""

from __future__ import annotations

import asyncio
import json
import sys

from sovereign_agent._internal.llm_client import (
    FakeLLMClient,
    ScriptedResponse,
    ToolCall,
)
from sovereign_agent._internal.paths import example_sessions_dir
from sovereign_agent.executor import DefaultExecutor
from sovereign_agent.halves.loop import LoopHalf
from sovereign_agent.planner import DefaultPlanner
from sovereign_agent.session.directory import create_session

from starter.edinburgh_research.tools import build_tool_registry
from starter.handoff_bridge.bridge import HandoffBridge
from starter.rasa_half.structured_half import RasaStructuredHalf, spawn_mock_rasa


def _build_fake_client_two_rounds() -> FakeLLMClient:
    """Round 1: plan → venue_search → handoff_to_structured (haymarket_tap)
    Round 2: plan → venue_search → handoff_to_structured (royal_oak)"""
    plan_r1 = json.dumps(
        [
            {
                "id": "sg_1",
                "description": "find venue near haymarket for 12",
                "success_criterion": "candidate identified",
                "estimated_tool_calls": 2,
                "depends_on": [],
                "assigned_half": "loop",
            }
        ]
    )
    # round 2 — loop gets rejection reason, retries with different area
    plan_r2 = json.dumps(
        [
            {
                "id": "sg_1",
                "description": "retry with larger venue after rejection",
                "success_criterion": "different venue with enough seats",
                "estimated_tool_calls": 2,
                "depends_on": [],
                "assigned_half": "loop",
            }
        ]
    )

    return FakeLLMClient(
        [
            # === ROUND 1 ===
            ScriptedResponse(content=plan_r1),  # planner turn 1
            ScriptedResponse(  # executor turn 1: search
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="venue_search",
                        arguments={"near": "Haymarket", "party_size": 12, "budget_max_gbp": 2000},
                    )
                ]
            ),
            ScriptedResponse(  # executor turn 2: handoff
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="handoff_to_structured",
                        arguments={
                            "reason": "loop half identified a candidate venue; passing to structured half for confirmation under policy rules",
                            "context": "party of 12 near Haymarket on 2026-04-25 19:30; chosen venue haymarket_tap",
                            "data": {
                                "action": "confirm_booking",
                                "venue_id": "Haymarket Tap",
                                "date": "2026-04-25",
                                "time": "19:30",
                                "party_size": "12",
                                "deposit": "£0",
                            },
                        },
                    )
                ]
            ),
            # === ROUND 2 (after reverse handoff from structured rejecting party=12) ===
            ScriptedResponse(content=plan_r2),  # planner turn 2
            ScriptedResponse(  # executor turn 1: new search with smaller party
                tool_calls=[
                    ToolCall(
                        id="c3",
                        name="venue_search",
                        arguments={"near": "Old Town", "party_size": 6, "budget_max_gbp": 2000},
                    )
                ]
            ),
            ScriptedResponse(  # executor turn 2: handoff royal_oak with party=6
                tool_calls=[
                    ToolCall(
                        id="c4",
                        name="handoff_to_structured",
                        arguments={
                            "reason": "retry after reverse handoff — scaled down to fit policy",
                            "context": "party was originally 12; rejected; re-proposing party of 6 at royal_oak (16 seats)",
                            "data": {
                                "action": "confirm_booking",
                                "venue_id": "The Royal Oak",
                                "date": "2026-04-25",
                                "time": "19:30",
                                "party_size": "6",
                                "deposit": "£0",
                            },
                        },
                    )
                ]
            ),
        ]
    )


async def run_scenario(real: bool) -> int:
    with example_sessions_dir("ex7-handoff-bridge", persist=real) as sessions_root:
        session = create_session(
            scenario="ex7-handoff-bridge",
            task="Book a venue for 12 people in Haymarket, Friday 19:30.",
            sessions_dir=sessions_root,
        )
        print(f"Session {session.session_id}")
        print(f"  dir: {session.directory}")

        # Always spawn mock Rasa — keeps Rasa out of the real-mode dependency chain.
        # Real mode means real LLM for the loop half; Rasa behaviour is already
        # validated by Ex6. The mock enforces the same party/deposit policy rules.
        server, _thread, mock_url = spawn_mock_rasa(port=5906)
        rasa_half = RasaStructuredHalf(rasa_url=mock_url)

        tools = build_tool_registry(session)
        if real:
            from sovereign_agent._internal.llm_client import OpenAICompatibleClient
            from sovereign_agent.config import Config

            cfg = Config.from_env()
            print(f"  LLM: {cfg.llm_base_url} (live)")
            print(f"  planner:  {cfg.llm_planner_model}")
            print(f"  executor: {cfg.llm_executor_model}")
            llm_client = OpenAICompatibleClient(
                base_url=cfg.llm_base_url,
                api_key_env=cfg.llm_api_key_env,
            )
            loop_half = LoopHalf(
                planner=DefaultPlanner(model=cfg.llm_planner_model, client=llm_client),
                executor=DefaultExecutor(model=cfg.llm_executor_model, client=llm_client, tools=tools),  # type: ignore[arg-type]
            )
        else:
            client = _build_fake_client_two_rounds()
            loop_half = LoopHalf(
                planner=DefaultPlanner(model="fake", client=client),
                executor=DefaultExecutor(model="fake", client=client, tools=tools),  # type: ignore[arg-type]
            )
        bridge = HandoffBridge(
            loop_half=loop_half,
            structured_half=rasa_half,
            max_rounds=3,
        )

        initial_task = {
            "task": (
                "Book a pub venue in Edinburgh for a party of 12 people on 2026-04-25 at 19:30. "
                "Step 1: call venue_search(near='Haymarket', party_size=12) to find a candidate venue. "
                "Step 2: call handoff_to_structured with the booking details in the 'data' field, "
                "including: action='confirm_booking', venue_id (use the venue's id field), "
                "date='2026-04-25', time='19:30', party_size='12', deposit='£0'. "
                "Do NOT call complete_task — always call handoff_to_structured to confirm the booking."
            )
        }
        try:
            result = await bridge.run(session, initial_task)
        finally:
            server.shutdown()

        print(f"\nBridge outcome: {result.outcome}")
        print(f"  rounds: {result.rounds}")
        print(f"  summary: {result.summary}")
        return 0 if result.outcome == "completed" else 1


def main() -> None:
    real = "--real" in sys.argv
    sys.exit(asyncio.run(run_scenario(real=real)))


if __name__ == "__main__":
    main()
