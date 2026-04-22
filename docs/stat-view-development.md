# Stat View Development

This guide describes the practical pattern for adding or modifying statistical
browser views.

## Standard View Contract

A statistical browser view should provide:

- validated filters in the page context
- one or more JSON payloads using `json_script`
- an empty-state reason
- a no-JS fallback table where feasible
- focused backend tests for payload shape and edge cases
- JavaScript syntax checks for changed chart files

The common file set is:

```text
apps/browser/views/stats/<view>.py
apps/browser/stats/queries.py
apps/browser/stats/payloads.py
apps/browser/stats/summaries.py
templates/browser/<view>.html
static/js/<view>.js
web_tests/test_browser_<view>.py
```

## Backend Pattern

Use this layered pattern:

1. `StatsFilterState` normalizes user input.
2. Query builders select canonical repeat calls and codon usage rows.
3. Summary builders reduce rows into biological summaries.
4. Payload builders serialize chart-ready JSON.
5. The view injects payloads into the template with stable IDs.

Avoid mixing these responsibilities. For example, `payloads.py` should not issue
database queries, and templates should not infer statistical values from raw
rows.

## Empty States

Handle empty data explicitly at each layer:

- no selected residue
- no matching repeat calls
- repeat calls exist but no codon usage rows exist for the selected residue
- no taxa reach the display rank/minimum observation threshold
- pairwise view has fewer than two taxa

Payloads should include enough metadata for the frontend to hide unavailable
modes rather than showing broken controls.

## Branch-Scoped Inspect Layers

Inspect layers answer: "what does this focused branch look like?"

Use branch-scoped canonical repeat-call querysets directly. Do not force inspect
through unfiltered rollups, because branch filters are interactive and should
reflect the current filter state exactly.

Parent comparison, when available, should align rows by stable keys such as
length-bin start, not by array index.

## Pairwise Views

Pairwise heatmaps should use `static/js/pairwise-overview.js` unless there is a
clear reason not to.

Expected payload shape:

- `taxa`: ordered visible taxa
- `divergenceMatrix`: square symmetric matrix
- `displayMetric`: usually `divergence` or `similarity`
- `valueMin` and `valueMax`
- optional mode-specific fields

Use divergence for raw distances where `0` means identical. Convert to
similarity only when the UI text and color scale explicitly communicate that
higher means more similar.

## Taxonomy Gutters

Taxonomy gutters are reusable SVG overlays.

Backend:

```python
build_taxonomy_gutter_payload(rows, filter_state=filter_state, collapse_rank=filter_state.rank)
```

Frontend:

```javascript
const gutterOverlay = attachTaxonomyGutter(chart, taxonomyGutterPayload);
gutterOverlay.render({
  showLabels,
  zoomState,
  gutterWidth,
  top,
  bottom,
  left,
  right,
});
```

Rules:

- chart category axis values must be taxon IDs as strings
- format labels back to names if axis labels are visible
- refresh the gutter after zoom, resize, and chart option changes
- hide duplicated y-axis labels when the gutter is active
- if the chart has a bottom taxonomy tree, reserve vertical space explicitly

## Zoom and Wheel Behavior

Use shared helpers from `stats-chart-shell.js`:

- `defaultZoomState`
- `normalizeZoomState`
- `buildYAxisZoom`
- `buildXAxisZoom`
- `installWheelHandler`
- `resolveZoomState`

Keep y-axis dataZoom first when using `installWheelHandler`; it dispatches to
`dataZoomIndex: 0`.

Plain wheel scrolls/pans the visible row window. Shift+wheel zooms around the
cursor. Horizontal sliders should update x-axis state without corrupting y-axis
state.

## Tables and Pagination

For large grouped fallback tables, use the shared summary-table paginator in
`static/js/site.js`.

Template hooks:

```html
<section data-summary-section data-summary-page-size="25">
  <tbody data-summary-table-body>
    <tr data-summary-row>...</tr>
  </tbody>
  <nav data-summary-pagination hidden>
    <button data-summary-pagination-previous>Previous</button>
    <span data-summary-pagination-status></span>
    <button data-summary-pagination-next>Next</button>
  </nav>
</section>
```

## Chart Mode Controls

Mode buttons should reflect payload availability.

- unavailable payload: hide or disable the mode
- active payload: set `aria-pressed="true"`
- switching modes should reset incompatible zoom state
- descriptions should switch with the mode

For example, dominance is only meaningful for residues with three or more
visible codons. Preference is the appropriate two-codon view.

## Support Display

Support should be visible but visually secondary.

Recommended support fields:

- observation count
- species count
- percent of the current panel total

Support traces can be shown on a 0-100% axis when the primary chart is also a
composition chart. They should not alter codon-share calculations.

## Common Failure Modes

Rollup/live mismatch:

- unfiltered views may use precomputed rollups
- filtered views often use live aggregation
- both must produce the same biological statistic

Gutter offset:

- usually caused by chart axis values not matching gutter leaf axis values, or
  by not passing the same top/bottom grid bounds to the gutter renderer

Horizontal zoom corrupting vertical zoom:

- handle x-slider `datazoom` events separately from y-slider events

Codon shares not summing to 1:

- check whether denominators count distinct repeat calls
- check whether all synonymous codons for the selected residue are visible
- check whether the imported per-call codon fractions are complete

## Review Checklist

Before opening a PR for a stat-view change:

- backend tests cover empty and populated payloads
- formulas are documented in `docs/statistics.md`
- rollup and live paths match, if both exist
- JavaScript syntax checks pass
- manual browser check covers zoom, tooltips, gutters, and mode switching
- no large stale planning docs were added
