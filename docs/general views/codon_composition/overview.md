# Codon Composition Viewer Overview

## Purpose

The codon-composition viewer is now frozen at its MVP browser contract.

Current implementation continuity:

- the existing browser route remains `/browser/codon-ratios/`
- route and file naming still use `codon_ratio` for continuity, but the page is
  codon composition only
- the old scalar codon-ratio browser direction is no longer part of the live
  page contract

Its job is to answer:

- how grouped codon composition varies across taxa for one selected residue
- how visible taxa compare to one another through a lineage-aware overview
- how the selected residue's codon composition changes inside the current
  branch-scoped subset

## Product decisions

### Residue scope

- the product supports all residues exposed by the imported catalog
- codon composition remains residue-specific by default
- do not mix residues into one grouped composition summary in the MVP
- the viewer requires a residue selection to activate composition-first
  analysis

### Data contract

- the browser uses normalized codon-usage rows as the hot-path data contract
- the existing source artifacts are the finalized codon-usage TSVs already
  emitted under `publish/calls/finalized/...`
- the web app imports raw and canonical codon-usage rows directly
- do not change `homorepeat_pipeline` for this viewer unless the user
  explicitly approves that boundary change
- `codon_metric_name`, `codon_metric_value`, and `codon_ratio_value` do not
  define the live browser contract

### Aggregation rule

- grouped codon composition uses equal call weight by default
- each call contributes its codon fractions once, regardless of tract length
- absent codons contribute `0` to grouped compositions

### Ordering rule

- visible taxa stay lineage-aware by default
- the shared ordering helper now includes a curated Metazoa sibling order so
  root-linked phyla do not appear effectively arbitrary in the browser
- outside the curated Metazoa backbone, ordering falls back to the stable
  lineage helper behavior already used by the browser

## Frozen MVP structure

### `Tier 1 - Overview`

Current shipped chart:

- if the selected residue has exactly 2 visible codons:
  signed `Taxon x Taxon` preference-difference heatmap
- otherwise:
  pairwise `Taxon x Taxon` codon-similarity heatmap

Meaning:

- both axes use the same lineage-ordered visible taxa
- 2-codon residues show signed balance difference
  (`codonTwo - codonOne`) between row and column taxa
- residues with 3, 4, or 6 visible codons show pairwise similarity as
  `1 - Jensen-Shannon divergence`
- the overview reuses the shared taxonomy gutter and the same visible taxon set
  as the browse layer

Performance behavior:

- the backend still computes a bounded pairwise matrix for the visible taxa
- the frontend renders only the current visible zoom window of that matrix
  instead of repainting the entire `n x n` grid on every interaction
- large windows drop per-cell borders and heavy emphasis styling to keep the
  chart usable in the browser

### `Tier 2 - Browse`

Current shipped chart:

- stacked codon-composition by visible taxon

Meaning:

- one row per displayed taxon
- each row shows residue-scoped codon shares for the visible synonymous codons
- the chart, grouped HTML table, and taxonomy gutter all use the same visible
  lineage-ordered taxa
- branch drill-down and taxon detail handoff remain first-class

### `Tier 3 - Inspect`

Current shipped view:

- branch-scoped aggregated codon-composition detail

Meaning:

- the inspect layer activates only when branch scope is active
- it shows one aggregated residue-specific codon mixture for the current branch
  subset
- it is not a per-call inspector in the MVP

## Page contract

- the page stays useful without JavaScript through the grouped composition
  table
- the summary table and the stacked chart describe the same visible taxon set
- filters currently exposed in the page UI are:
  target search, run, branch search, display rank, method, residue, length
  range, minimum observations, and `top_n`
- visible result sets stay bounded through residue scope, branch scope, rank,
  `min_count`, and `top_n`

## Explicit MVP freeze

The codon-composition MVP stops here.

Frozen MVP behavior:

- composition-first route remains `/browser/codon-ratios/`
- overview remains the current pairwise taxon heatmap, not a `Taxon x Codon`
  hex map
- browse remains the stacked taxon composition plus grouped HTML fallback table
- inspect remains the branch-scoped aggregate composition chart
- shared taxonomy gutter and lineage-aware ordering are part of the frozen
  browser contract

Deferred beyond the MVP:

- `Taxon x Codon` overview redesign
- route/template/file renaming away from `codon_ratio`
- broader discoverability and handoff cleanup
- richer inspect views such as per-call composition previews
