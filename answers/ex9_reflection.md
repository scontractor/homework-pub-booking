# Ex9 — Reflection

## Q1 — Planner handoff decision

### Your answer

In my ex7 run (session sess_52e9be8bc50b), the planner's plan JSON for
both rounds assigned the single subgoal sg_1 to assigned_half: "loop" —
not "structured". The actual decision to transition to the structured
half was made by the executor at runtime, not by the planner's
assignment. Trace line 5 shows the decisive event:
event_type="executor.tool_called", tool="handoff_to_structured",
reason="loop half identified a candidate venue; passing to structured
half for confirmation under policy rules". Line 6 immediately follows:
event_type="session.state_changed", from="loop", to="structured",
round=1.

The signal driving the call was the executor recognising that booking
confirmation involves deterministic policy constraints (deposit cap,
party-size cap) rather than open-ended research. That distinction maps
directly onto which half should run: anything rule-following belongs to
the structured half. The bridge honours the tool call regardless of the
planner's assignment.

Round 2 begins at trace line 8 (bridge.round_start, round=2). By then
the planner was re-invoked with the rejection reason embedded in the
task: "The structured half rejected the previous proposal. Reason:
party_too_large." The planner produced a fresh plan, the executor
searched Old Town and found royal_oak (16 seats), and called
handoff_to_structured a second time. Line 14 shows
session.state_changed from="structured", to="complete".

The key architectural lesson: the planner's assigned_half field is an
advisory hint, not a physical gate. The bridge enforces transitions by
detecting the handoff_to_structured tool call. This means a real LLM
executor can hand off even when the plan said "loop" — useful for
unexpected rule violations discovered mid-subgoal.

### Citation

- trace.jsonl line 5: executor.tool_called, tool=handoff_to_structured
- trace.jsonl line 6: session.state_changed, from=loop, to=structured
- ticket tk_70f785e7: planner.plan, state=success, round 1
- ticket tk_37542fa5: executor.run_subgoal/sg_1, state=success, round 1

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
