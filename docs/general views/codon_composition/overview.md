# Codon Composition Viewer Overview

## Purpose

The codon-composition viewer replaces the scalar codon-ratio direction.

Current implementation continuity:

- the existing browser route is `/browser/codon-ratios/`
- the product direction should now be treated as codon composition rather than
  scalar codon ratio

Its job is to answer:

- how codon composition varies across taxa
- how codon mixtures differ by lineage
- how the selected residue's codon composition changes under the current branch
  and filter scope

## Product decisions

### Residue scope

- the product should support all residues
- codon composition remains residue-specific by default
- do not mix residues into one grouped composition in v1
- the viewer should require a residue scope for composition-first analysis

### Data contract

- the browser should use normalized codon-usage rows as the hot-path data
  contract
- the existing source artifacts are the finalized codon-usage TSVs already
  emitted under `publish/calls/finalized/...`
- the web app should import raw and canonical codon-usage rows directly
- do not change `homorepeat_pipeline` for this viewer unless the user
  explicitly approves that boundary change
- `codon_metric_name`, `codon_metric_value`, and `codon_ratio_value` should not
  define the viewer contract

### Aggregation rule

- grouped codon composition should use equal call weight by default
- each call contributes its codon fractions once, regardless of tract length
- absent codons contribute `0` to grouped compositions

### Delivery order

Even though the old codon-ratio page already exists technically, the new work
should treat that route as a migration target rather than a stable product
definition.

## Target 3-tier structure

### `Tier 1 - Overview`

Target chart:

- taxonomy-first `Taxon x Codon` hex overview for one selected residue

Meaning:

- y-axis: lineage-aware taxa or lineage groups
- x-axis: synonymous codons visible in the current residue scope
- cell value: equal-weight mean codon fraction for that taxon and codon
- the overview should share one visual shell with the other first-wave viewers

### `Tier 2 - Browse`

Target chart:

- stacked codon-composition by taxon

Meaning:

- one row per displayed taxon
- each row shows codon shares for the selected residue
- branch drill-down and taxon detail handoff remain first-class

This should be the first shipped composition page because it is structurally
closest to the existing length browse layer while preserving full codon
mixtures.

### `Tier 3 - Inspect`

Target views:

- branch- or taxon-focused codon-composition detail
- composition tables or charts for one lineage or filtered subset
- optional per-call composition preview when needed

## Reuse strategy

- reuse the shared stats page shape from length where it still matches the
  product
- reuse lineage-aware ordering, branch handoffs, and bounded filter semantics
- add composition-specific query and payload helpers rather than forcing codon
  mixtures through scalar summary code
- keep the page meaningful without JavaScript through a grouped composition
  table

## Constraints

- codon composition should be derived from normalized codon-usage rows, not
  from one scalar field
- the viewer must work for residues with 2, 3, 4, or 6 synonymous codons
- visible result sets must stay bounded through residue scope, branch scope,
  rank, `min_count`, and `top_n`
- do not treat a scalar codon-ratio companion view as part of the first-wave
  core product
