# Session Log

**Date:** 2026-04-19

## Objective
- Fix the codon taxonomy gutter alignment bug where the cladogram stayed
  vertically offset from the overview heatmap rows and browse stacked-bar rows.
- Preserve the rooted visible-tree backend payload and the current codon viewer
  behavior while replacing only the unstable frontend rendering path.

## What happened
- Confirmed the visible taxon order was already correct, so the remaining bug
  was not a row-order mismatch.
- Tried several narrower frontend fixes first:
  - visible-subtree reprojection for clipped zoom windows
  - explicit zoom-window row clipping
  - switching back from the separated panel to the old ECharts overlay path
  - different y-position sources (`convertToPixel`, grid-rect band math, direct
    axis-object coordinates)
- The bug remained a stable vertical offset across zoom levels, which strongly
  suggested an ECharts layout-contract mismatch rather than a simple math bug.
- Pivoted the taxonomy gutter off ECharts rendering entirely:
  - kept the rooted-tree backend payload
  - kept the shared gutter-width calculation and zoom/window logic
  - replaced the ECharts gutter renderer with a DOM `SVG` overlay anchored to
    the chart container
  - passed explicit chart `top`, `bottom`, and `gutterWidth` values from the
    codon chart config into the gutter renderer
- The SVG gutter now draws connectors, nodes, labels, and braces from one
  explicit visible-row model, using one visible row = one row center.
- After the SVG pivot, the gutter aligned correctly against both codon charts.

## Files touched
- `static/js/taxonomy-gutter.js`
  Replaced the practical gutter rendering path with a DOM `SVG` overlay and
  kept the rooted-tree projection plus shared width/layout helpers.
- `static/js/repeat-codon-ratio-explorer.js`
  Stopped using the ECharts-driven gutter render paths and passed explicit
  layout bounds into the new SVG overlay renderer for overview and browse.
- `docs/general views/taxonomy_gutter_plan.md`
  Updated the frontend contract to describe the SVG overlay approach instead of
  ECharts `graphic`/`custom` series rendering.
- `docs/general views/taxonomy_gutter_cladogram_refactor.md`
  Updated the renderer/refactor notes to record the practical pivot away from
  ECharts-driven gutter geometry.

## Validation
- `node --check static/js/taxonomy-gutter.js`
- `node --check static/js/repeat-codon-ratio-explorer.js`
- `python manage.py test web_tests.test_browser_codon_ratios`
- Manual browser confirmation from the user:
  the SVG gutter alignment works after the pivot.

## Current status
- Done.
- Codon overview and browse now use the rooted taxonomy gutter through a stable
  SVG overlay instead of ECharts-driven gutter rendering.

## Open issues
- The SVG gutter path is currently wired only into the codon overview and
  browse charts.
- Spacing/readability polish may still be worth a follow-up pass now that the
  alignment bug is closed.

## Next step
- Treat the SVG overlay renderer as the default shared gutter path and only
  generalize/reuse it in other viewers after a small polish pass.

---

# Session 2 — 2026-04-19 (continuation)

## Objective
- Polish the bottom tree in the taxonomy gutter (label rotation, placement, and order).
- Improve the codon ratio chart legend layout.
- Extract grouped-taxa pagination into a shared helper and apply it to the codon-ratio explorer.
- Fix mousewheel behaviour in both explorer charts so plain scroll pans and Shift+scroll zooms.

## What happened

### Bottom tree label fixes (`taxonomy-gutter.js`)
- **Rotation direction:** labels were rotating clockwise (downward); fixed to
  `rotate(-90)` so they read upward, matching the side-gutter convention.
- **Label placement:** labels were rendering below the tree instead of above it.
  Root cause was that `makeY` started at `bottomTop + BOTTOM_TREE_PADDING` with
  labels placed after the root. Fixed by computing a `labelSectionHeight`
  (gap + leaf label extent + brace label extent + bottom padding) and shifting
  the tree down by that amount, placing labels at `bottomTop + BOTTOM_LABEL_GAP`.
  Connector direction was also reversed to run from the label bottom down to the
  node, not from node upward.
- **Brace/leaf order:** brace annotations (the `{` taxon grouping labels) are now
  rendered above leaf names, with leaf names below — previously they were in the
  wrong order.

### Codon ratio legend layout (`repeat-codon-ratio-explorer.js`)
- Widened `currentOverviewMargins.right` to give the visualMap legend more room.
- Repositioned both `visualMap` blocks (`right`, `itemWidth`, `itemHeight`,
  shortened label text) and both `dataZoom` slider blocks (`right: 8`) so the
  legend no longer overlaps the slider.

### Shared grouped-taxa pagination
- Extracted `summaryPageStatus` and `mountSummaryTablePagination` (plus the
  local `clamp`/`positiveInteger` helpers they need) from
  `repeat-length-explorer.js` into a second self-contained IIFE at the end of
  `site.js`. The function bails immediately when `[data-summary-section]` is
  absent, so it has no effect on pages that don't use it.
- Removed the now-duplicate functions and the explicit call from
  `repeat-length-explorer.js`; `site.js` fires them on every page's
  `DOMContentLoaded`.
- Added the required data attributes to `codon_ratio_explorer.html`: 
  `data-summary-section data-summary-page-size="25"` on the section,
  `data-summary-table-body` on the tbody, `data-summary-row` on each `<tr>`,
  and a `<nav>` pagination bar (Previous / status span / Next) matching the
  lengths template exactly.

### Mousewheel behaviour overhaul (both explorer JS files)
- Earlier attempts using ECharts' `zoomOnMouseWheel: "ctrl"` / `"shift"` options
  were unreliable: zoom still triggered at boundaries during fast scrolling, and
  the modifier-key filter on the slider was ignored when the cursor was over
  chart cells.
- Replaced ECharts' built-in wheel handling entirely:
  - `inside` dataZoom: `zoomOnMouseWheel: false`, `moveOnMouseWheel: false`.
  - `slider` dataZoom: `zoomOnMouseWheel: false`.
  - Added `installWheelHandler(chart, rowCount, getCurrentZoomState)` in each
    file, registered with `{ passive: false, capture: true }` so it intercepts
    events in the capture phase — before ECharts sees them — regardless of
    whether the cursor is over a cell, empty chart area, or the slider.
  - **Plain scroll:** pans the zoom window by 20 % of its current size.
  - **Shift+scroll:** zooms toward the mouse cursor position.
    `chart.convertFromPixel` maps the cursor Y to a row index; the new window
    expands or contracts by 15 % of current size while keeping the row under the
    cursor proportionally fixed.

## Files touched
- `static/js/taxonomy-gutter.js`
  Rotation direction, `labelSectionHeight` placement, brace-before-leaf order.
- `static/js/repeat-codon-ratio-explorer.js`
  Legend layout; `installWheelHandler` added and called for overview and browse
  charts; inside/slider wheel options disabled.
- `static/js/repeat-length-explorer.js`
  Removed duplicate pagination functions; `installWheelHandler` added and called;
  inside/slider wheel options disabled.
- `static/js/site.js`
  Second IIFE appended with the shared `mountSummaryTablePagination` helper.
- `templates/browser/codon_ratio_explorer.html`
  Pagination data attributes and nav bar added to the grouped-taxa section.
- `CLAUDE.md`
  Created by `/init` at the start of the session.

## Validation
- Manual browser confirmation from the user: pagination and wheel behaviour work.

## Current status
- Done.

## Open issues
- Mousewheel pan/zoom direction may need tuning if the user finds scroll-down
  pans in the wrong direction relative to the Y axis orientation.

## Next step
- None open from this session.
