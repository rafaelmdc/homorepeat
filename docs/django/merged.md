## Phase 5 — Merged Redesign: Identity-First Derived Statistics

### Summary

- Keep raw storage run-centric and authoritative.
- Redefine merged as a derived biological statistics layer built from raw rows.
- Preserve a strict separation between:
  - raw truth: what each pipeline run imported and called
  - merged summaries: deduplicated biological views built over raw evidence
- Use different merged identity keys depending on the level of summary:
  - protein-level identity: `(accession, protein_id)`
  - residue-specific identity: `(accession, protein_id, residue)`
- Do not use collapsed coordinate-level repeat-call fingerprints as the primary merged identity for biological statistics.
- Exclude rows from merged biological statistics when they lack a trustworthy identity key, while keeping them fully visible in raw mode and provenance views.

### Core Merge Rules

- Canonical raw truth remains unchanged:
  - every imported Genome, Sequence, Protein, and RepeatCall remains attached to its PipelineRun
  - no raw rows are collapsed at import time
  - raw mode remains the authoritative representation of what each run produced

- Merged is a derived layer:
  - merged records are not independent truth entities
  - merged records are summaries computed from raw evidence
  - merged logic may later be optimized or materialized, but its semantics remain derived from raw data

### Merged Identity Rules

- Protein-level merged identity:
  - `merged_protein_key = (accession, protein_id)`
  - used for deduplicated protein prevalence and taxon/accession-level biological summaries

- Residue-specific merged identity:
  - `merged_protein_residue_key = (accession, protein_id, residue)`
  - used for residue-filtered or residue-bucketed summaries
  - distinct residues observed in the same protein, such as Q and N, are not duplicates and must remain distinct at this level

- Identity rule:
  - for merged biological statistics, all raw rows sharing the same merged identity key are treated as evidence for one merged biological unit
  - differences in coordinates, purity, start/end, sequence length, amino-acid string, or minor resequencing/annotation drift do not split merged identity when the relevant identity key is unchanged
  - coordinate-level distinctness is evidence, not merged identity

### Biological Semantics

- Every protein stored in the database is already repeat-positive by admission policy.
- Therefore, merged logic does not decide whether a protein is generally repeat-bearing in the unfiltered database.
- Instead, merged logic decides:
  - how raw evidence is deduplicated into biological summary units
  - how those units are counted in accession/taxon/residue summaries
  - how filtered subsets are derived from contributing evidence

- Protein-level summaries:
  - count each unique `(accession, protein_id)` at most once within the active summary scope
  - if the same protein appears across multiple runs, it remains one merged protein unit

- Residue-specific summaries:
  - count each unique `(accession, protein_id, residue)` at most once within the active summary scope
  - the same protein may therefore contribute to multiple residue-specific merged groups when multiple residues are observed
  - for example, `(accession=A, protein_id=P, residue=Q)` and `(accession=A, protein_id=P, residue=N)` are distinct merged biological units for residue-specific statistics

### Filter Semantics

- Filters do not define identity.
- Filters define inclusion within a derived merged view.

- In merged mode:
  - filters on residue, method, length, purity, or similar criteria determine whether a merged unit is included in the current filtered result set
  - filters do not alter the merged identity key itself

- Unfiltered merged views:
  - protein-level summaries count all deduplicated repeat-positive proteins
  - residue-specific summaries count all deduplicated residue-specific identities present in the evidence

- Filtered merged views:
  - a protein-level merged unit is included when at least one contributing raw row for that protein matches the active filters
  - a residue-specific merged unit is included when at least one contributing raw row for that exact `(accession, protein_id, residue)` identity matches the active filters

### Unkeyed or Untrusted Rows

- If `accession` or `protein_id` is missing, invalid, ambiguous, or otherwise not trustworthy for identity-level deduplication:
  - exclude the row from merged biological statistics
  - keep the row fully visible in raw browsing and provenance views

- If residue is required for a residue-specific merged summary and is missing or untrustworthy:
  - exclude the row from that residue-specific merged summary
  - keep the row fully visible in raw browsing and provenance views

- Merged outputs should surface excluded-row counts so omissions remain visible and auditable.

### Implementation Changes

- Replace the current merged repeat-call identity logic in `apps/browser/merged.py`:
  - stop using call fingerprints as the primary merged identity for biological statistics
  - introduce grouping helpers centered on:
    - `(accession, protein_id)` for protein-level summaries
    - `(accession, protein_id, residue)` for residue-specific summaries
  - treat repeat calls as contributing evidence collected under merged biological units

- Keep merged as a derived-query implementation first:
  - build merged summaries in Python/ORM over raw tables
  - if performance becomes insufficient, promote the same logic into SQL views or materialized structures later without changing semantics

- Split merged outputs into clearly distinct concepts:
  - merged protein statistics: identity-based summaries used for accession/taxon prevalence
  - merged protein-residue statistics: residue-specific summaries used for residue breakdowns and residue-filtered views
  - supporting evidence view: contributing raw repeat calls, including coordinate drift, method differences, sequence variation, and run provenance

### Browser / Presentation Semantics

- Raw mode remains the default authoritative mode.
- Merged mode becomes a deduplicated biological statistics layer.

- Update merged browser semantics in `apps/browser/views.py`:
  - accession merged pages summarize unique merged proteins per accession
  - taxon or branch merged summaries aggregate unique protein-level merged units
  - residue-specific pages aggregate unique protein-residue merged units
  - repeat-related merged pages act as evidence browsers and summary views, not as independent truth entities

- Presentation must not silently use “latest row wins” as biological truth.
- By default, merged pages should present an evidence summary over all contributing raw rows for the merged identity.

- Merged pages should show summary fields such as:
  - accession
  - protein_id
  - residue, when relevant
  - contributing run count
  - contributing raw row / raw call count
  - methods observed
  - coordinate variability or drift summary
  - sequence-length or sequence-variant summary, where relevant
  - links to all contributing raw evidence

- When a single representative raw row must be shown for convenience:
  - treat it as a representative evidence row, not as canonical truth
  - choose it deterministically using a ranking policy
  - prefer most complete / most informative / best-supported rows first
  - use newest run only as a final tie-breaker, not as the semantic definition of the merged unit

### Provenance Requirements

- Every merged record must remain traceable back to raw evidence.
- Every merged record should expose:
  - contributing run count
  - backlinks to contributing raw proteins and repeat calls
  - visibility of coordinate drift and method differences where present
  - excluded-unkeyed counts where relevant

### Public Interface / Labels

- Raw mode labels should emphasize run-attached evidence and provenance.
- Merged mode labels should emphasize deduplicated biological summaries.

- Merged counts should be labeled in terms of:
  - unique accession-protein units
  - unique accession-protein-residue units
  - contributing raw runs
  - contributing raw calls
  - excluded unkeyed rows

- Avoid labels that imply merged records are canonical imported truth rows.

### Test Plan

- The same `(accession, protein_id)` across multiple runs counts once in protein-level merged statistics.
- The same `(accession, protein_id)` with different call coordinates still counts once as one merged protein.
- The same `(accession, protein_id)` with slightly different protein length or sequence still counts once at the protein level.
- Different `protein_id` values under the same accession count as separate merged proteins.
- The same protein with different residues, such as Q and N, counts:
  - once at the protein level
  - once per residue at the residue-specific level
- Multiple raw rows with the same `(accession, protein_id, residue)` across runs count once in residue-specific merged statistics.
- Missing or untrustworthy `protein_id` or accession excludes the row from merged biological statistics but leaves it visible in raw pages.
- Missing or untrustworthy residue excludes the row from residue-specific merged summaries but leaves it visible in raw pages.
- Method, residue, length, and purity filters affect inclusion in filtered merged views, not merged identity itself.
- Merged records expose backlinks to all contributing raw rows and runs.
- Existing raw browser behavior and run replacement behavior remain unchanged.

### Assumptions and Defaults

- `protein_id` on the imported raw protein row is the primary trustworthy protein identifier for deduplication.
- `accession` remains the genome/assembly identity boundary and is part of the merged identity key.
- Residue is part of identity only for residue-specific merged summaries.
- The merged layer is intended for biological prevalence and residue-summary views, not for preserving coordinate-level distinctness as standalone truth.
- Coordinate-level distinctness remains available only in the raw evidence layer.
- The same biological protein may legitimately appear in multiple residue-specific merged groups when distinct repeat residues are observed.
