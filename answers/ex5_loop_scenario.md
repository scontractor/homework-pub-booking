# Ex5 — Edinburgh research loop scenario

## Your answer

The agent ran the Edinburgh research scenario offline using FakeLLMClient.
The planner produced two subgoals: sg_1 (research — assigned to loop) and
sg_2 (produce flyer — also loop). sg_2 depends on sg_1, so the executor ran
them sequentially.

**Turn 1 — parallel read-tool burst.** The executor called three tools in one
shot: `venue_search(near="Haymarket", party_size=6)`, which returned
`haymarket_tap` (8 seats available, area "Haymarket", hire_fee £0,
min_spend £200); `get_weather(city="Edinburgh", date="2026-04-25")`, which
returned `{condition: "cloudy", temperature_c: 12, precip_mm: 0.0}`; and
`calculate_cost(venue_id="haymarket_tap", party_size=6, duration_hours=3,
catering_tier="bar_snacks")`, which applied the formula
`subtotal = base_per_head × venue_mult × 6 × 3 = £324`, added 10% service
(£32) and min_spend (£200), producing `total_gbp=556, deposit_required_gbp=111`
(20% bracket). All three are `parallel_safe=True` — they only read fixtures.

**Turn 2 — flyer write.** `generate_flyer(event_details={...})` wrote
`workspace/flyer.html`. Every key fact — `£556` total, `£111` deposit,
`"cloudy"`, `"12"` — was rendered inside `data-testid`-tagged elements so
`verify_dataflow` can parse them structurally rather than with loose regex.
`generate_flyer` is registered `parallel_safe=False`; a concurrent write to
the same path would corrupt or interleave HTML.

**Integrity check — real catch.** An early draft of the flyer template wrote
`"No deposit required (booking under £300 threshold)"` in prose.
`verify_dataflow` calls `extract_money_facts`, which strips HTML tags and
finds every `£<number>` occurrence. It found `£300`, then called
`fact_appears_in_log("£300")`, which scans every `ToolCallRecord` output and
argument dict recursively. `£300` never appears in any record — it is a
business-rule constant inside `calculate_cost`'s logic, never returned as
data. The check returned `IntegrityResult(ok=False, unverified_facts=["£300"])`.
Changing the copy to `"No deposit required for this booking."` removed the
spurious fact and the check passed. Without the integrity check, `£300` would
look entirely plausible in context and slip through manual review.

## Citations

- `starter/edinburgh_research/tools.py` — `venue_search`, `get_weather`,
  `calculate_cost`, `generate_flyer`; parallel_safe registrations
- `starter/edinburgh_research/integrity.py` — `verify_dataflow`,
  `extract_money_facts`, `fact_appears_in_log`
- `starter/edinburgh_research/sample_data/venues.json` — `haymarket_tap`
  fixture (seats=8, hire=£0, min_spend=£200)
- `starter/edinburgh_research/sample_data/weather.json` — Edinburgh
  2026-04-25 (cloudy, 12°C)
- `starter/edinburgh_research/sample_data/catering.json` — bar_snacks
  base rate, venue modifiers, service_charge_percent
