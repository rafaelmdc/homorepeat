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
