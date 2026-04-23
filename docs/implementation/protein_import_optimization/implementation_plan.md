# Protein Import Optimization Plan

## Context

Large PostgreSQL-backed imports currently spend a noticeable amount of time in the
`Importing retained protein rows` stage. That stage is broader than the label
suggests: it stages `proteins.tsv`, validates references, updates genome protein
counts, stages protein FASTA, checks FASTA coverage, and finally inserts retained
protein rows into `browser_protein`.

The most likely avoidable cost is repeated work against the staged repeat-call
table. Protein import currently treats published proteins as a possible superset
and repeatedly derives retained proteins from
`tmp_homorepeat_import_repeat_calls` inside each acquisition batch import. The
live `Q_run_04_2026` import confirmed that published protein rows are a
superset: some proteins in `proteins.tsv` / `proteins.faa` have no repeat call.
With millions of repeat calls, repeatedly running `DISTINCT` and
`GROUP BY protein_id` can dominate the stage.

## Goals

- Keep the import memory-safe for 100GB+ input artifacts.
- Avoid loading all retained IDs or FASTA records into Python memory.
- Reduce repeated PostgreSQL work during sequence and protein import.
- Make progress status identify the slow substep inside protein import.
- Keep behavior equivalent: same retained rows, same validation failures, same
  stored protein attributes and repeat-call counts.
- Preserve support for acquisition protein outputs that are supersets of called
  proteins.

## Proposed Changes

### 1. Keep Superset Protein Outputs

Continue importing only retained proteins, but stop deriving that retained set
with repeated inline subqueries:

```sql
JOIN (SELECT DISTINCT protein_id FROM tmp_homorepeat_import_repeat_calls) retained
  ON retained.protein_id = staged.protein_id
```

Instead, join the precomputed retained-protein table:

```sql
SELECT staged.protein_id, counts.repeat_call_count
FROM tmp_homorepeat_import_proteins staged
JOIN tmp_homorepeat_import_retained_proteins counts
  ON counts.protein_id = staged.protein_id;
```

Do not fail when a staged protein has no repeat call. Those rows represent
analyzed proteins but are not inserted into `browser_protein`.

### 2. Precompute Repeat-Call Counts Once

Immediately after staging repeat-call rows, create a reusable temp table:

```sql
CREATE TEMP TABLE tmp_homorepeat_import_retained_proteins AS
SELECT protein_id, COUNT(*)::integer AS repeat_call_count
FROM tmp_homorepeat_import_repeat_calls
GROUP BY protein_id;
```

Add indexes:

```sql
CREATE INDEX ... ON tmp_homorepeat_import_retained_proteins (protein_id);
```

Use this table for:

- retained protein count
- protein FASTA coverage checks
- per-protein `repeat_call_count`
- retained-only protein insertion

### 3. Keep Sequence Filtering Unless Its Contract Is Confirmed

The same simplification may apply to sequences if `sequences.tsv` / `cds.fna`
are guaranteed to be limited to retained sequence rows. Do not assume that from
the protein output behavior.

Until confirmed, sequence import should continue filtering against staged repeat
calls, though it can still benefit from a precomputed retained sequence table:

```sql
CREATE TEMP TABLE tmp_homorepeat_import_retained_sequences AS
SELECT DISTINCT sequence_id
FROM tmp_homorepeat_import_repeat_calls;
```

This table can replace repeated inline sequence subqueries:

```sql
JOIN (SELECT DISTINCT sequence_id FROM tmp_homorepeat_import_repeat_calls) retained
```

### 4. Add More Specific Protein Progress States

Split the current broad protein status into substeps:

- `Staging protein TSV rows`
- `Validating protein references`
- `Updating genome analyzed-protein counts`
- `Staging protein FASTA rows`
- `Checking retained protein FASTA coverage`
- `Inserting retained protein rows`

Keep the existing total progress based on retained protein count, but use the
message/stage payload to show the exact substep.

### 5. Consider FASTA Filtering Later

If protein FASTA staging is still the dominant cost after replacing repeated
retained-protein filtering, consider filtering FASTA to retained protein IDs
earlier.

Preferred approach: keep filtering database-backed or use a bounded/chunked
lookup. Avoid a large Python `set` unless measured retained ID counts prove it is
safe for the expected 100GB+ imports.

### 6. Defer Index-Drop/Rebuild Optimization

Bulk inserting into `browser_protein` maintains several indexes and a unique
constraint. Temporarily dropping/rebuilding indexes may speed one-off imports,
but it is more operationally risky and should not be the first change.

## Verification Plan

- Add tests that retained protein rows are imported when they have calls.
- Add tests that staged protein rows without staged repeat calls do not fail and
  are excluded from `browser_protein`.
- Add tests that retained sequence temp tables preserve existing import results,
  unless the sequence output contract is also confirmed retained-only.
- Add tests that protein `repeat_call_count` remains correct.
- Add tests or assertions that progress payloads identify the protein substep.
- Run the full web test suite.
- Re-run a real Docker import and compare timestamps for:
  - sequence import
  - protein TSV staging
  - protein FASTA staging
  - protein insert
  - repeat-call import

## Expected Outcome

The largest expected win is replacing repeated retained-protein filtering with a
single precomputed retained-protein table and computing per-protein repeat-call
counts only once. This should reduce CPU and shared-memory pressure in
PostgreSQL without increasing Python memory use or changing import semantics.
