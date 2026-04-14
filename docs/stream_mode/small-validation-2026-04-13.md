# Stream-Mode Small Validation 2026-04-13

## Summary

This note records a small-dataset validation pass for the stream-mode rebuild
track.

It is not the `4.1` large-run validation artifact. It is a preflight check on
the existing small test datasets only, used to verify that the streamed
rebuild and worker-hardening slices are stable before spending time on the real
`chr_all3_raw_2026_04_09` import.

## Validated Behavior

The small test suites exercised the following stream-mode concerns:

- merged rebuild now processes accession-scoped repeat-call reads
- rebuild query shapes do not introduce an unnecessary `ORDER BY`
- replace-existing imports remove stale merged accessions correctly
- `backfill_merged_summaries` still populates, skips, and force-rebuilds as
  expected
- the background import worker logs unexpected failures and keeps polling
- `import_worker --once` still raises on unexpected failures

## Commands Run

```bash
python manage.py test web_tests.test_browser_merged
python manage.py test web_tests.test_import_commands
python manage.py test web_tests.test_import_process_run
python manage.py test web_tests.test_browser_metadata
```

## Results

- `web_tests.test_browser_merged`: `35` tests passed
- `web_tests.test_import_commands`: `7` tests passed
- `web_tests.test_import_process_run`: `14` tests passed
- `web_tests.test_browser_metadata`: `7` tests passed

Total for this pass: `63` tests passed.

## Notes

One latent fixture mismatch surfaced during this pass:

- `create_imported_run_fixture()` always rebuilt merged rows
- the metadata backfill test expected raw imported rows without prebuilt merged
  rows

That fixture contract is now explicit through `rebuild_merged=False` in the
backfill-population test path. This was a test compatibility fix for the small
validation pass, not a change to the stream-mode runtime contract.

## Remaining Work

`4.1` remains pending.

The remaining required validation is still the real large-run check against
`chr_all3_raw_2026_04_09` under the Compose/Postgres stack, plus a dated note
recording whether stream mode resolves the original memory failure on the
target hardware envelope.
