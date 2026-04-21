# Codon Composition x Length Viewer Overview

## Purpose

This viewer compares codon composition against repeat length across taxa.

Planned route:

- `/browser/codon-composition-length/`

It remains part of the first-wave browser viewer family because it combines the
two main biological signals:

- repeat length
- codon composition

The first-wave design should be **composition-aware**, not "full composition
everywhere". The overview should use simple matrix summaries that are readable
at scale, while the browse and inspect layers preserve full composition detail
where users can actually read it.

Core questions:

- which codon is preferred at each length bin
- how strong that preference is
- where codon composition changes across length
- whether observed patterns are well-supported
- which taxa have similar overall codon-length behavior

## Design Principles

- overview = state, strength, support, change
- browse and inspect = full composition
- lineage-aware taxon ordering is required
- support awareness is required in every tier
- fixed codon order is required in browse and inspect views
- simple matrix summaries are preferred over miniature per-cell detail
- scalar summaries may guide overview reading, but must not replace full
  composition views in browse and inspect

The biological object is still codon composition. The representation changes by
scale:

- Tier 1 summarizes codon composition into readable overview states.
- Tier 2 shows full composition trajectories for selected taxa.
- Tier 3 exposes exact values for one taxon, branch, or focused subset.

## Dependencies

This viewer should not invent new infrastructure. It depends on:

- the implemented length-view stats foundation
- the normalized codon-usage contract from the codon-composition plan
- shared lineage-order helpers
- shared length-bin helpers
- the same normalized stats filter state used by the other viewers

## Current Implementation Note

As of `2026-04-20`, the viewer is intentionally reset to the `CL3.1` baseline.

- the shared non-pairwise chart-shell extraction remains valid
- the first `CL3.2` overview-renderer attempt was reverted
- the codon-length backend bundle itself looked correct on the real dataset
- the failure was in frontend chart binding, not in the biological summary
  contract

The next overview pass should begin with the simplest stable renderer:

- rectangular heatmap-style cells
- simple scalar or categorical encodings
- no miniature composition glyphs
- no frontend-first complexity before the matrix binding is proven

## Target 3-Tier Structure

### `Tier 1 - Overview`

Tier 1 is a simple matrix-based overview with a small number of clear modes.

Shared structure:

- y-axis: taxa in lineage-aware order
- x-axis: shared repeat length bins, or adjacent-bin transitions for shift mode
- cells: compact summaries of codon composition state, strength, support, or
  change
- tooltips: exact codon fractions and support metadata where useful

Tier 1 should not show the full codon mixture inside every `Taxon x Length-bin`
cell. Tiny stacked bars, split tiles, or miniature composition glyphs are not
first-wave defaults because they are too dense to read at scale and too
expensive to render reliably on dense real data.

#### Primary Mode for 2-Codon Residues: `Preference Matrix`

Primary chart:

- `Taxon x Length-bin` signed preference matrix

Encoding:

- each cell shows one continuous signed codon preference score
- negative = codon B preferred
- zero = balanced
- positive = codon A preferred
- stronger color magnitude = stronger preference

This is the preferred overview for polyQ-like 2-codon cases. One codon fraction
implies the other, so a signed scalar preserves direction and strength without
forcing a tiny split bar into every cell.

Support handling:

- every cell must visually reflect support
- acceptable first-wave support encodings:
  - reduced opacity
  - subtle dot or corner marker
  - tooltip support tier
- sparse long bins must not look equally trustworthy as dense central bins

For 2-codon residues, the signed preference matrix is preferred over miniature
split bars as the main Tier 1 representation.

#### Primary Mode for 3+ Codon Residues: `Dominant-Codon Matrix`

Primary chart:

- `Taxon x Length-bin` dominant-codon matrix

Encoding:

- hue/category = dominant codon identity
- intensity, saturation, or border strength = dominance margin
- full mixture is not shown in-cell
- tooltips may expose exact codon fractions and support

This keeps overview cells readable while preserving the two key overview
questions:

- which codon wins
- how decisive that win is

For 3+ codon residues, tiny stacked bars or mini composition glyphs are
explicitly rejected as the default first-wave overview. They may be considered
later only if the simple matrix views are already stable and the real dataset
shows a clear need.

#### Companion Mode: `Composition Shift`

Primary chart:

- `Taxon x Adjacent-length-transition` matrix

Meaning:

- each cell measures how much codon composition changes from one length bin to
  the next
- stable taxa stay visually quiet
- sharp transition points stand out along the length axis

Statistics:

- for 2-codon residues:
  - absolute change in one codon fraction
- for 3+ codon residues:
  - L1 distance between adjacent-bin normalized composition vectors

Default to L1 distance for simplicity and interpretability. JSD can be a later
companion metric, but it is not the first-wave default.

This mode should answer:

- where composition changes sharply across length
- which taxa are stable across length
- which taxa show transition points

#### Optional Companion Mode: `Pairwise Taxa Overview`

Pairwise taxa similarity is useful, but it is secondary.

Primary chart:

- `Taxon x Taxon` distance heatmap

Definition:

- summarize each taxon's codon-length trajectory into a support-aware vector
- compute pairwise taxa distances
- show a distance heatmap for clustering and outlier detection

Constraints:

- this is a secondary comparison view
- it must not replace the main `Taxon x Length-bin` overview
- it should be presented as trajectory similarity, not as the core biological
  representation

Pairwise taxa similarity is too abstract for the landing view because it hides
where along length taxa differ.

### `Tier 2 - Browse`

Tier 2 is where full codon composition is preserved for selected taxa.

Primary chart family:

- per-taxon small multiples across length
- one panel per selected taxon
- fixed x-axis = length bins
- fixed codon order across panels

Recommended view rules:

- for 2-codon residues:
  - line or area chart is preferred
  - do not force tiny internal composition glyphs
- for 3+ codon residues:
  - stacked bars or stacked areas are preferred
  - avoid cluttered multi-line overlays

Support display:

- add a compact support strip or count strip beneath each taxon panel
- sparse bins must remain visibly sparse
- long-bin differences should be easy to distinguish from long-bin uncertainty

Tier 2 should answer:

- how codon composition evolves across length for a selected taxon
- how neighboring or selected taxa compare
- whether long-bin differences are supported

### `Tier 3 - Inspect`

Tier 3 is a focused inspect layer for one taxon, branch, or filtered subset.

Required inspect components:

- one detailed composition-across-length chart
- one exact table

The exact table should include:

- length bin
- codon counts
- codon fractions
- support count
- dominant codon
- dominance margin
- optional entropy or evenness
- optional delta from previous bin

Optional comparison:

- parent branch aggregate
- selected reference taxon
- sibling mean

Tier 3 is where full composition detail and exact values belong.

## Statistical Guidance

### Composition Representation

- codon composition vectors remain normalized within each taxon-length bin
- no mixed-residue codon aggregation by default
- codon order remains fixed across browse and inspect views
- overview summaries must be derived from the same normalized composition
  vectors used by browse and inspect

### Preference Statistics

For 2-codon residues:

- use a signed preference score based on the two codon fractions
- keep codon sign direction fixed and documented in the payload
- expose exact fractions in tooltips and inspect tables

The preference score is the first-wave overview representation because it
preserves direction and strength in one readable scalar.

### Dominance Statistics

For 3+ codon residues:

- compute dominant codon per taxon-length bin
- compute dominance margin between the top codon and the next strongest codon
- use dominance margin for visual strength
- expose full fractions in tooltips, browse, and inspect

### Shift Statistics

For adjacent-bin composition change:

- 2-codon residues:
  - use absolute change in one codon fraction
- 3+ codon residues:
  - use L1 distance between normalized codon-composition vectors

Default to simple, transparent measures. Do not introduce JSD as the first-wave
default unless a later analysis shows L1 is insufficient.

### Support Handling

Every taxon-length bin should retain support metadata such as:

- observation count
- optional count tier classification
- species count where available

Support should inform rendering and interpretation throughout the page. Sparse
long bins must not visually read as equally reliable as dense central bins.

## Practical Implementation Guidance

The first implementation pass should prioritize the simplest renderer path.

- start with rectangular heatmap-style cells
- wire the backend summary contract into a simple matrix first
- prove row, bin, and tooltip binding on the real dataset
- avoid taxonomy gutter complexity in the first pass unless the shared gutter
  path is already stable for this chart shape
- do not implement miniature SVG composition glyphs as the first overview
  renderer
- do not add rich support ornamentation until the base matrix is correct
- only add richer visual details after the simple version works well on dense
  real data

Implementation should remain backend-contract first:

- the backend owns taxon order
- the backend owns length-bin order
- the backend owns codon order
- the frontend renders those ordered arrays without inventing a second
  classification or binning contract

## Non-Goals And Explicit Rejections

First-wave defaults should not include:

- tiny composition glyphs in every overview cell
- miniature stacked bars as the default main matrix encoding
- overviews that hide support
- pairwise taxa heatmaps as the landing state
- scalar-only summaries replacing Tier 2 and Tier 3 composition views
- complex frontend-first rendering before a simple matrix path works
- mixed-residue codon aggregation
- a second filter architecture
- unbounded all-taxa trend plots

## Recommended First-Wave Outcome

### Tier 1

- for 2-codon residues:
  - signed preference matrix
- for 3+ codon residues:
  - dominant-codon matrix with dominance strength
- composition shift matrix
- support-aware cells
- lineage-aware ordering
- optional secondary pairwise taxa similarity tab

### Tier 2

- per-taxon small multiples across length
- line or area chart for 2-codon residues
- stacked bars or stacked areas for 3+ codon residues
- support strip under each panel

### Tier 3

- detailed composition-across-length chart
- exact table
- optional lineage comparison

## Summary

This viewer should not force full codon mixtures into every overview cell.

The first-wave page should use simple graphs that work on dense real data:

- signed preference for 2-codon residues
- dominant codon plus dominance strength for 3+ codon residues
- adjacent-bin shift for transition detection
- support-aware rendering throughout
- full composition detail in browse and inspect

That makes the viewer composition-aware without making the overview visually
overloaded or technically fragile.
