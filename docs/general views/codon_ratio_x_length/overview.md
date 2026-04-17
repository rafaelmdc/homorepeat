# Codon Ratio x Length Viewer Overview

## Purpose

This is the flagship comparison viewer for the first wave.

Planned route:

- `/browser/codon-ratio-length/`

Its job is to answer:

- how codon ratio changes across repeat length
- how those codon-length relationships differ by lineage
- which taxa show distinct codon-length patterns

## Why it matters

This viewer combines the two signals that motivated the general-views work in
the first place:

- repeat length
- codon ratio

It should become the main comparison viewer once the shared codon contract and
codon-ratio browse layer exist.

## Dependencies

This viewer should not invent new infrastructure. It depends on:

- the implemented length-view stats foundation
- the numeric `codon_ratio_value` contract from the codon-ratio plan
- shared lineage-order helpers
- shared length-bin helpers
- the same normalized stats filter state used by the other viewers

## Target 3-tier structure

### `Tier 1 - Overview`

Primary chart:

- `Taxon x Length-bin Codon Heatmap`

Meaning:

- each cell summarizes codon ratio for one taxon and one length bin
- row order stays lineage-aware
- this is the first biological display, not the pairwise statistical view

### `Tier 2 - Browse`

Primary chart:

- small-multiple trend panels

Meaning:

- one panel per selected or visible taxon
- x-axis: length bins
- y-axis: codon-ratio summary

This avoids overlaying too many lines into a single unreadable plot.

### `Tier 3 - Inspect`

Primary chart:

- 2D binned density view over length and codon ratio

Meaning:

- one selected taxon, branch, or filtered subset
- rectangular bins first
- no true hexbin work unless the simpler version proves insufficient

## Deferred companion view

A pairwise taxon comparison matrix is still valuable, but it should be a later
companion statistical view rather than the main biological landing state.

## Constraints

- no mixed-residue codon aggregation by default
- no unbounded all-taxa line plots
- no second filter architecture
- no overview page without lineage-aware ordering
