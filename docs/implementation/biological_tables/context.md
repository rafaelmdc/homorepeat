# Biological Tables Context

## Purpose

The current HomoRepeat browser is useful for auditability, but many of its
primary list views still read like the database schema. Users can browse
accessions, genomes, sequences, proteins, repeat calls, imported runs, and
operational tables, but the main scientific question is one level higher:

- what homorepeat was found?
- where did it occur biologically?
- what is the repeat architecture?
- what codons encode the target repeat residues?

This project adds two biology-first browser tables that should become the main
scientific browsing surfaces:

- **Homorepeats**
- **Codon Usage**

Existing canonical catalog, raw provenance, and operational views should remain
available. They should become supporting views for drill-down, auditing, import
debugging, and advanced investigation rather than defining the default browsing
experience.

## Design Principle

These tables are biological observation tables, not provenance tables.

A biologist should be able to scan the default columns without understanding
the raw/canonical split, import batches, internal primary keys, or pipeline
side-artifact layout.

Default columns should emphasize compact biological meaning:

- organism and source assembly
- protein or gene target
- repeat class and length
- compact repeat architecture
- purity and protein position
- codon profile and dominant codon where relevant
- detection method

Implementation and provenance information should still be reachable from row
details, links, advanced catalog pages, or TSV downloads.

## Homorepeats Table

The Homorepeats table answers:

> What repeat was found, in what organism/genome/protein, and what is its
> biologically relevant structure?

It should be based on the current canonical repeat catalog. One row should
represent one canonical repeat observation.

### Default Columns

- **Organism**: species or source organism, preferably from the repeat call's
  taxon/species context.
- **Genome / Assembly**: compact genome or assembly accession.
- **Protein / Gene**: protein name/accession with gene symbol when available.
- **Repeat class**: main repeated amino acid, such as `Q`, `A`, `P`, `N`, or
  `G`.
- **Length**: total detected repeat-region length, including accepted
  interruptions.
- **Pattern**: compact amino-acid run-length representation of the repeat
  region.
- **Purity**: target residue count divided by total repeat-region length.
- **Position**: simple placement in the protein, preferably percentage through
  the protein or a broad N-terminal/middle/C-terminal region.
- **Method**: detection method used.

### Pattern

`Pattern` is CIGAR-like in spirit, but describes amino-acid repeat
architecture rather than alignment operations. It should compact consecutive
amino-acid runs inside the detected repeat region:

```text
42Q
18Q1A12Q
10A1G9A
7P1A8P1S5P
```

The full repeat sequence should not be a default table column because it is
visually noisy. It should be available in row details and TSV downloads.

## Codon Usage Table

The Codon Usage table answers:

> What codons make up the amino-acid repeat, and how strongly is one codon
> preferred?

This table should be biology-first, not a raw codon-usage SQL table. One row
should represent a repeat's codon profile for the target repeat class. The row
may be backed by multiple canonical codon-usage rows.

### Default Columns

- **Organism**: species or source organism.
- **Genome / Assembly**: compact genome or assembly accession.
- **Protein / Gene**: protein name/accession with gene symbol when available.
- **Repeat class**: amino acid being analyzed, such as `Q`.
- **Length**: total detected repeat-region length.
- **Pattern**: same compact repeat architecture used by the Homorepeats table.
- **Codon coverage**: number of target repeat residues with resolvable codons.
- **Codon profile**: compact percentage profile, such as `CAG 86%, CAA 14%`.
- **Codon counts**: actual counts, such as `CAG 36 / CAA 6`.
- **Dominant codon**: most frequent codon.
- **Method**: detection method used.

### Interrupted Repeats

For interrupted repeats, codon usage must stay scoped to the target repeat
class.

Example:

```text
Pattern: 18Q1A12Q
Length: 31
Target repeat class: Q
Target Q residues: 30
Codon counts: CAG 20 / CAA 10
Codon coverage: 30/30
Codon profile: CAG 67%, CAA 33%
Dominant codon: CAG
```

The `A` interruption is part of the repeat-region pattern and length, but it is
not part of the Q codon profile.

The full codon sequence should not be a default table column. It should be
available in row details and TSV downloads.

## Default-Hidden Content

Do not prioritize these fields in the default table views:

- full lineage
- protein description
- run ID
- import batch
- internal database IDs
- raw or canonical primary keys
- full provenance
- nucleotide/CDS coordinates
- nucleotide flanks
- amino-acid flanks
- full repeat sequence
- full codon sequence

These can appear in row details, advanced catalog/provenance views, admin
views, or downloads.

## Row Details

Row detail pages or expandable rows should expose information that is useful
but too noisy for the default table:

- full repeat sequence
- full codon sequence when available
- amino-acid and nucleotide flank context where available
- protein start/end coordinates
- source sequence/protein/genome links
- lineage/taxon links
- latest run and supporting raw observation provenance
- links into existing length and codon composition explorers with matching
  filters

## Downloads

TSV downloads should represent the full filtered data scope, not just visible
rows. They should include the compact display fields plus scientifically useful
complete fields:

- full repeat sequence
- full codon sequence where available
- codon counts and fractions in a parseable form
- source organism, assembly, protein, gene, method, length, purity, and
  position
- stable source identifiers needed for reproducible downstream analysis

Downloads may include selected provenance fields, such as latest run, when they
help reproduce the catalog state. These fields should not drive the default UI.

## Open Questions For Implementation

The implementation agent should inspect the current code before finalizing the
technical approach for these items:

- whether `Pattern` should be computed in a small presentation helper, queryset
  annotation, or cached property-like adapter
- exact `Position` display format: percentage midpoint, start-end percent
  range, broad region label, or a combined compact value
- whether Codon Usage should show only profiles for the repeat call's own
  `repeat_residue` or allow additional amino-acid profiles when present
- how much provenance to include in downloads without making them feel like raw
  table exports
- whether the existing repeat-call detail page should become the Homorepeat
  detail page or be linked as a provenance/detail variant
