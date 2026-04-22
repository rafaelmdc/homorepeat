# Statistics and Scientific Semantics

This document defines the statistics shown by the HomoRepeat browser and the
biological assumptions behind them.

## Filter State

All statistical views use `StatsFilterState` from `apps/browser/stats/filters.py`.
The relevant filters are:

- imported run
- taxonomy branch (`branch=<pk>` or `branch_q=...`)
- display rank
- target search
- repeat detection method
- repeat residue
- length range
- purity range
- minimum observations
- top N visible taxa

Allowed display ranks are:

```text
phylum, class, order, family, genus, species
```

Unscoped views default to class. Branch-scoped views default to species.

## Core Counting Terms

Observation count:

- number of canonical repeat calls in the filtered scope
- for codon composition rollups, only repeat calls with codon-usage rows for the
  selected residue should contribute to codon-share denominators

Species count:

- number of descendant species taxa contributing observations to a display taxon
  or taxon/bin group

Codon fraction:

- imported per repeat call and amino acid
- for one selected residue, synonymous codon fractions partition that residue's
  codon usage
- for a complete residue codon set, fractions should sum to 1 per repeat call

## Taxonomy Grouping

For each repeat call, `TaxonClosure` maps the species taxon to each requested
display-rank ancestor. A display taxon row is therefore a group of descendant
species.

Rows are ordered by lineage after aggregation so biologically related taxa stay
adjacent in charts and tables.

## Length Summaries

Length summary rows are calculated from repeat-call lengths inside each display
taxon:

- minimum length
- q1
- median
- q3
- maximum length

Quantiles use linear interpolation over sorted observed lengths.

The length overview has two pairwise distance modes.

Typical profile:

- each visible taxon is represented by raw repeat lengths
- pairwise distance is Wasserstein-1 over lengths clamped at 50 aa
- distance is normalized by the cap, so values are in `[0, 1]`
- this captures central shape robustly

Tail burden:

- each taxon is represented by:
  `[p(L > 20), p(L > 30), p(L > 50), min(q95 / 50, 1)]`
- pairwise distance is mean L1 distance across those four features
- this captures upper-tail enrichment explicitly

Length inspect:

- active only for branch-scoped views
- displays a CCDF/survival curve: `P(length >= x)`
- reports median, q90, q95, and max for the branch scope

## Length Bins

Codon composition by length uses fixed 5-aa bins:

```text
0-4, 5-9, 10-14, ...
```

The bin start is `(length // 5) * 5`. Visible bins are expanded continuously
between the minimum and maximum occupied bin so chart x-axes remain comparable.

## Codon Composition

Codon composition is residue-scoped. A residue must be selected before codon
composition is biologically meaningful.

For each display taxon and selected residue:

1. For each species, average repeat-call codon fractions for that residue.
2. Average those species-level codon compositions equally across species.
3. Display one codon share per synonymous codon.

This is species-weighted, not raw observation-weighted. A heavily sampled species
does not dominate a display taxon merely because it has more repeat calls.

For a two-codon residue, the codon composition overview uses a signed preference
map. The per-taxon score is:

```text
codon_two_share - codon_one_share
```

The pairwise signed preference cell compares row and column taxon scores. The
tooltip also carries Jensen-Shannon divergence over the codon-share vectors.

For residues with three or more codons, the codon composition overview uses a
pairwise codon-similarity matrix based on Jensen-Shannon divergence.

## Codon Composition by Length

For each display taxon, length bin, and selected residue:

1. Group repeat calls by descendant species and length bin.
2. For each species/bin, average repeat-call codon fractions for that residue.
3. Average the species/bin compositions equally across species.
4. Store/show codon shares for every visible synonymous codon.

For a complete codon set, shares in a taxon/bin should sum to 1, except for
rounding. This is the expected biological interpretation: "within this residue,
what fraction is encoded by each synonymous codon?"

The unfiltered no-branch route may use the precomputed
`CanonicalCodonCompositionLengthSummary` rollup. Filtered routes fall back to
live aggregation from canonical codon-usage rows. Both paths must use the same
species-weighted semantics.

### Overview Modes

Preference:

- available for exactly two visible codons
- cell value is `codon_a_share - codon_b_share`
- range is `[-1, 1]`

Dominance:

- available for three or more visible codons
- dominant codon is the codon with the highest share
- dominance margin is `leading_share - second_share`
- color encodes dominant codon; opacity/strength encodes margin and support

Shift:

- compares adjacent length bins within the same taxon
- for two-codon residues, shift is the absolute change in the first codon's
  share
- for three or more codons, shift is the L1 change across all visible codons

Similarity:

- pairwise trajectory divergence between visible taxa
- for each shared length bin, compute Jensen-Shannon divergence between the
  two codon-share vectors
- pairwise value is the mean divergence across shared bins
- taxa with no shared bins get distance `1.0`

### Browse Panels

Browse panels show per-taxon codon composition trajectories across shared length
bins.

- two-codon residues use line/area traces
- three-or-more-codon residues use stacked composition bars
- a faint support trace shows `bin_observation_count / panel_observation_count`
  on the same 0-100% y-axis
- tooltips report observations, species, and percent of panel total

### Inspect Layer

The inspect layer is branch-scoped. It aggregates the selected branch directly
by length bin and can compare against the parent taxon when available.

Inspect rows show:

- length bin
- observations
- species
- dominant codon
- dominance margin
- codon shares
- shift from previous bin

## Jensen-Shannon Divergence

Jensen-Shannon divergence is calculated as:

```text
M = (P + Q) / 2
JSD(P, Q) = (KL(P || M) + KL(Q || M)) / 2
```

KL terms skip zero-valued entries. The implementation uses log base 2, so values
fall in `[0, 1]` for probability vectors.

## Support Semantics

Support is reported as:

- observation count
- species count
- percent of panel total when panel context exists

Support affects visual confidence but does not change codon-share formulas. Low
support means the estimate is less stable; it does not mean the displayed codon
shares stop being normalized composition values.

## Rollups

Two current-catalog rollup tables exist for unfiltered high-traffic views:

- `CanonicalCodonCompositionSummary`
- `CanonicalCodonCompositionLengthSummary`

They are rebuilt after canonical codon usages are refreshed. The PostgreSQL and
Python rebuild paths must remain equivalent. In particular, codon-by-length
rollups must count distinct repeat calls, not codon-usage rows, when forming
species/bin denominators.

Backfill commands:

```bash
python3 manage.py backfill_codon_composition_summaries
python3 manage.py backfill_codon_composition_length_summaries
```

## Taxonomy Gutter

The taxonomy gutter is an SVG overlay aligned to chart category axes. Payloads
contain:

- rooted visible subtree
- preserved split nodes
- visible leaves in chart order
- brace labels for collapsed child ranks

Chart y-axis category values must be taxon IDs as strings. Labels may format
those IDs back to names, but the gutter aligns by the taxon ID axis value.
