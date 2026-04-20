# Codon Composition Viewer Slices

## Status

The codon-composition viewer is frozen at its MVP browser behavior.

This document no longer describes the old implementation plan as open work. It
records what shipped in the MVP and what remains explicitly deferred.

Boundary rule:

- do not modify `homorepeat_pipeline` as part of codon browser work unless the
  user explicitly approves that change
- keep using the finalized codon-usage artifacts already imported into the
  browser data model

## Shipped in the MVP

### `CC1` Composition-first data contract

Shipped behavior:

- the live browser path depends on normalized codon-usage rows
- codon composition is residue-scoped
- the old scalar codon-ratio browser contract is no longer the live page model

Closed outcome:

- composition queries use imported codon-usage data directly

### `CC2` Composition-first route replacement

Shipped behavior:

- the existing route remains `/browser/codon-ratios/`
- route and file naming still say `codon_ratio` for continuity
- the page behavior is codon composition only

Closed outcome:

- the legacy route now serves the composition viewer contract

### `CC3` Grouped composition fallback table

Shipped behavior:

- the page remains useful without JavaScript
- grouped taxon rows show residue-scoped codon shares and call counts
- branch and taxon handoffs remain available from the grouped table

Closed outcome:

- codon composition is browseable through the server-rendered table alone

### `CC4` Overview layer

Shipped behavior:

- 2-codon residues use a signed `Taxon x Taxon` preference-difference heatmap
- residues with more visible codons use a pairwise `Taxon x Taxon` similarity
  heatmap based on `1 - Jensen-Shannon divergence`
- both axes use the same lineage-ordered visible taxon set
- the overview reuses the shared taxonomy gutter

Closed outcome:

- the page has a lineage-aware overview for the current visible taxon set

MVP note:

- this is the frozen MVP exception to the original `Taxon x Codon` overview
  target

### `CC5` Browse layer

Shipped behavior:

- the browse chart is a stacked codon-composition view by visible taxon
- the chart, grouped table, and taxonomy gutter use the same visible taxon set
- visible rows are lineage-ordered instead of count-sorted

Closed outcome:

- grouped codon composition is visually comparable across many taxa

### `CC6` Inspect layer

Shipped behavior:

- inspect activates only when branch scope is active
- inspect shows one branch-scoped aggregated composition view
- inspect is not a per-call browser in the MVP

Closed outcome:

- the composition viewer spans overview, browse, and inspect layers without
  reintroducing the old scalar model

### `CC7` Taxonomy ordering and gutter stabilization

Shipped behavior:

- overview and browse use the shared rooted taxonomy gutter
- visible taxa follow the shared lineage-aware ordering helper
- high-level Metazoa/root-linked phyla now use a curated sibling order instead
  of effectively arbitrary root ordering

Closed outcome:

- taxon-oriented codon views now preserve a more biologically coherent order

### `CC8` Heatmap performance stabilization

Shipped behavior:

- the backend emits a compact pairwise matrix payload
- the frontend renders only the current visible zoom window of the overview
- large windows disable expensive cell styling

Closed outcome:

- large visible taxon sets are materially faster to render in the browser

## Deferred after the MVP

### `CC9` Replace the overview with `Taxon x Codon`

Deferred work:

- redesign the overview around lineage-ordered taxa by visible codon
- make the overview match the original shared-shell target instead of the
  current pairwise taxon matrix

Reason deferred:

- this is a product-visible redesign, not a small stabilization patch

### `CC10` Rename the route and implementation surface

Deferred work:

- rename `/browser/codon-ratios/`
- rename `codon_ratio` templates, view classes, and frontend assets

Reason deferred:

- naming cleanup is not required to keep the MVP correct or usable

### `CC11` Richer inspect and handoff behavior

Deferred work:

- per-call composition previews
- broader browser-home and detail-page handoffs
- richer drill-down states beyond branch-scoped aggregate composition

Reason deferred:

- current inspect behavior is sufficient for the MVP browser contract
