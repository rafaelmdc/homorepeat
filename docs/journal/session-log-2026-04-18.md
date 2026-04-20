# Session Log

**Date:** 2026-04-18

## Objective
- Finish the codon-composition viewer transition by removing old scalar codon-ratio browser code, fixing the codon charts, and making taxon-based views easier to read.
- Add a shared taxonomy gutter design and implementation path that can be reused by future taxon-oriented browser views.

## What happened
- Removed the remaining browser-side scalar codon-ratio compatibility layer and dead helper code from the shared stats path. The live `/browser/codon-ratios/` flow is now composition-first only.
- Fixed the codon overview/browse chart height bug and aligned the zoom behavior with the length view so large taxon sets use a bounded scroll window instead of leaving blank page space.
- Changed codon browse ordering to lineage order instead of raw observation-count order so related taxa stay adjacent.
- Wrote shared taxonomy-gutter planning docs, then implemented the backend rooted visible-tree payload for codon overview and browse.
- Implemented the frontend taxonomy gutter as an ECharts `graphic` cladogram overlay rather than an ECharts `tree` series so it stays aligned with the existing cartesian y-axis and `dataZoom`.
- Tightened the backend tree projection so the gutter structure now keeps only the browser ranks (`phylum`, `class`, `order`, `family`, `genus`, `species`) plus the visible root when needed, instead of preserving arbitrary intermediate taxonomy ranks.

## Files touched
- `apps/browser/stats/filters.py`, `apps/browser/stats/queries.py`, `apps/browser/stats/summaries.py`, `apps/browser/stats/payloads.py`, `apps/browser/stats/__init__.py`
  Removed obsolete scalar codon-ratio browser helpers and simplified the shared composition-first stats path.
- `apps/browser/stats/taxonomy_gutter.py`
  Added the shared rooted taxonomy-gutter payload builder, then refined it to project the visible tree onto browser ranks only.
- `apps/browser/views/stats/codon_ratios.py`, `templates/browser/codon_ratio_explorer.html`
  Wired taxonomy-gutter payloads into the codon overview and browse views.
- `static/js/repeat-codon-ratio-explorer.js`, `static/js/taxonomy-gutter.js`
  Fixed chart sizing/zoom behavior and added the shared rooted cladogram gutter renderer.
- `web_tests/test_browser_stats.py`, `web_tests/test_browser_codon_ratios.py`, `web_tests/support.py`
  Updated shared/browser tests for the composition-only path, lineage ordering, rooted gutter payloads, and rank-limited tree projection.
- `docs/general views/shared_foundation.md`, `docs/general views/codon_composition/overview.md`, `docs/general views/length/overview.md`, `docs/general views/taxonomy_gutter_plan.md`, `docs/general views/taxonomy_gutter_cladogram_refactor.md`
  Documented the shared taxonomy-gutter direction and codon-composition viewer expectations.

## Validation
- Removed-dead-code and stats checks:
  `python -m py_compile apps/browser/stats/__init__.py apps/browser/stats/filters.py apps/browser/stats/payloads.py apps/browser/stats/queries.py apps/browser/stats/summaries.py apps/browser/views/explorer/repeat_calls.py web_tests/test_browser_stats.py web_tests/test_browser_codon_ratios.py web_tests/_browser_views.py`
- JS syntax checks:
  `node --check static/js/taxonomy-gutter.js`
  `node --check static/js/repeat-codon-ratio-explorer.js`
- Targeted Django tests:
  `python manage.py test web_tests.test_browser_stats web_tests.test_browser_codon_ratios`
- Earlier browser regression sweep after codon cleanup:
  `python manage.py test web_tests.test_browser_stats web_tests.test_browser_codon_ratios web_tests.test_browser_lengths web_tests.test_browser_taxa_genomes web_tests.test_browser_proteins web_tests.test_browser_repeat_calls`
- All listed checks passed.

## Current status
- Codon composition is the only active browser implementation path.
- Codon overview and browse now have a shared rooted taxonomy gutter.
- The taxonomy gutter tree is rank-limited to the browser backbone instead of preserving arbitrary taxonomy intermediates.

## Open issues
- No browser-driven visual pass was run after the latest gutter changes, so spacing, readability, and split-label density still need manual review in the live page.
- Route, template, and file naming still use `codon_ratio` in several places even though the behavior is codon composition.
- The current gutter is wired only into codon overview and browse; length and future taxon-based viewers do not reuse it yet.

## Next step
- Do a live browser pass on `/browser/codon-ratios/` and tune the taxonomy gutter spacing, label density, and branch readability.
- Zoomout behaviour slightly de aligns the tree against the data.
- Add a "root" node, instead of just making a line at the pylum level for readibility.
- Add node behavior, when hovering a node/intersection show the label of it, so it's easier to browse.
- Browser level is not aligned, regardless of zoomout.

---

## Taxonomy Gutter Follow-up

**Date:** 2026-04-18

## Objective
- Fix the remaining codon taxonomy-gutter alignment bugs, specifically scroll and scale behavior in the separated left cladogram panel used by overview and browse.

## What happened
- Reviewed the codon composition and taxonomy gutter docs plus ECharts custom-series and `dataZoom` behavior to narrow the failure mode.
- Kept the separated left-panel approach and avoided reverting back to the older overlay path.
- Fixed the gutter disappearing-on-scroll bug by marking the custom gutter series as non-axis-encoded, so its dummy datum no longer falls out of the zoom window during pan.
- Kept the rescale behavior that correctly rebuilds the gutter when the visible row count changes.
- Attempted a viewport-clipping fix so internal nodes that become unary after scroll are collapsed before drawing.
- The remaining bug is still present: after scroll and scale/rescale interactions, cladogram nodes and some connector lines can shift or drift horizontally/structurally when they should stay stable.

## Files touched
- `static/js/taxonomy-gutter.js`
  Added the custom-series `encode` fix for scroll visibility and adjusted viewport node-clipping/collapse logic for the separated cladogram panel.
- `static/js/repeat-codon-ratio-explorer.js`
  Kept the separated panel wiring and the rescale-aware rebuild behavior used by the codon overview and browse charts.

## Validation
- `node --check static/js/taxonomy-gutter.js`
- `node --check static/js/repeat-codon-ratio-explorer.js`
- `python manage.py test web_tests.test_browser_codon_ratios`
- All listed checks passed after the latest gutter changes.

## Current status
- In progress.
- Scroll disappearance is fixed.
- Scale/rescale generally works.
- The scroll/scale bug where cladogram nodes and lines move around when they are not supposed to is still unresolved.

## Open issues
- After scrolling, especially following scale/rescale changes, some internal node markers and branch elbows do not line up with the expected visible tree structure.
- The remaining problem appears to be in how the visible subtree is clipped/reprojected during viewport changes, not in basic chart height or initial row alignment.

## Next step
- Instrument and simplify the visible-subtree projection in `static/js/taxonomy-gutter.js` so the gutter draws from one stable clipped tree model during scroll, instead of mixing full-tree depth with partially visible descendants.
