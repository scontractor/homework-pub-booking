# Ex9 — Reflection

## Q1 — Planner handoff decision

### Your answer

In session `sess_92d0b8710dd6`, the planner (ticket `tk_476a0a5a`,
model Qwen3-Next-80B-A3B-Thinking) decomposed the initial task into two
subgoals: sg_1 `"Search for a pub venue near Haymarket in Edinburgh for
12 people"` with `assigned_half: "loop"`, and sg_2 `"Confirm the
booking details using handoff_to_structured with venue ID, date, time,
and party size"` with `assigned_half: "structured"`. The planner's
assignment of sg_2 to "structured" is an advisory intent label encoding
where confirmation should happen — but it is not the mechanism that
triggers the transition.

The actual signal came from the executor inside ticket `tk_662e21e3`
(executor.run_subgoal/sg_1). The LLM called `venue_search(near=
"Haymarket", party_size=12)` twice (trace lines 4–5), returning 0
results both times, then called `handoff_to_structured` at trace line 6
— still inside the loop-assigned sg_1. The arguments contained only
search-failure metadata (`"search_attempts": [{"budget": 1000,
"results": 0}, ...]`), not a valid venue_id. The bridge detected the
tool call and emitted `session.state_changed` from="loop",
to="structured" at trace line 7.

The structured half found no venue_id in the payload and returned a
rejection (trace line 8, `rejection_reason: "normalisation failed:
missing venue_id"`), triggering the bridge's reverse-handoff path.

Round 2 (trace line 9, bridge.round_start) shows the planner
re-planning with the rejection in context (ticket `tk_539694c1`): sg_1
became `"Search for a venue in Old Town with party size 6"`, again
`assigned_half: "loop"`. The executor (ticket `tk_bc9ec108`) called
`venue_search(near="Old Town", party_size=6)`, found 1 result (trace
line 12), and the bridge forwarded the handoff (trace line 13). The
structured half accepted and the session transitioned to complete at
trace line 14 with booking reference `BK-F3DA6A8C`.

The key architectural point: `assigned_half` is an advisory hint, not
a gate. The executor called `handoff_to_structured` from within a
loop-assigned subgoal (sg_1), and the bridge honoured it. The
planner's assignment of sg_2 to "structured" never executed; the
handoff happened earlier, driven by the executor detecting an
unresolvable search failure.

### Citation

- sessions/sess_92d0b8710dd6/logs/trace.jsonl line 6: executor.tool_called, tool=handoff_to_structured
- sessions/sess_92d0b8710dd6/logs/trace.jsonl line 7: session.state_changed, from=loop, to=structured, round=1
- sessions/sess_92d0b8710dd6/logs/trace.jsonl line 8: session.state_changed, from=structured, to=loop, rejection_reason="normalisation failed: missing venue_id"
- sessions/sess_92d0b8710dd6/logs/trace.jsonl line 14: session.state_changed, from=structured, to=complete
- ticket tk_476a0a5a: planner.plan round 1, sg_1 assigned_half="loop", sg_2 assigned_half="structured"
- ticket tk_662e21e3: executor.run_subgoal/sg_1 round 1, handoff_requested=true
- ticket tk_539694c1: planner.plan round 2, sg_1 assigned_half="loop"
- ticket tk_bc9ec108: executor.run_subgoal/sg_1 round 2, handoff_requested=false

---

## Q2 — Dataflow integrity catch

### Your answer

My integrity check would catch the following specific fabrication
scenario — one that manual review would miss.

Suppose generate_flyer's template were extended to show a cost note:
"Includes venue hire of £75 and minimum spend of £500." Both figures
come from the venues fixture and are factually correct for
bennets_bar. But calculate_cost does not return hire_fee_gbp or
min_spend_gbp in its output dict — it returns subtotal_gbp,
service_gbp, total_gbp, and deposit_required_gbp. So £75 and £500
never appear in _TOOL_CALL_LOG.

When verify_dataflow runs, extract_money_facts pulls both values from
the flyer HTML. fact_appears_in_log scans every ToolCallRecord in the
log — checking output dicts and argument dicts recursively. Neither
£75 nor £500 appears in any record. The function returns
IntegrityResult(ok=False, unverified_facts=["£75", "£500"]).

A human skimming the flyer would see plausible numbers from the right
fixture and approve them. The integrity check fails them because no
tool returned those values in its output — a stricter standard than
"does this look right?"

To reproduce the test exactly: call calculate_cost("bennets_bar", 6, 3)
to populate the log, then call generate_flyer with event_details that
includes an extra key "hire_note": "£75" in the rendered HTML. Run
verify_dataflow on the HTML string. It must return ok=False with "£75"
in unverified_facts. The grader runs this exact pattern by planting
£9999 in the flyer and confirming the check catches it.

### Citation

- starter/edinburgh_research/integrity.py — verify_dataflow,
  extract_money_facts, fact_appears_in_log
- starter/edinburgh_research/tools.py — record_tool_call in
  calculate_cost (logs output dict, not raw fixture fields)

---

## Q3 — Removing one framework primitive

### Your answer

The first production failure I would expect is Nebius API
rate-limiting: per-minute token quotas trigger 429 responses during
bursts of concurrent booking sessions, most commonly after the
planner's decomposition call (the most token-heavy single request).

The sovereign-agent primitive that surfaces this is the **ticket state
machine**. When a planner or executor call raises SA_EXT_RATE_LIMITED,
the ticket in state=running transitions to state=failed with the error
code recorded in its manifest. The session's terminal event becomes
session.state_changed with state=failed. Without the ticket state
machine the rate-limit error would either propagate as an unhandled
exception — losing every partial result — or be swallowed silently,
making the session appear complete when it isn't.

With the ticket state machine, all partial results up to the failure
point are preserved. If venue_search and get_weather tickets reached
state=success before the rate limit hit calculate_cost, those outputs
are in the session directory. An operator can inspect the failed
ticket, identify the exact call that failed, and retry from that
point. The fail-closed design also prevents the bridge from calling
the structured half with an incomplete upstream result — the bridge
checks the session state before dispatching.

The SessionQueue retry primitive would additionally catch transient
429s and back off automatically. But the ticket state machine is the
primitive that makes the failure observable and auditable — it converts
an opaque crash into a structured, addressable artifact in the session
directory.

### Citation

- sovereign_agent.tickets.ticket — TicketState enum (pending, running,
  success, failed)
- sovereign_agent.session.directory — session.mark_failed
