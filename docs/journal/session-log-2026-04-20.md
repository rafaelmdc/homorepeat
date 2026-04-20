# Session Log

**Date:** 2026-04-20

## Objective
- Freeze the codon-composition browser behavior at its current MVP boundary in
  the docs.
- Make the codon-composition docs describe the page that actually ships now,
  not the earlier target design.

## What happened
- Reviewed the current codon-composition route, template, backend payload, and
  frontend chart behavior to confirm the live browser contract.
- Rewrote the codon-composition overview doc so it now describes the shipped
  composition-first route, the current pairwise overview behavior, the stacked
  browse layer, the branch-scoped inspect layer, and the explicit MVP freeze.
- Replaced the old codon-composition implementation-plan slices doc with a
  status document that separates shipped MVP behavior from deferred post-MVP
  work.
- Updated the shared foundation and general-view plan docs so they record the
  current codon-composition exception:
  the shared target remains taxonomy-first overview shells, but codon
  composition is intentionally frozen on the current pairwise `Taxon x Taxon`
  overview for the MVP.
- Recorded that lineage-aware ordering now includes the curated Metazoa
  sibling order used to keep root-linked phyla biologically coherent.

## Files touched
- `docs/general views/codon_composition/overview.md`
  Reframed the viewer as the frozen codon-composition MVP contract.
- `docs/general views/codon_composition/slices.md`
  Replaced the old forward implementation plan with shipped-vs-deferred MVP
  status.
- `docs/general views/shared_foundation.md`
  Added the current codon-composition overview exception and the Metazoa
  sibling-order note.
- `docs/general views/general_plan.txt`
  Updated the top-level general-views plan to reflect the frozen codon
  composition MVP state.

## Validation
- No code validation run.
- Docs-only update based on the current inspected browser view, payload, JS,
  and existing browser tests.

## Current status
- Done.
- Codon composition is now documented as frozen at its current MVP browser
  behavior.

## Open issues
- Route, template, and asset names still use `codon_ratio` in the
  implementation surface.
- The current overview remains a pairwise `Taxon x Taxon` heatmap rather than
  the original `Taxon x Codon` target.

## Next step
- Treat further codon-composition changes as post-MVP work unless they are
  small correctness or stability fixes.

---

# Session Log

**Date:** 2026-04-20

## Objective
- Re-ground the length-view plan on the correct branch where the codon-style
  taxonomy gutter and pairwise overview code actually exist.
- Rewrite the length docs around that reality, then start implementing the
  reuse-first slices for the length overview backend.

## What happened
- Confirmed the previous branch context was wrong and re-inspected the live
  codon-composition browser, including the shared taxonomy gutter and pairwise
  overview behavior.
- Rewrote `docs/general views/length/overview.md` so the length overview is now
  explicitly planned as a codon-style pairwise `Taxon x Taxon` heatmap rather
  than a `Taxon x Length-bin` chart.
- Recreated `docs/general views/length/slices.md` with a phased plan that
  prioritizes reusing the codon overview shell, taxonomy gutter, and stats
  seams, and includes an inspect track.
- Implemented `L2` by extracting the shared backend pairwise-overview payload
  seam in `apps/browser/stats/payloads.py` without changing the codon payload
  contract.
- Implemented `L3` by moving the codon pairwise overview renderer into the new
  shared frontend module `static/js/pairwise-overview.js`, then rewiring the
  codon page to call it.
- Implemented `L4` by adding `build_length_profile_vector_bundle(...)` and
  `summarize_length_profile_vectors(...)`, reusing the existing visible taxa and
  shared 5-aa length bins to build bounded normalized per-taxon profiles.
- Implemented `L5` by adding `build_length_overview_payload(...)` on top of the
  shared pairwise payload seam so the length viewer now has a backend payload
  builder for the future pairwise overview.

## Files touched
- `docs/general views/length/overview.md`
  Reframed the length overview as codon-style pairwise taxon similarity and
  narrowed the inspect MVP to branch-scoped CCDF.
- `docs/general views/length/slices.md`
  Recreated the full phased implementation plan with overview, browse
  alignment, and inspect phases.
- `static/js/pairwise-overview.js`
  New shared frontend module for pairwise overview rendering, including
  visible-window painting and taxonomy-gutter attachment.
- `static/js/repeat-codon-ratio-explorer.js`
  Reduced the codon page to a wrapper that mounts the shared pairwise overview
  renderer.
- `templates/browser/codon_ratio_explorer.html`
  Loads the new shared pairwise overview script.
- `apps/browser/stats/summaries.py`
  Added normalized length-profile vector shaping over the shared length bins.
- `apps/browser/stats/queries.py`
  Added `build_length_profile_vector_bundle(...)`.
- `apps/browser/stats/payloads.py`
  Added the shared pairwise payload seam and `build_length_overview_payload(...)`.
- `apps/browser/stats/__init__.py`
  Exported the new length overview/profile helpers.
- `web_tests/test_browser_stats.py`
  Added direct backend coverage for codon payload shape, length profile vectors,
  and the length pairwise overview payload.

## Validation
- `python manage.py test web_tests.test_browser_stats`
- `python manage.py test web_tests.test_browser_codon_ratios`
- `node --check static/js/pairwise-overview.js`
- `node --check static/js/repeat-codon-ratio-explorer.js`
- `python -m py_compile apps/browser/stats/payloads.py`
- `python -m py_compile apps/browser/stats/queries.py apps/browser/stats/summaries.py`

## Current status
- In progress.
- Docs are updated and backend/frontend reuse seams for the length overview are
  now in place through `L5`.

## Open issues
- The length page still does not consume the new overview payload; `L6` is the
  next wiring step.
- The length template and JS still reflect the old browse-only page shell.
- Inspect work has only been planned so far; no inspect implementation has
  started.

## Next step
- Implement `L6` by wiring the length overview payload and taxonomy-gutter
  payload into `RepeatLengthExplorerView` without changing the page shell yet.

---

# Session Log

**Date:** 2026-04-20

## Objective
- Complete the Length Viewer: wire the overview, browse, and inspect layers
  end-to-end, then redesign the overview heatmap with two statistically sounder
  metrics and a reusable interactive color scale.

## What happened

### Length viewer completion (L6–L15 + refinements)
- Wired overview bundle, taxonomy gutter payload, and both context IDs into
  `RepeatLengthExplorerView.get_context_data` (`L6`).
- Added the Overview section to the length template with pairwise-overview
  payload injection and taxonomy gutter payload (`L7`).
- Mounted the shared `renderPairwiseOverview` renderer in
  `repeat-length-explorer.js` (`L8`).
- Fixed a taxonomy gutter ordering bug: `build_ranked_length_summary_bundle`
  was ordering by observation count rather than lineage, causing the gutter
  to draw overlapping lines for biologically distant taxa sitting adjacently.
  Applied `order_taxon_rows_by_lineage` to fix it.
- Added `build_length_inspect_bundle`, `build_ccdf_points`, and
  `build_length_inspect_summary` to the stats pipeline (`L11 / L12`).
- Wired the inspect bundle, payload, and all summary metrics into the view
  context (`L13`).
- Added the inspect section to the template with CCDF chart container, four
  summary metric panels, and a fallback table (`L14`).
- Added `mountInspectChart` to the JS, rendering an ECharts step-function
  survival curve with percentile mark-lines (`L15`).
- Refined the inspect chart: added linear/log x-axis toggle and focus/full
  range toggle with `syncButtons` / `renderChart` inner-function pattern.
  In log mode, step function is disabled (smooth line) to avoid ECharts
  rendering artefacts. Focus range is `max(ceil(q95 × 1.5), ceil(median × 3), 10)`
  clamped to the data maximum.
- Set the linear x-axis minimum to `dataXMin` so the chart does not pad left
  from zero when the shortest repeats start at 6–10 aa.

### Dual-heatmap overview redesign
- Replaced the single JSD-based overview with two complementary metrics:
  - **Typical profile**: pairwise Wasserstein-1 on lengths clamped at 50 aa,
    normalized by the cap → range [0, 1]. Captures central shape robustly.
  - **Long-repeat burden**: pairwise L1 on per-taxon tail feature vectors
    `[p(L>20), p(L>30), p(L>50), q95/50]`, normalized by 4 → range [0, 1].
    Captures upper-tail enrichment explicitly.
- Added `raw_lengths: sorted(lengths)` to each profile row in
  `summarize_length_profile_vectors` so payload builders have direct access
  to raw lengths without re-querying.
- Added `build_wasserstein_pairwise_matrix` and `build_tail_pairwise_matrix`
  in `summaries.py`, with private helpers `_compute_wasserstein1_distance`,
  `_compute_tail_feature_vector`, and `_compute_l1_tail_distance`.
- Replaced `build_length_overview_payload` (deleted) with
  `build_typical_length_overview_payload` and `build_tail_burden_overview_payload`
  in `payloads.py`. Both use `displayMetric: "divergence"` (raw distance, 0=identical).
- Updated template to serve two `json_script` payloads and a toggle
  (`Typical profile` / `Tail burden`) in the overview section header.
- Rewrote `mountLengthOverview` in JS with toggle state, `syncOverviewModeButtons`,
  `renderOverview` (dispose-and-re-create pattern), and per-mode description
  text toggling via `data-overview-description`.
- Fixed hover tooltip to show metric-specific labels ("W1 distance" /
  "Tail L1 distance") via a `makeTooltipFormatter` factory passed as
  `similarityTooltipFormatter`.

### Reusable interactive color scale (`createDistanceScaleLegend`)
- Added `createDistanceScaleLegend(container, {onRangeChange, onReset})`
  factory function in `pairwise-overview.js`. Analogous to
  `createSignedPreferenceLegend` but for the 0–1 distance domain.
- Visual: a vertical draggable track (orange top → white mid → teal bottom)
  with two marker lines for the current min and max clip positions.
  Click snaps the nearest marker to the clicked position; double-click and
  Reset button restore defaults.
- Wired into `renderPairwiseOverview` via new `distanceScaleStorageKey`
  parameter. Range persists per key in sessionStorage. Any caller that
  passes a key gets the control for free.
- Moved ECharts `visualMap` to `show: false` for the similarity/divergence
  mode; the custom panel is now the sole legend.
- Fixed color direction for divergence mode: `["#0f5964", "#f2efe6", "#d06e37"]`
  (teal=0/identical → white → orange=1/different). Similarity mode uses the
  reverse. Both now use the 3-color diverging gradient with white midpoint.
- Added `.pairwise-distance-scale` CSS block to `site.css` (globally
  available) using the same visual language as the codon preference scale.
- Updated `currentOverviewMargins` to use consistent 176/132 px right
  margin for all heatmap modes so the scale panel never overlaps the zoom
  slider.
- Per-mode storage keys in the length explorer:
  `length-overview:scale:typical` and `length-overview:scale:tail`.

## Files touched
- `apps/browser/stats/summaries.py`
  Added `raw_lengths` to profile rows; added W1, tail-feature, and pairwise
  matrix helpers.
- `apps/browser/stats/payloads.py`
  Deleted `build_length_overview_payload`; added
  `build_typical_length_overview_payload` and `build_tail_burden_overview_payload`.
  Fixed 3-color inRange gradient for divergence/similarity modes.
- `apps/browser/stats/queries.py`
  Applied `order_taxon_rows_by_lineage` in `build_ranked_length_summary_bundle`.
  Added `build_length_inspect_bundle`.
- `apps/browser/stats/__init__.py`
  Updated exports.
- `apps/browser/views/stats/lengths.py`
  Wired all overview and inspect context vars; replaced old single-payload
  context with two-payload context.
- `templates/browser/repeat_length_explorer.html`
  Added overview toggle, two json_script tags, per-mode description text,
  inspect section with scale/range toggles, metric panels, and fallback table.
- `static/js/repeat-length-explorer.js`
  Added dual-overview toggle logic, inspect chart with scale/range toggles,
  custom tooltip formatters, and `distanceScaleStorageKey` wiring.
- `static/js/pairwise-overview.js`
  Added `createDistanceScaleLegend` factory, distance scale helpers,
  `distanceScaleStorageKey` param on `renderPairwiseOverview`, fixed color
  direction, unified right margins.
- `static/css/site.css`
  Added `.pairwise-distance-scale` component CSS.
- `web_tests/test_browser_stats.py`
  Added `LengthOverviewMetricsTests` (23 tests) covering W1 symmetry/values,
  tail feature thresholds, L1 tail distance, matrix properties, and payload
  shapes. Replaced deleted `test_build_length_overview_payload_uses_pairwise_similarity_mode`.

## Validation
- `python manage.py test web_tests` — 235 tests, 0 failures, 2 skipped.
- `node --check static/js/pairwise-overview.js`
- `node --check static/js/repeat-length-explorer.js`

## Current status
- Done.
- Length viewer is feature-complete through the overview, browse, and inspect
  layers, with the dual-heatmap overview and interactive color scale shipped.

## Open issues
- The `.codon-preference-scale` CSS remains inline in the codon-ratio
  template; it could be migrated to `site.css` and renamed alongside
  `pairwise-distance-scale` in a future cleanup pass.
- The `createSignedPreferenceLegend` call in `renderPairwiseOverview`
  accumulates hidden DOM nodes on repeated calls to the same container (pre-existing;
  not introduced here).

## Next step
- Treat the length viewer as MVP-complete.
- Consider writing a freeze/status doc for the length viewer analogous to the
  codon-composition freeze doc.
