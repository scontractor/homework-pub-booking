# Ex7 — Handoff bridge

## Your answer

The bridge runs a round-trip loop. Session `sess_92d0b8710dd6` shows the
full two-round trajectory from initial task to committed booking reference
`BK-F3DA6A8C`.

**Round 1** (trace line 1: `bridge.round_start round=1 half=loop`). The
planner (trace line 2) received the task "Book a pub venue in Edinburgh for
a party of 12 people on 2026-04-25 at 19:30" and produced two subgoals
(trace line 3, `num_subgoals=2`): sg_1 "Search near Haymarket, party_size=12"
`assigned_half="loop"`; sg_2 "Confirm booking via handoff_to_structured"
`assigned_half="structured"`. The executor called
`venue_search(near="Haymarket", party_size=12)` twice (trace lines 4–5),
receiving 0 results both times (no Haymarket venue seats 12). At trace line 6
it called `handoff_to_structured` — still inside the loop-assigned sg_1 —
with only search failure metadata: `{"search_attempts": [{"budget": 1000,
"results": 0}, {"budget": 2000, "results": 0}, {"budget": 5000, "results":
0}]}`. No `venue_id` was in the payload.

The bridge detected the tool call, emitted `session.state_changed from=loop
to=structured` (trace line 7), and forwarded the payload to the structured
half. The validator raised `ValidationFailed("missing venue_id")` and
returned rejection (trace line 8: `session.state_changed from=structured
to=loop, rejection_reason="normalisation failed: missing venue_id"`).

**Round 2** (trace line 9: `bridge.round_start round=2`). The bridge rebuilt
the task with the rejection reason in context (trace line 10 preview shows
"party_size <= 8"). The planner re-planned (trace line 11, `num_subgoals=2`)
and the executor called `venue_search(near="Old Town", party_size=6)` (trace
line 12: 1 result, `royal_oak`). The bridge forwarded the handoff (trace
line 13: `session.state_changed from=loop to=structured round=2`).
This time `normalise_booking_payload` found a valid `venue_id`, Rasa's
`ActionValidateBooking` accepted (deposit=£0, party_size=6), and the bridge
transitioned to complete (trace line 14: `session.state_changed from=
structured to=complete round=2`). `session.json` records `state=completed`,
`booking_reference=BK-F3DA6A8C`.

The key invariant maintained throughout: exactly one `handoff_to_structured.json`
file exists in `ipc/` at any time. The bridge writes it before forwarding,
moves it to `logs/handoffs/` after the structured half responds, and only
writes a new one on the next round — never overlapping.

## Citations

- `sessions/sess_92d0b8710dd6/logs/trace.jsonl` — all 14 trace lines
- `sessions/sess_92d0b8710dd6/session.json` — `state=completed`,
  `booking_reference=BK-F3DA6A8C`, full booking dict (royal_oak, 2026-04-25,
  19:30, party_size=6, deposit=£0)
- `sessions/sess_92d0b8710dd6/logs/tickets/tk_476a0a5a/summary.md` —
  planner round 1: 2 subgoals, 1 loop + 1 structured
- `sessions/sess_92d0b8710dd6/logs/tickets/tk_662e21e3/summary.md` —
  executor round 1: 3 tool calls (venue_search×2, handoff_to_structured),
  handoff requested
- `sessions/sess_92d0b8710dd6/logs/tickets/tk_539694c1/summary.md` —
  planner round 2: 2 subgoals
- `sessions/sess_92d0b8710dd6/logs/tickets/tk_bc9ec108/summary.md` —
  executor round 2: 1 tool call (venue_search), no handoff requested
- `starter/handoff_bridge/bridge.py` — `HandoffBridge.run`, IPC file
  lifecycle, reverse-task construction
