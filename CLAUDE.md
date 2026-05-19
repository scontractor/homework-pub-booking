# homework-pub-booking — Claude Code context

KCL coursework. Build an AI agent that books an Edinburgh pub. Five exercises
(Ex5–Ex9), each graded independently.

**Deadline: 2026-05-22 23:59 UTC-12 (= 2026-05-23 noon London time)**
Submission: commit to `main`; CI runs at the deadline and is authoritative.

## Stack

- **sovereign-agent 0.2.0** — the agent SDK. Do not bump the version pin.
- **Python 3.12**, managed by `uv`. All commands go through `make`.
- **Nebius API** (OpenAI-compatible) — Qwen3-32B executor, Qwen3-Next-80B planner.
- **Rasa CALM** (Ex6/Ex7) — runs in Docker on localhost:5005.
- `export PYTHONUTF8 := 1` is set in the Makefile to avoid cp1252 errors on Windows.

## Key commands

| Command | What it does |
|---|---|
| `make` | Structured walkthrough — read this first |
| `make next` | Tells you the literal next command to run based on repo state |
| `make setup` | Install deps, check env |
| `make verify` | Smoke-test Nebius connection — run this FIRST when anything seems weird |
| `make test` | Run all public pytest tests |
| `make lint` / `make format` | Ruff lint / auto-fix |
| `make check-submit` | Full local pre-flight (Mechanical layer) |
| `make narrate-latest` | Replay last session in plain English with tool-call timeline |
| `make ex5` | Run Ex5 offline (FakeLLMClient) |
| `make ex5-real` | Run Ex5 against Nebius (burns tokens) |
| `make ex6-help` | Read before starting Ex6 — explains the three-terminal setup |
| `make ex6` / `make ex6-real` | Ex6 offline / real |
| `make ex7` | Ex7 end-to-end bridge demo |
| `make ex8-text` / `make ex8-voice` | Ex8 text / voice mode |
| `make educator-diagnostics` | Full env dump — use this when opening a help issue |

## Secrets — NEVER commit

`.env` is gitignored. Contains: `NEBIUS_KEY`, `RASA_PRO_LICENSE`,
`SPEECHMATICS_KEY`, `RIME_API_KEY`. Sessions in `sessions/` are also
gitignored — they contain API output.

## Scoring

| Layer | Points | Runs |
|---|---|---|
| Mechanical | 27 | Locally + CI |
| Behavioural | 19 | Partial locally, full CI |
| Reasoning (Ex9) | 30 | CI only (LLM judge) |
| **Total** | **76** | |

Fresh clone scores 4/76 (scaffold preservation only). Complete submission ~70/76 locally.
`make check-submit` reproduces Mechanical + partial Behavioural. Reasoning scores only at CI
by a different LLM than you used — so 0/30 locally is expected.

---

## Ex5 — Edinburgh research scenario (20 pts)

**Location:** `starter/edinburgh_research/`

**Status: COMPLETE.** All four tools implemented. `verify_dataflow` implemented.
Offline run produces `workspace/flyer.html` with `data-testid` attributes.

### What's implemented

- `tools.py` — four tools, all call `record_tool_call(...)` before returning:
  - `venue_search` — reads `venues.json`, bidirectional area substring match,
    spiral guard (caps at 3 calls via `_TOOL_CALL_LOG` count)
  - `get_weather` — reads `weather.json`, returns `ToolError("SA_TOOL_INVALID_INPUT")` on miss
  - `calculate_cost` — reads `catering.json` + `venues.json`; formula:
    `subtotal = base_per_head * venue_mult * party_size * max(1, duration_hours)`;
    deposit: 0 if total<300, 20% if 300–1000, 30% if >1000
  - `generate_flyer` — writes `workspace/flyer.html`, `parallel_safe=False`

- `integrity.py` — `verify_dataflow` scans `data-testid` values in the flyer,
  checks each against `_TOOL_CALL_LOG` output dicts recursively.
  Grader plants £9999 — this is caught.

### Grading breakdown

| Check | Points |
|---|---|
| `make ex5` runs clean; flyer.html written | 4 |
| All 3 read tools filter fixtures correctly | 4 |
| `generate_flyer` is `parallel_safe=False` | 1 |
| `verify_dataflow` catches planted fabrication | 6 |
| `verify_dataflow` no false-positives on legit flyer | 3 |
| Session has successful planner + executor tickets | 2 |

**Penalty:** −3 pts if any tool missing a dataflow log entry.

---

## Ex6 — Rasa structured half (20 pts)

**Location:** `starter/rasa_half/`, `rasa_project/`

### Three-terminal setup (critical — read `make ex6-help` first)

Ex6 needs **three terminals running simultaneously**:
1. `make rasa-actions` — custom action server (port 5055)
2. `make rasa-serve` — Rasa dialog server (port 5005)
3. `make ex6-real` — your scenario runner

After editing any file in `rasa_project/actions/`, **restart `make rasa-actions`**.
Rasa caches Python modules in memory; changes won't load until restart.

### What to implement

1. `structured_half.py` — `RasaStructuredHalf` subclass, routes booking intent
   to Rasa via HTTP (`http://localhost:5005/webhooks/rest/webhook`), returns `HalfResult`.
2. `rasa_project/data/flows.yml` — three flows:
   - `confirm_booking` — happy path, ends committed
   - `resume_from_loop` — triggered on mid-scenario loop handoff
   - `request_research` — triggers re-research when manager reply exceeds cap
3. `rasa_project/actions/actions.py` — `ActionValidateBooking`:
   - Rejects deposit > £300
   - Rejects party_size > 8
   - Both pass → returns `action: committed` + booking ref
4. `validator.py` — normalises booking data (currency £→int, date format,
   party_size coercion, etc.) before sending to Rasa.

### Grading breakdown

| Check | Points |
|---|---|
| `make ex6` runs clean (Rasa container up) | 4 |
| `confirm_booking` flow commits a valid booking | 4 |
| `ActionValidateBooking` rejects deposit > £300 | 3 |
| `ActionValidateBooking` rejects party > 8 | 3 |
| `resume_from_loop` re-enters correctly after loop handoff | 4 |
| Validator normalises ≥3 of: date, currency, party_size, timezone, venue_id | 2 |

---

## Ex7 — Handoff bridge (20 pts)

**Location:** `starter/handoff_bridge/`

**Prerequisites:** Ex5 and Ex6 both green.

### What to implement

1. `bridge.py` — routes loop→structured handoff; catches structured rejection;
   hands back to loop with rejection reason.
2. `run.py` — drives the required trajectory:
   - "party of 12, Haymarket, Friday 19:30"
   - Loop finds `haymarket_tap` (8 seats → too small) → hands off to structured
   - Structured rejects "party exceeds cap" → bridge returns to loop
   - Loop finds `royal_oak` (16 seats) → hands off to structured → approves
   - Session marks complete

**Key invariant:** at most ONE `handoff_to_*.json` file visible in `ipc/` at
any time. Multiple simultaneous handoffs → `SA_IO_MALFORMED_HANDOFF_STATE`.

### Architectural note (from real run sess_52e9be8bc50b)

The planner always assigns `assigned_half: "loop"` in its plan JSON — it does
NOT decide the transition. The executor calls `handoff_to_structured` tool at
runtime; the bridge detects this tool call and transitions the session state.
Planner's `assigned_half` is an advisory hint, not a gate.

### Grading breakdown

| Check | Points |
|---|---|
| Forward handoff (loop→structured) preserves full context | 4 |
| Reverse handoff (structured→loop) preserves rejection reason | 4 |
| Session reaches `completed` within 3 round trips | 4 |
| ≤1 handoff file in `ipc/` at any time | 2 |
| Trace has `session.state_changed` events for each transition | 3 |
| Grader's planted failure (structured always rejects) is caught + reported | 3 |

---

## Ex8 — Voice pipeline (20 pts)

**Location:** `starter/voice_pipeline/`

### What to implement

1. `manager_persona.py` — system prompt + `ManagerPersona` wrapping
   `OpenAICompatibleClient` → Llama-3.3-70B-Instruct on Nebius.
   Persona: gruff Edinburgh pub manager; accepts ≤£300 deposit + ≤8 people;
   declines otherwise with specific reason.
2. `voice_loop.py`:
   - Text mode (`--text`): stdin → persona → stdout, trace logged
   - Voice mode (`--voice`): Speechmatics STT + Rime.ai Arcana TTS
   - Graceful degradation: if `SPEECHMATICS_KEY` missing + `--voice` passed →
     fall back to text with visible warning, never crash
   - Every utterance logged as `voice.utterance_in` / `voice.utterance_out`

### Grading breakdown

| Check | Points |
|---|---|
| Text mode: full 3+ turn conversation | 6 |
| Manager persona stays in character (LLM judge) | 4 |
| Voice mode end-to-end (if keys present) | 4 |
| Every utterance in trace with correct event_type | 3 |
| Missing-key graceful degradation | 3 |
| **Bonus:** real voice mode STT working | +4 |

Text-only max: 16/20. Voice bonus: 20/20 (+4 above).

---

## Ex9 — Reflection (20 pts)

**Location:** `answers/ex9_reflection.md`

**Status: COMPLETE.** All three questions answered with real session citations.

### The three questions

- **Q1** — Find a specific Ex7 trace point where the planner handed off to
  structured. Quote `assigned_half` or the exact subgoal. What signal caused
  it? (Must cite real ticket IDs / trace lines from your session.)
- **Q2** — One specific instance (or reproducible scenario) where
  `verify_dataflow` caught something manual inspection would miss. Must be
  concrete enough to reconstruct the test case.
- **Q3** — First production failure you'd expect shipping next week +
  which sovereign-agent primitive surfaces it. EXACTLY one primitive, one failure.

### Grading breakdown

| Check | Points |
|---|---|
| Each answer cites specific ticket IDs or trace lines | 9 (3×3) |
| Each answer 100–400 words | 3 (1×3) |
| Answers grounded in reality (not generic waffle) | 6 (2×3) |
| Q3 names exactly ONE primitive + ONE failure mode | 2 |

LLM-as-judge cross-checks citations against committed session artifacts.

---

## When things break

1. `make verify` — run this FIRST when anything seems wrong
2. `make narrate-latest` — replay last session in plain English
3. `docs/real-mode-failures.md` — catalogue of every known real-mode failure
   (Qwen spiraling, Rasa cache issues, voice SDK quirks) with diagnosis + fix
4. Open an issue with `make educator-diagnostics` output — gives the teaching team everything needed to help

**The `make ex5-real` Qwen spiral is expected and documented.** When it happens,
read `docs/real-mode-failures.md`. The spiral detection in `venue_search` (cap at 3 calls)
mitigates it but doesn't eliminate it. Offline marks are unaffected.

---

## Integrity requirements (all exercises)

- Every scenario ships with a dataflow integrity check. **−10 pts** from
  Mechanical if any scenario is missing it.
- **No raw secrets committed** — grader auto-detects, zeros the affected exercise.
- No wholesale LLM-generated commit messages. Short focused commits are fine.

## Answer files

All live in `answers/`:
- `ex5_loop_scenario.md` — narrative of the Ex5 run
- `ex6_rasa_integration.md`
- `ex7_handoff_bridge.md`
- `ex8_voice_pipeline.md`
- `ex9_reflection.md`

Do not delete or rename these. Replace every `*(Write your answer below this line)*` placeholder.
