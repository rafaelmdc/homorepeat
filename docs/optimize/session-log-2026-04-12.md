# Session Log

**Date:** 2026-04-12

## Objective

- Continue the optimize track on `rehaul`
- carry the raw-browser pass from metadata/page-chrome cleanup through the raw
  query-path slices and the large-run acceptance/profile pass
- leave the repo in a state where the next session can move on without
  re-deriving branch status

## What happened

- Implemented slices `1.2`, `1.3`, `2.1`, `2.2`, `2.3`, and `2.4`:
  - persisted `PipelineRun.browser_metadata`
  - added metadata fallback/backfill support
  - moved run summaries and raw facets off the hot request path
  - replaced branch dropdowns with `branch_q`
  - made hot raw fragment payloads tolerate missing `count`
- Implemented slice `3.1`:
  - aligned raw default orders for sequences, proteins, and repeat calls to the
    intended browse/index contract
- Implemented slice `3.2`:
  - added composite browse indexes for the hot raw pages
  - created `browser.0011_add_hot_raw_browse_indexes`
- Implemented slice `3.3`:
  - kept cursor mode only on the fast default raw order
  - made alternate sorts fall back to page-number pagination
- Implemented slices `3.4` and `3.5`:
  - narrowed raw repeat-call, protein, and sequence row fetches
  - removed eager `genome` joins from the default protein/sequence row path
  - removed eager `genome` and `protein` joins from the default repeat-call row
    path
  - switched row templates to local FK ids plus denormalized raw display fields
- Ran the real large-run acceptance/profile pass for slice `4.1` on
  `chr_all3_raw_2026_04_09` in Docker/Postgres
- Found and fixed a real environment issue during profiling:
  - the persistent Compose/Postgres database still had not applied
    `browser.0011_add_hot_raw_browse_indexes`
  - applied migrations in Compose, then reran timings and `EXPLAIN`
- Recorded the post-migration large-run artifact:
  - default raw row fetches now use the intended composite browse indexes
  - the remaining dominant hot cost is exact `COUNT(*)`, including on cursor
    fragments
  - `/browser/` is still dominated by live directory-card counts

## Files touched

- [docs/optimize/phases.md](/home/rafael/Documents/GitHub/homorepeat/docs/optimize/phases.md)
  Updated slice status through `4.1`, baseline artifact references, and the
  current handoff state.
- [docs/optimize/optimize.md](/home/rafael/Documents/GitHub/homorepeat/docs/optimize/optimize.md)
  Added a short current measured outcome note so the plan reflects the actual
  large-run profile.
- [docs/optimize/baseline-2026-04-11.md](/home/rafael/Documents/GitHub/homorepeat/docs/optimize/baseline-2026-04-11.md)
  Marked the original placeholder as superseded by the real reprofile artifact.
- [docs/optimize/reprofile-2026-04-12.md](/home/rafael/Documents/GitHub/homorepeat/docs/optimize/reprofile-2026-04-12.md)
  Added the large-run timing and `EXPLAIN` artifact from the real Compose/Postgres dataset.
- [docs/optimize/session-log-2026-04-12.md](/home/rafael/Documents/GitHub/homorepeat/docs/optimize/session-log-2026-04-12.md)
  Updated the dated optimize handoff log to cover the full day.
- [apps/browser/models.py](/home/rafael/Documents/GitHub/homorepeat/apps/browser/models.py)
- [apps/browser/migrations/0010_pipelinerun_browser_metadata.py](/home/rafael/Documents/GitHub/homorepeat/apps/browser/migrations/0010_pipelinerun_browser_metadata.py)
- [apps/browser/migrations/0011_add_hot_raw_browse_indexes.py](/home/rafael/Documents/GitHub/homorepeat/apps/browser/migrations/0011_add_hot_raw_browse_indexes.py)
  Added browser metadata storage compatibility and the hot raw composite browse
  indexes.
- [apps/browser/metadata.py](/home/rafael/Documents/GitHub/homorepeat/apps/browser/metadata.py)
  Added shared metadata/facet resolution and backfill helpers.
- [apps/imports/services/import_run.py](/home/rafael/Documents/GitHub/homorepeat/apps/imports/services/import_run.py)
  Persisted browser metadata during import completion.
- [apps/browser/views.py](/home/rafael/Documents/GitHub/homorepeat/apps/browser/views.py)
  Landed the raw ordering contract, cursor gating, narrower hot raw row paths,
  and the measured-count hotspot context.
- [apps/browser/merged.py](/home/rafael/Documents/GitHub/homorepeat/apps/browser/merged.py)
  Added multi-taxon branch scope support for merged accessions, proteins, and
  repeat-call groups.
- [templates/browser/taxon_list.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/taxon_list.html)
- [templates/browser/genome_list.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/genome_list.html)
- [templates/browser/sequence_list.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/sequence_list.html)
- [templates/browser/protein_list.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/protein_list.html)
- [templates/browser/repeatcall_list.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/repeatcall_list.html)
- [templates/browser/accession_list.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/accession_list.html)
- [templates/browser/includes/accession_list_rows.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/includes/accession_list_rows.html)
- [templates/browser/includes/sequence_list_rows.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/includes/sequence_list_rows.html)
- [templates/browser/includes/protein_list_rows.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/includes/protein_list_rows.html)
- [templates/browser/includes/repeatcall_list_rows.html](/home/rafael/Documents/GitHub/homorepeat/templates/browser/includes/repeatcall_list_rows.html)
  Replaced branch dropdowns, preserved branch search state, and moved hot raw
  row links onto local ids plus denormalized display fields.
- [static/js/site.js](/home/rafael/Documents/GitHub/homorepeat/static/js/site.js)
  Taught the virtual-scroll client to tolerate fragment payloads without
  `count`.
- [web_tests/test_models.py](/home/rafael/Documents/GitHub/homorepeat/web_tests/test_models.py)
- [web_tests/test_browser_metadata.py](/home/rafael/Documents/GitHub/homorepeat/web_tests/test_browser_metadata.py)
- [web_tests/test_browser_views.py](/home/rafael/Documents/GitHub/homorepeat/web_tests/test_browser_views.py)
- [web_tests/test_merged_helpers.py](/home/rafael/Documents/GitHub/homorepeat/web_tests/test_merged_helpers.py)
  Added focused coverage for metadata, branch search, ordering/index contract,
  cursor fallback behavior, and coarse hot-row query shape.

## Validation

- `python manage.py test web_tests.test_models.PipelineRunModelTests`
- `python manage.py test web_tests.test_browser_metadata`
- `python manage.py test web_tests.test_browser_views.BrowserViewTests.test_sequence_list_default_ordering_matches_optimize_contract web_tests.test_browser_views.BrowserViewTests.test_protein_list_default_ordering_matches_optimize_contract web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_default_ordering_matches_optimize_contract web_tests.test_browser_views.BrowserViewTests.test_sequence_list_virtual_scroll_fragment_returns_rows_without_count web_tests.test_browser_views.BrowserViewTests.test_protein_list_uses_cursor_pagination_for_raw_results web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_uses_cursor_pagination_for_raw_results`
- `python manage.py makemigrations browser --check --dry-run`
- `python manage.py test web_tests.test_models.BiologicalModelTests.test_sequence_model_defines_hot_raw_browse_index web_tests.test_models.BiologicalModelTests.test_protein_model_defines_hot_raw_browse_index web_tests.test_models.BiologicalModelTests.test_repeat_call_model_defines_hot_raw_browse_index`
- `python manage.py test web_tests.test_browser_views.BrowserViewTests.test_sequence_list_uses_cursor_pagination_for_default_raw_order web_tests.test_browser_views.BrowserViewTests.test_sequence_list_alternate_sort_falls_back_to_page_pagination web_tests.test_browser_views.BrowserViewTests.test_protein_list_uses_cursor_pagination_for_raw_results web_tests.test_browser_views.BrowserViewTests.test_protein_list_alternate_sort_falls_back_to_page_pagination web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_uses_cursor_pagination_for_raw_results web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_alternate_sort_falls_back_to_page_pagination`
- `python manage.py test web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_keeps_raw_rows_narrow web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_uses_local_ids_and_denormalized_fields_for_links web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_combined_filters_and_branch_scope_work web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_uses_cursor_pagination_for_raw_results web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_alternate_sort_falls_back_to_page_pagination web_tests.test_browser_views.BrowserViewTests.test_repeatcall_list_virtual_scroll_fragment_returns_rows`
- `python manage.py test web_tests.test_browser_views.BrowserViewTests.test_sequence_list_keeps_raw_rows_narrow web_tests.test_browser_views.BrowserViewTests.test_sequence_list_uses_local_ids_and_denormalized_fields_for_links web_tests.test_browser_views.BrowserViewTests.test_sequence_list_uses_cursor_pagination_for_default_raw_order web_tests.test_browser_views.BrowserViewTests.test_sequence_list_alternate_sort_falls_back_to_page_pagination web_tests.test_browser_views.BrowserViewTests.test_protein_list_keeps_raw_rows_narrow web_tests.test_browser_views.BrowserViewTests.test_protein_list_uses_local_ids_and_denormalized_fields_for_links web_tests.test_browser_views.BrowserViewTests.test_protein_list_uses_cursor_pagination_for_raw_results web_tests.test_browser_views.BrowserViewTests.test_protein_list_alternate_sort_falls_back_to_page_pagination`
- `docker compose run --rm --no-deps web python manage.py migrate`
- `docker compose run --rm --no-deps web python manage.py shell ...`
  Measured large-run timings and captured post-migration `EXPLAIN ANALYZE`
  plans for proteins, repeat calls, and sequences.
- `python manage.py test web_tests.test_merged_helpers`

Key results:

- all focused optimize regressions passed through slices `3.1` to `3.5`
- Compose/Postgres large-run measurements were captured successfully after
  applying `browser.0011_add_hot_raw_browse_indexes`
- the real large-run row fetch plans now use the intended composite browse
  indexes
- the remaining dominant hot cost is exact `COUNT(*)`, not the row fetch

## Current status

- In progress
- Raw optimize slices `1.2` through `4.1` are implemented/profiled
- `1.1` remains intentionally skipped
- the docs now reflect the post-migration large-run profile and the remaining
  bottlenecks
- there is no next optimize slice currently queued in `docs/optimize/phases.md`

## Open issues

- The hot raw cursor pages still execute exact `COUNT(*)` via
  `CursorPaginatedListView.paginate_queryset()`, even when the fragment payload
  omits `count`
- `/browser/` is still dominated by live directory-card counts
- slice `1.1` was skipped, so there is still no trustworthy before/after timing
  comparison set for the optimize pass
- Merged mode is still outside the raw-browser completion path and still
  materializes large repeat-call sets in Python

## Next step

- Decide whether to do a follow-up pass that removes exact total counts from
  hot raw cursor pages, and possibly from the browser home directory cards too
