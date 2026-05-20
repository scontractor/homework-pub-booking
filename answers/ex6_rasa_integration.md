# Ex6 — Rasa structured half

## Your answer

`RasaStructuredHalf.run()` receives a `HalfContext` containing the loop
half's raw booking data dict. Before any network call it passes the data
through `normalise_booking_payload()` in `validator.py`. Five fields are
normalised:

1. **venue_id** — `canonicalise_venue_id` lowercases the string and replaces
   spaces and hyphens with underscores: `"Haymarket Tap"` → `"haymarket_tap"`.
2. **date** — `_normalise_date` parses natural-language strings;
   `"25th April"` → `"2026-04-25"`, `"today"` → `"2026-04-25"`. Accepts
   ISO-8601 pass-through unchanged.
3. **time** — `parse_time_24h` converts 12-hour format: `"7:30pm"` →
   `"19:30"`, `"half seven"` is not handled (defaults to ValueError, caught
   upstream), `"19:30"` passes through unchanged.
4. **party_size** — `parse_party_size` coerces `"6 people"` → `6` (int),
   rejects values `< 1` with `ValidationFailed`.
5. **deposit** — `parse_currency_gbp` strips `£` prefix and `GBP` suffix:
   `"£300"` → `300`, `500.0` → `500`.

If any required field is absent or malformed, `ValidationFailed` is raised.
`run()` catches it and returns `HalfResult(success=False,
next_action="escalate", rejection_reason=str(e))` — the structured half
never raises; it always returns a `HalfResult` with a clear reason the loop
can act on.

The normalised payload is POSTed as JSON to
`http://localhost:5005/webhooks/rest/webhook`. The `sender` field is a
stable SHA-1 prefix of `venue_id + date + time`, so retries within one
session reuse the same Rasa conversation tracker instead of spawning
a new dialogue.

`ActionValidateBooking` in `actions.py` enforces two hard constraints:
`deposit_gbp > 300` → reject (above the auto-approve ceiling); `party_size
> 8` → reject (venue capacity). Each rejection returns `action: "rejected"`
plus a specific reason string. When both checks pass it emits
`action: "committed"` with a booking reference, which `run()` maps to
`HalfResult(success=True, next_action="complete")`.

The offline mock server (a stdlib `http.server` thread) always returns
`action: committed`, giving deterministic unit-test coverage for the happy
path. Rejection behaviour is exercised in Ex7 where the bridge's
round-trip loop drives the decision through the full Rasa container.

## Citations

- `starter/rasa_half/validator.py` — `normalise_booking_payload`,
  `canonicalise_venue_id`, `parse_currency_gbp`, `parse_time_24h`,
  `parse_party_size`, `_normalise_date`
- `starter/rasa_half/structured_half.py` — `RasaStructuredHalf.run`,
  `ValidationFailed` catch block, mock server thread
- `rasa_project/actions/actions.py` — `ActionValidateBooking`
- `rasa_project/data/flows.yml` — `confirm_booking`,
  `resume_from_loop`, `request_research` flows
