# Codon Composition x Length Viewer Overview

## Purpose

This remains the flagship comparison viewer for the first wave, but it is now a
composition-first viewer rather than a scalar codon-ratio comparison page.

Planned route:

- `/browser/codon-composition-length/`

Its job is to answer:

- how codon mixtures change across repeat length bins
- how those composition-length relationships differ by lineage
- which taxa show distinct codon-composition patterns across length

## Why it matters

This viewer combines the two biological signals that motivate the first-wave
family:

- repeat length
- codon composition

It should become the main comparison viewer once the shared codon-usage
contract and codon-composition browse layer exist.

## Dependencies

This viewer should not invent new infrastructure. It depends on:

- the implemented length-view stats foundation
- the normalized codon-usage contract from the codon-composition plan
- shared lineage-order helpers
- shared length-bin helpers
- the same normalized stats filter state used by the other viewers

## Target 3-tier structure

### `Tier 1 - Overview`

Primary chart:

- taxonomy-first `Taxon x Length-bin` hex overview with mini stacked
  composition cells

Meaning:

- each cell represents one taxon and one length bin
- the cell preserves codon mixtures rather than collapsing them to one number
- row order stays lineage-aware
- this is the shared cross-viewer landing shell adapted to composition

### `Tier 2 - Browse`

Primary chart:

- per-taxon composition-across-length panels

Meaning:

- one panel per selected or visible taxon
- x-axis: length bins
- y/stack encoding: codon fractions for the selected residue

This avoids forcing codon mixtures into an unreadable overlaid line plot.

### `Tier 3 - Inspect`

Primary views:

- one selected taxon, branch, or filtered subset
- detailed codon composition across length bins
- supporting table or chart views for one focused lineage

## Deferred companion views

Secondary scalar summaries such as dominance or entropy may still be useful as
companion analytical views, but they should not replace the composition-first
landing state.

## Constraints

- no mixed-residue codon aggregation by default
- no unbounded all-taxa trend plots
- no second filter architecture
- no overview page without lineage-aware ordering
- no scalar color encoding as the primary representation of codon mixtures
