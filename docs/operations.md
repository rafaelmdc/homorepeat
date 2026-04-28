# Operations

## Management Commands

All commands can be run directly or inside the Compose stack:

```bash
# Direct
python3 manage.py <command>

# Inside Compose
docker compose exec web python manage.py <command>
```

**Migrate:**

```bash
python3 manage.py migrate
```

**Import a published run:**

```bash
python3 manage.py import_run --publish-root /absolute/path/to/<run>/publish
```

The manifest at `metadata/run_manifest.json` must include `publish_contract_version: 2`. Required v2 files are `calls/repeat_calls.tsv`, `calls/run_params.tsv`, the TSVs under `tables/`, summaries under `summaries/`, and the manifest under `metadata/`.

**Process the oldest queued import:**

```bash
python3 manage.py import_run --next-pending
```

**Rebuild canonical catalog metadata:**

```bash
python3 manage.py backfill_canonical_catalog
python3 manage.py backfill_browser_metadata
```

**Rebuild codon rollups:**

```bash
python3 manage.py backfill_codon_composition_summaries
python3 manage.py backfill_codon_composition_length_summaries
```

## Import and Rollup Maintenance

The canonical catalog sync rebuilds codon composition summaries, codon composition by length summaries, and canonical protein repeat-call counts.

If codon share values in an unfiltered view do not match a filtered/branch view, rebuild the relevant rollup table and compare against live aggregation. Unfiltered views are the most likely to use rollups.

For codon-by-length summaries, shares for a complete residue codon set should sum to 1 within each taxon/bin (within rounding). If they do not, check for:

- stale rollup rows
- denominator bugs that count codon-usage rows instead of distinct repeat calls
- incomplete or invalid imported codon fractions

## Cache Behaviour

Stats bundles and taxonomy gutter payloads are cached using a hash of the validated filter state. TTL is controlled by `HOMOREPEAT_BROWSER_STATS_CACHE_TTL` (default: 60 seconds).

Taxonomy gutter payloads also carry a local version constant in `apps/browser/stats/taxonomy_gutter.py`. Bump it when changing payload shape or alignment semantics.

## Validation Checklist

Before merging statistical or chart changes:

```bash
python3 manage.py test web_tests.test_browser_stats
python3 manage.py test web_tests.test_browser_lengths
python3 manage.py test web_tests.test_browser_codon_ratios
python3 manage.py test web_tests.test_browser_codon_composition_lengths
```

For frontend chart changes:

```bash
node --check static/js/stats-chart-shell.js
node --check static/js/taxonomy-gutter.js
node --check static/js/pairwise-overview.js
node --check static/js/repeat-length-explorer.js
node --check static/js/repeat-codon-ratio-explorer.js
node --check static/js/codon-composition-length-explorer.js
```

Manual browser checks should cover:

- unfiltered and branch-scoped routes
- two-codon and multi-codon residues
- y-axis wheel pan and Shift+wheel zoom
- horizontal x-axis sliders where present
- taxonomy gutter alignment after zoom
- no-JS fallback tables where relevant

## Database Notes

PostgreSQL is the production-like path. Large v2 imports stream run-level TSVs into temporary tables with `COPY` and join in SQL. SQLite is a lightweight fallback for compact fixtures and parser checks; it does not exercise the PostgreSQL staging path or SQL rollup rebuilds.

When changing raw SQL rollups, validate both the PostgreSQL rebuild command in the Compose stack and the Django tests using the Python/live fallback.

For a real v2 import validation:

```bash
docker compose exec web python manage.py import_run \
  --publish-root /workspace/homorepeat_pipeline/runs/<run-id>/publish
```

Then compare source table row counts against imported raw counts for repeat calls, matched sequences, matched proteins, repeat-call codon usage, repeat context, and operational tables. Confirm canonical sequence/protein bodies are populated after sync and codon rollups rebuild successfully.
