# Ex9 — Reflection

## Q1 — Planner handoff decision

### Your answer

In session `sess_92d0b8710dd6`, the planner (ticket `tk_476a0a5a`,
model Qwen3-Next-80B-A3B-Thinking, 402 tokens in, 1216 tokens out,
7467 ms) decomposed the initial task into two subgoals: sg_1
`"Search for a pub venue near Haymarket in Edinburgh for 12 people"`,
`assigned_half: "loop"`,
`success_criterion: "Returns a venue ID from the search results"`;
and sg_2 `"Confirm the booking details using handoff_to_structured
with venue ID, date, time, and party size"`, `assigned_half:
"structured"`. The `assigned_half` label on sg_2 is advisory intent —
it is not the mechanism that triggers the transition.

The actual signal came from the executor inside ticket `tk_662e21e3`
(`executor.run_subgoal/sg_1`, 112521 ms — nearly two minutes of LLM
inference across 3 turns). The executor called
`venue_search(near="Haymarket", party_size=12)` at trace line 4 (0
results), then `venue_search(near="Haymarket", party_size=12,
budget_max_gbp=2000)` at trace line 5 (0 results again). Having
exhausted sg_1's `success_criterion` — no venue_id anywhere in the
responses — the executor called `handoff_to_structured` at trace line
6, still inside the loop-assigned sg_1, with only search-failure
metadata: `{"search_attempts": [{"budget": 1000, "results": 0},
{"budget": 2000, "results": 0}, {"budget": 5000, "results": 0}]}`.
The raw output records `final_answer: "(handoff requested)"` — not a
completed subgoal result but an explicit escalation signal. The bridge
detected the tool call and emitted `session.state_changed from=loop
to=structured` at trace line 7. The normaliser found no `venue_id`
and returned rejection at trace line 8 (`rejection_reason:
"normalisation failed: missing venue_id"`).

Round 2 (trace line 9). The planner re-ran (ticket `tk_539694c1`,
4638 ms, 390 tokens in, 720 tokens out). sg_1 became `"Search for a
venue in Old Town with party size 6"` — the planner absorbed both
constraints from the rejection message: change area away from
Haymarket, and reduce party_size from 12 to 6 to satisfy the ≤ 8
cap. The executor (ticket `tk_bc9ec108`, 12281 ms, 1 tool call) called
`venue_search(near="Old Town", party_size=6)` (trace line 12: 1
result, `royal_oak`). The bridge forwarded to structured (trace line
13: `state_changed loop→structured round=2`). Rasa committed at trace
line 14: `state_changed from=structured to=complete`, booking
reference `BK-F3DA6A8C`.

The key architectural point: `assigned_half` is an advisory hint, not
a gate. The executor escalated from within the loop-assigned sg_1 —
not from sg_2 — and the bridge honoured it unconditionally. The
planner's sg_2 assignment to "structured" never executed.

### Citation

- sessions/sess_92d0b8710dd6/logs/trace.jsonl line 4–5: executor.tool_called, tool=venue_search, 0 results both calls
- sessions/sess_92d0b8710dd6/logs/trace.jsonl line 6: executor.tool_called, tool=handoff_to_structured
- sessions/sess_92d0b8710dd6/logs/trace.jsonl line 7: session.state_changed, from=loop, to=structured, round=1
- sessions/sess_92d0b8710dd6/logs/trace.jsonl line 8: session.state_changed, from=structured, to=loop, rejection_reason="normalisation failed: missing venue_id"
- sessions/sess_92d0b8710dd6/logs/trace.jsonl line 14: session.state_changed, from=structured, to=complete
- ticket tk_476a0a5a: manifest.json — planner.plan, 7467 ms, Qwen3-Next-80B-A3B-Thinking, 1216 tokens out; raw_output.json — sg_1 success_criterion="Returns a venue ID from the search results"
- ticket tk_662e21e3: manifest.json — executor.run_subgoal/sg_1, 112521 ms, 3 tool_calls; raw_output.json — final_answer="(handoff requested)", handoff_requested=true
- ticket tk_539694c1: manifest.json — planner.plan, 4638 ms, 720 tokens out; raw_output.json — sg_1 description changed to Old Town, party_size=6
- ticket tk_bc9ec108: manifest.json — executor.run_subgoal/sg_1, 12281 ms, 1 tool_call; raw_output.json — final_answer={"venue_id": "royal_oak"}, handoff_requested=false

---

## Q2 — Dataflow integrity catch

### Your answer

A catch that happened during development: an early version of
`generate_flyer`'s HTML template rendered `"No deposit required
(booking under £300 threshold)"` in the cost section when
`deposit_required_gbp == 0`.

`verify_dataflow` calls `extract_money_facts`, which strips HTML tags
and returns all `£<number>` patterns. It found `£300`. Then
`fact_appears_in_log("300")` scanned every `ToolCallRecord` in
`_TOOL_CALL_LOG`, recursively walking output and argument dicts via
`_scan`. For the standard run scenario — `venue_search("Haymarket",
party_size=6)` populating `haymarket_tap` (hire_fee=£0,
min_spend=£200), `calculate_cost("haymarket_tap", 6, 3)` returning
`{subtotal_gbp: 324, service_gbp: 32, total_gbp: 556,
deposit_required_gbp: 111}` — no record contains the value 300. The
result was `IntegrityResult(ok=False, unverified_facts=["£300"])`.

A human reviewer seeing `£300` in a deposit section immediately
recognises it as the correct policy threshold. It is factually
accurate. But the integrity check applies a stricter standard: the
value must have been returned by a tool. `£300` is a hardcoded
constant inside `calculate_cost`'s deposit logic (`if total < 300:
deposit = 0`) — a business rule, not a data value. It never appears
in any `ToolCallRecord` output. The check correctly flags it as
unverified fabrication. Changing the copy to `"No deposit required
for this booking."` removed the spurious fact and the check passed.

To reconstruct the test: populate `_TOOL_CALL_LOG` by calling
`venue_search("Haymarket", 6)` and `calculate_cost("haymarket_tap",
6, 3)`. Then construct HTML containing the string `£300` anywhere in
the body (e.g. a deposit note). Call `verify_dataflow(html)`. It must
return `ok=False` with `"£300"` in `unverified_facts`. The grader
runs the same pattern using a different planted value (`£9999`).

### Citation

- starter/edinburgh_research/integrity.py — `verify_dataflow`,
  `extract_money_facts`, `fact_appears_in_log`, `_scan`
- starter/edinburgh_research/tools.py — `calculate_cost` output dict
  (returns subtotal/service/total/deposit, not the threshold constant)
- starter/edinburgh_research/sample_data/venues.json — haymarket_tap:
  hire_fee_gbp=0, min_spend_gbp=200 (neither is 300)

---

## Q3 — Removing one framework primitive

### Your answer

The first production failure I would expect is Nebius API
rate-limiting: per-minute token quotas trigger 429 responses during
bursts of concurrent booking sessions, most commonly after the
planner's decomposition call (the most token-heavy single request —
ticket `tk_476a0a5a` consumed 1216 output tokens from
Qwen3-Next-80B-A3B-Thinking in one shot).

The sovereign-agent primitive that surfaces this is the **ticket state
machine**. When a planner or executor call raises `SA_EXT_RATE_LIMITED`,
the ticket transitions from `state=running` to `state=failed`, with
`error_code: "SA_EXT_RATE_LIMITED"` and the full error message written
to the ticket's `state.json` and `manifest.json` on disk. The
session's terminal trace event becomes `session.state_changed` with
`state=failed`. The failure is now a structured, addressable artifact
rather than an unhandled exception.

Without the ticket state machine the rate-limit would either crash the
process — losing all partial results from earlier subgoals — or be
caught and swallowed at the wrong layer, making the session appear
complete when it isn't. The fail-closed design also prevents the
bridge from dispatching to the structured half with an incomplete
upstream result, because the bridge reads session state before
forwarding any handoff.

With the ticket state machine intact, partial results up to the
failure are preserved. If `venue_search` and `get_weather` tickets
reached `state=success` before the 429 hit `calculate_cost`, their
outputs remain in the session directory. An operator can inspect the
exact failed ticket, identify which model call triggered the limit,
and resume from that checkpoint — without re-running the work already
completed.

### Citation

- sovereign_agent.tickets.ticket — `TicketState` enum
  (pending → running → success | failed)
- sovereign_agent.session.directory — `session.mark_failed`,
  terminal `session.state_changed` event
- sessions/sess_92d0b8710dd6/logs/tickets/tk_476a0a5a/manifest.json —
  example of a success ticket: 1216 tokens out from Qwen3-Next-80B
  (shows the token cost that would trigger a 429 under load)
