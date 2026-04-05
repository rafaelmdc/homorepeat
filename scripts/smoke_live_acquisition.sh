#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_STARTED_AT_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DEFAULT_RUN_STAMP="$(date -u +%Y-%m-%d_%H-%M-%SZ)"
RUN_ID="${HOMOREPEAT_SMOKE_RUN_ID:-live_smoke_${DEFAULT_RUN_STAMP}}"
RUN_ROOT="${HOMOREPEAT_SMOKE_RUN_ROOT:-$ROOT_DIR/runs/$RUN_ID}"

TAXONOMY_DB_PATH="${TAXONOMY_DB_PATH:-$ROOT_DIR/cache/taxonomy/ncbi_taxonomy.sqlite}"
TAXONOMY_TAXDUMP_PATH="${TAXONOMY_TAXDUMP_PATH:-$(dirname "$TAXONOMY_DB_PATH")/taxdump.tar.gz}"
TAXONOMY_BUILD_REPORT_PATH="${TAXONOMY_BUILD_REPORT_PATH:-$(dirname "$TAXONOMY_DB_PATH")/ncbi_taxonomy_build.json}"
NCBI_API_KEY="${NCBI_API_KEY:-}"
TAXON_WEAVER_BIN="${TAXON_WEAVER_BIN:-taxon-weaver}"
DATASETS_BIN="${DATASETS_BIN:-datasets}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
NCBI_CACHE_DIR="${NCBI_CACHE_DIR:-}"

SMOKE_TAXON_NAME="${HOMOREPEAT_SMOKE_TAXON_NAME:-Homo sapiens}"
SMOKE_ACCESSION="${HOMOREPEAT_SMOKE_ACCESSION:-GCF_000001405.40}"
SMOKE_REPEAT_RESIDUE="${HOMOREPEAT_SMOKE_REPEAT_RESIDUE:-Q}"

fail() {
  echo "smoke failure: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found on PATH: $1"
}

assert_nonempty_file() {
  local path="$1"
  [[ -s "$path" ]] || fail "expected non-empty file: $path"
}

assert_tsv_has_data_rows() {
  local path="$1"
  [[ -s "$path" ]] || fail "expected TSV file: $path"
  local lines
  lines="$(wc -l < "$path")"
  [[ "$lines" -ge 2 ]] || fail "expected at least one data row in $path"
}

run_py() {
  "$PYTHON_BIN" "$@"
}

require_command "$PYTHON_BIN"
require_command "$TAXON_WEAVER_BIN"
require_command "$DATASETS_BIN"

mkdir -p "$(dirname "$TAXONOMY_DB_PATH")"

if [[ ! -f "$TAXONOMY_DB_PATH" ]]; then
  echo "smoke: taxonomy DB not found, building with taxon-weaver"
  "$TAXON_WEAVER_BIN" build-db \
    --download \
    --dump "$TAXONOMY_TAXDUMP_PATH" \
    --db "$TAXONOMY_DB_PATH" \
    --report-json "$TAXONOMY_BUILD_REPORT_PATH"
fi

[[ -f "$TAXONOMY_DB_PATH" ]] || fail "taxonomy DB was not created: $TAXONOMY_DB_PATH"

mkdir -p "$RUN_ROOT"
mkdir -p "$RUN_ROOT/logs"
printf '%s\n' "$RUN_STARTED_AT_UTC" > "$RUN_ROOT/run_started_at_utc.txt"

TAXONOMY_CHECK_DIR="$RUN_ROOT/taxonomy_check"
PLANNING_DIR="$RUN_ROOT/planning"
BATCH_RAW_DIR="$RUN_ROOT/batches/batch_0001/raw"
BATCH_NORMALIZED_DIR="$RUN_ROOT/batches/batch_0001/normalized"
MERGED_DIR="$RUN_ROOT/merged/acquisition"
DETECTION_DIR="$RUN_ROOT/merged/calls"
CODON_DIR="$RUN_ROOT/merged/calls_with_codons"
SQLITE_DIR="$RUN_ROOT/merged/sqlite"
REPORTS_DIR="$RUN_ROOT/merged/reports"

mkdir -p "$TAXONOMY_CHECK_DIR" "$PLANNING_DIR" "$BATCH_RAW_DIR" "$BATCH_NORMALIZED_DIR" "$MERGED_DIR" "$DETECTION_DIR" "$CODON_DIR" "$SQLITE_DIR" "$REPORTS_DIR"

cat > "$TAXONOMY_CHECK_DIR/requested_taxa.tsv" <<EOF
request_id	input_value	input_type	provided_rank	selection_policy	notes
req_taxonomy	$SMOKE_TAXON_NAME	scientific_name		reference_preferred_representative_allowed	live taxon-weaver smoke check
EOF

echo "smoke: resolving live scientific name with taxon-weaver"
run_py "$ROOT_DIR/bin/resolve_taxa.py" \
  --requested-taxa "$TAXONOMY_CHECK_DIR/requested_taxa.tsv" \
  --taxonomy-db "$TAXONOMY_DB_PATH" \
  --taxon-weaver-bin "$TAXON_WEAVER_BIN" \
  --outdir "$TAXONOMY_CHECK_DIR"

assert_tsv_has_data_rows "$TAXONOMY_CHECK_DIR/resolved_requests.tsv"
run_py - <<'PY' "$TAXONOMY_CHECK_DIR/resolved_requests.tsv"
import csv, sys
path = sys.argv[1]
with open(path, encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if len(rows) != 1:
    raise SystemExit(f"expected exactly one taxonomy resolution row, found {len(rows)}")
row = rows[0]
if row["review_required"] != "false":
    raise SystemExit("taxonomy smoke resolution entered review queue")
if not row["matched_taxid"]:
    raise SystemExit("taxonomy smoke resolution did not produce a matched taxid")
PY

cat > "$PLANNING_DIR/requested_taxa.tsv" <<EOF
request_id	input_value	input_type	provided_rank	selection_policy	notes
req_accession	$SMOKE_ACCESSION	assembly_accession		reference_preferred_representative_allowed	live single-accession acquisition smoke check
EOF

echo "smoke: resolving direct accession request"
run_py "$ROOT_DIR/bin/resolve_taxa.py" \
  --requested-taxa "$PLANNING_DIR/requested_taxa.tsv" \
  --taxonomy-db "$TAXONOMY_DB_PATH" \
  --taxon-weaver-bin "$TAXON_WEAVER_BIN" \
  --outdir "$PLANNING_DIR"

echo "smoke: enumerating live assembly metadata"
ENUMERATE_ARGS=(
  "$ROOT_DIR/bin/enumerate_assemblies.py"
  --resolved-requests "$PLANNING_DIR/resolved_requests.tsv"
  --outdir "$PLANNING_DIR"
  --datasets-bin "$DATASETS_BIN"
)
if [[ -n "$NCBI_API_KEY" ]]; then
  ENUMERATE_ARGS+=(--api-key "$NCBI_API_KEY")
fi
run_py "${ENUMERATE_ARGS[@]}"

echo "smoke: selecting assemblies"
run_py "$ROOT_DIR/bin/select_assemblies.py" \
  --assembly-inventory "$PLANNING_DIR/assembly_inventory.tsv" \
  --outdir "$PLANNING_DIR"

echo "smoke: planning batches"
run_py "$ROOT_DIR/bin/plan_batches.py" \
  --selected-assemblies "$PLANNING_DIR/selected_assemblies.tsv" \
  --outdir "$PLANNING_DIR" \
  --target-batch-size 1 \
  --max-batches 1

assert_tsv_has_data_rows "$PLANNING_DIR/selected_assemblies.tsv"
assert_tsv_has_data_rows "$PLANNING_DIR/selected_batches.tsv"

echo "smoke: downloading live NCBI package"
DOWNLOAD_ARGS=(
  "$ROOT_DIR/bin/download_ncbi_packages.py"
  --batch-manifest "$PLANNING_DIR/selected_batches.tsv"
  --batch-id batch_0001
  --outdir "$BATCH_RAW_DIR"
  --datasets-bin "$DATASETS_BIN"
)
if [[ -n "$NCBI_API_KEY" ]]; then
  DOWNLOAD_ARGS+=(--api-key "$NCBI_API_KEY")
fi
if [[ -n "$NCBI_CACHE_DIR" ]]; then
  mkdir -p "$NCBI_CACHE_DIR"
  DOWNLOAD_ARGS+=(--cache-dir "$NCBI_CACHE_DIR")
fi
run_py "${DOWNLOAD_ARGS[@]}"

assert_tsv_has_data_rows "$BATCH_RAW_DIR/download_manifest.tsv"

echo "smoke: normalizing live package with taxon-weaver lineage enrichment"
run_py "$ROOT_DIR/bin/normalize_cds.py" \
  --package-dir "$BATCH_RAW_DIR/ncbi_package" \
  --taxonomy-db "$TAXONOMY_DB_PATH" \
  --taxon-weaver-bin "$TAXON_WEAVER_BIN" \
  --batch-id batch_0001 \
  --outdir "$BATCH_NORMALIZED_DIR"

echo "smoke: translating normalized CDS"
run_py "$ROOT_DIR/bin/translate_cds.py" \
  --sequences-tsv "$BATCH_NORMALIZED_DIR/sequences.tsv" \
  --cds-fasta "$BATCH_NORMALIZED_DIR/cds.fna" \
  --batch-id batch_0001 \
  --outdir "$BATCH_NORMALIZED_DIR"

echo "smoke: merging one successful batch"
run_py "$ROOT_DIR/bin/merge_acquisition_batches.py" \
  --batch-inputs "$BATCH_NORMALIZED_DIR" \
  --outdir "$MERGED_DIR"

assert_tsv_has_data_rows "$MERGED_DIR/genomes.tsv"
assert_tsv_has_data_rows "$MERGED_DIR/taxonomy.tsv"
assert_tsv_has_data_rows "$MERGED_DIR/sequences.tsv"
assert_tsv_has_data_rows "$MERGED_DIR/proteins.tsv"
assert_nonempty_file "$MERGED_DIR/acquisition_validation.json"

run_py - <<'PY' "$MERGED_DIR/acquisition_validation.json"
import json, sys
payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
if payload.get("status") not in {"pass", "warn"}:
    raise SystemExit(f"unexpected acquisition validation status: {payload.get('status')}")
for key in [
    "all_selected_accessions_accounted_for",
    "all_genomes_have_taxids",
    "all_proteins_belong_to_genomes",
    "all_retained_proteins_trace_to_cds",
]:
    if not payload.get("checks", {}).get(key, False):
        raise SystemExit(f"validation check failed: {key}")
PY

echo "smoke: running pure detection for codon extraction check"
run_py "$ROOT_DIR/bin/detect_pure.py" \
  --proteins-tsv "$MERGED_DIR/proteins.tsv" \
  --proteins-fasta "$MERGED_DIR/proteins.faa" \
  --repeat-residue "$SMOKE_REPEAT_RESIDUE" \
  --outdir "$DETECTION_DIR"

assert_tsv_has_data_rows "$DETECTION_DIR/pure_calls.tsv"

echo "smoke: extracting codons for pure calls"
run_py "$ROOT_DIR/bin/extract_repeat_codons.py" \
  --calls-tsv "$DETECTION_DIR/pure_calls.tsv" \
  --sequences-tsv "$MERGED_DIR/sequences.tsv" \
  --cds-fasta "$MERGED_DIR/cds.fna" \
  --outdir "$CODON_DIR"

assert_tsv_has_data_rows "$CODON_DIR/pure_calls.tsv"
assert_nonempty_file "$CODON_DIR/pure_calls_codon_warnings.tsv"

run_py - <<'PY' "$CODON_DIR/pure_calls.tsv"
import csv, sys
path = sys.argv[1]
with open(path, encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if not rows:
    raise SystemExit("expected codon-enriched pure calls to be non-empty")
success_count = 0
for row in rows:
    codon_sequence = row.get("codon_sequence", "")
    codon_metric_name = row.get("codon_metric_name", "")
    codon_metric_value = row.get("codon_metric_value", "")
    length = int(row["length"])
    if codon_metric_name or codon_metric_value:
        raise SystemExit("v1 smoke found unexpected codon metric fields")
    if codon_sequence:
        success_count += 1
        if len(codon_sequence) != length * 3:
            raise SystemExit("codon extraction length mismatch in smoke output")
if success_count < 1:
    raise SystemExit("expected at least one successful codon extraction in smoke output")
PY

echo "smoke: building sqlite artifact"
run_py "$ROOT_DIR/bin/build_sqlite.py" \
  --taxonomy-tsv "$MERGED_DIR/taxonomy.tsv" \
  --genomes-tsv "$MERGED_DIR/genomes.tsv" \
  --sequences-tsv "$MERGED_DIR/sequences.tsv" \
  --proteins-tsv "$MERGED_DIR/proteins.tsv" \
  --call-tsv "$CODON_DIR/pure_calls.tsv" \
  --run-params-tsv "$DETECTION_DIR/run_params.tsv" \
  --outdir "$SQLITE_DIR"

assert_nonempty_file "$SQLITE_DIR/homorepeat.sqlite"
assert_nonempty_file "$SQLITE_DIR/sqlite_validation.json"

run_py - <<'PY' "$SQLITE_DIR/sqlite_validation.json"
import json, sys
payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
if payload.get("status") != "pass":
    raise SystemExit(f"unexpected sqlite validation status: {payload.get('status')}")
if not all(payload.get("checks", {}).values()):
    raise SystemExit("sqlite validation contains failed checks")
PY

echo "smoke: exporting summary tables"
run_py "$ROOT_DIR/bin/export_summary_tables.py" \
  --taxonomy-tsv "$MERGED_DIR/taxonomy.tsv" \
  --proteins-tsv "$MERGED_DIR/proteins.tsv" \
  --call-tsv "$CODON_DIR/pure_calls.tsv" \
  --outdir "$REPORTS_DIR"

assert_tsv_has_data_rows "$REPORTS_DIR/summary_by_taxon.tsv"
assert_tsv_has_data_rows "$REPORTS_DIR/regression_input.tsv"

echo "smoke: preparing report tables"
run_py "$ROOT_DIR/bin/prepare_report_tables.py" \
  --summary-tsv "$REPORTS_DIR/summary_by_taxon.tsv" \
  --regression-tsv "$REPORTS_DIR/regression_input.tsv" \
  --outdir "$REPORTS_DIR"

assert_nonempty_file "$REPORTS_DIR/echarts_options.json"

run_py - <<'PY' "$REPORTS_DIR/echarts_options.json"
import json, sys
payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
for key in ["taxon_method_overview", "repeat_length_distribution"]:
    if key not in payload:
        raise SystemExit(f"missing ECharts option block: {key}")
PY

echo "smoke: completed successfully"
echo "smoke: run root -> $RUN_ROOT"
