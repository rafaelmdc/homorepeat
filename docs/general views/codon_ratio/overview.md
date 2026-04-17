# Codon Ratio Viewer Overview

## Purpose

The codon-ratio viewer is the first new viewer that should reuse the implemented
length-view foundation.

Planned route:

- `/browser/codon-ratios/`

Its job is to answer:

- how codon ratio varies across taxa
- how codon behavior differs by lineage
- how codon summaries change across the currently selected residue and branch
  scope

## Product decisions

### Residue scope

- the product should support all residues
- codon summaries stay residue-specific by default
- do not mix residues into one codon-ratio aggregate in v1

### Codon metric contract

- keep `codon_metric_name` and `codon_metric_value` as provenance
- add and use a numeric `codon_ratio_value` for viewer queries
- expose a `codon_metric_name` selector only when more than one metric exists
  inside the current scope

### Delivery order

Even though the top-level conceptual overview is a heatmap, implementation
should start with the browse layer because it reuses the current length-view
page shell and stats service structure.

## Target 3-tier structure

### `Tier 1 - Overview`

Target chart:

- `Taxon x Length-bin Codon Heatmap`

Meaning:

- y-axis: lineage-aware taxa or lineage groups
- x-axis: length bins
- color: mean or median `codon_ratio_value`

### `Tier 2 - Browse`

Target chart:

- ranked codon-ratio summary by taxon

Meaning:

- one row per displayed taxon
- count plus interval summary for codon ratio
- branch drill-down and taxon detail handoff

This should be the first shipped codon page because it is structurally closest
to the existing length explorer.

### `Tier 3 - Inspect`

Target charts:

- histogram-style codon-ratio distribution
- boxplot-style summary for one taxon, clade, or filtered subset

## Reuse strategy

- reuse the shared stats filter state and page pattern from length view
- reuse grouped-summary and payload helpers where possible
- reuse lineage-aware ordering and binning helpers from the shared foundation
- do not fork a separate codon-specific filter architecture

## Constraints

- codon queries should operate on numeric `codon_ratio_value`, not repeated
  text casting
- null codon values should fall out naturally through filtering and empty
  states
- the first page should remain useful with JavaScript disabled
- codon summaries should remain bounded by branch scope, rank, `min_count`, and
  `top_n`
