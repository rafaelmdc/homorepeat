#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_STARTED_AT_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DEFAULT_RUN_STAMP="$(date -u +%Y-%m-%d_%H-%M-%SZ)"
RUN_ID="${HOMOREPEAT_DETECTION_SMOKE_RUN_ID:-live_detection_smoke_${DEFAULT_RUN_STAMP}}"
RUN_ROOT="${HOMOREPEAT_DETECTION_SMOKE_RUN_ROOT:-$ROOT_DIR/runs/$RUN_ID}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DIAMOND_BIN="${DIAMOND_BIN:-diamond}"
SMOKE_REPEAT_RESIDUE="${HOMOREPEAT_SMOKE_REPEAT_RESIDUE:-Q}"
SMOKE_DIAMOND_MAX_TARGET_SEQS="${HOMOREPEAT_SMOKE_DIAMOND_MAX_TARGET_SEQS:-500}"

find_latest_live_smoke_root() {
  local candidate
  candidate="$(find "$ROOT_DIR/runs" -maxdepth 1 -mindepth 1 -type d -name 'live_smoke_*' | sort | tail -n1 || true)"
  printf '%s' "$candidate"
}

SOURCE_RUN_ROOT="${HOMOREPEAT_SMOKE_SOURCE_RUN_ROOT:-$(find_latest_live_smoke_root)}"
SOURCE_ACQUISITION_DIR="${HOMOREPEAT_SMOKE_SOURCE_ACQUISITION_DIR:-}"
if [[ -z "$SOURCE_ACQUISITION_DIR" ]]; then
  [[ -n "$SOURCE_RUN_ROOT" ]] || {
    echo "smoke failure: no source acquisition run was provided and no live_smoke_* run was found under $ROOT_DIR/runs" >&2
    exit 1
  }
  SOURCE_ACQUISITION_DIR="$SOURCE_RUN_ROOT/merged/acquisition"
fi

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
require_command "$DIAMOND_BIN"

[[ -d "$SOURCE_ACQUISITION_DIR" ]] || fail "source acquisition directory does not exist: $SOURCE_ACQUISITION_DIR"
assert_tsv_has_data_rows "$SOURCE_ACQUISITION_DIR/proteins.tsv"
assert_nonempty_file "$SOURCE_ACQUISITION_DIR/proteins.faa"
assert_tsv_has_data_rows "$SOURCE_ACQUISITION_DIR/sequences.tsv"
assert_nonempty_file "$SOURCE_ACQUISITION_DIR/cds.fna"

mkdir -p "$RUN_ROOT"
mkdir -p "$RUN_ROOT/logs"
printf '%s\n' "$RUN_STARTED_AT_UTC" > "$RUN_ROOT/run_started_at_utc.txt"
printf '%s\n' "$SOURCE_ACQUISITION_DIR" > "$RUN_ROOT/source_acquisition_dir.txt"

THRESHOLD_DIR="$RUN_ROOT/merged/calls/threshold"
BLAST_DIR="$RUN_ROOT/merged/calls/blast"
THRESHOLD_CODON_DIR="$RUN_ROOT/merged/calls_with_codons/threshold"
BLAST_CODON_DIR="$RUN_ROOT/merged/calls_with_codons/blast"

mkdir -p "$THRESHOLD_DIR" "$BLAST_DIR" "$THRESHOLD_CODON_DIR" "$BLAST_CODON_DIR"

echo "smoke: running threshold detection"
run_py "$ROOT_DIR/bin/detect_threshold.py" \
  --proteins-tsv "$SOURCE_ACQUISITION_DIR/proteins.tsv" \
  --proteins-fasta "$SOURCE_ACQUISITION_DIR/proteins.faa" \
  --repeat-residue "$SMOKE_REPEAT_RESIDUE" \
  --outdir "$THRESHOLD_DIR"

assert_tsv_has_data_rows "$THRESHOLD_DIR/threshold_calls.tsv"
assert_tsv_has_data_rows "$THRESHOLD_DIR/run_params.tsv"

run_py - <<'PY' "$THRESHOLD_DIR/threshold_calls.tsv" "$THRESHOLD_DIR/run_params.tsv"
import csv, sys
from lib.repeat_features import validate_call_row

calls_path, params_path = sys.argv[1], sys.argv[2]
with open(calls_path, encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if not rows:
    raise SystemExit("threshold smoke output is empty")
for row in rows:
    validate_call_row(row)
    if row["method"] != "threshold":
        raise SystemExit("threshold smoke found a non-threshold method row")
    if not row["window_definition"]:
        raise SystemExit("threshold smoke found an empty window_definition")
with open(params_path, encoding="utf-8", newline="") as handle:
    params = {(row["param_name"], row["param_value"]) for row in csv.DictReader(handle, delimiter="\t")}
for item in [("window_size", "8"), ("min_target_count", "6")]:
    if item not in params:
        raise SystemExit(f"threshold smoke missing run param: {item}")
PY

echo "smoke: extracting codons for threshold calls"
run_py "$ROOT_DIR/bin/extract_repeat_codons.py" \
  --calls-tsv "$THRESHOLD_DIR/threshold_calls.tsv" \
  --sequences-tsv "$SOURCE_ACQUISITION_DIR/sequences.tsv" \
  --cds-fasta "$SOURCE_ACQUISITION_DIR/cds.fna" \
  --outdir "$THRESHOLD_CODON_DIR"

assert_tsv_has_data_rows "$THRESHOLD_CODON_DIR/threshold_calls.tsv"
assert_nonempty_file "$THRESHOLD_CODON_DIR/threshold_calls_codon_warnings.tsv"

run_py - <<'PY' "$THRESHOLD_CODON_DIR/threshold_calls.tsv"
import csv, sys
path = sys.argv[1]
with open(path, encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if not rows:
    raise SystemExit("threshold codon smoke output is empty")
success_count = 0
for row in rows:
    if row.get("codon_metric_name") or row.get("codon_metric_value"):
        raise SystemExit("threshold codon smoke found unexpected codon metric values")
    codon_sequence = row.get("codon_sequence", "")
    if codon_sequence:
        success_count += 1
        if len(codon_sequence) != int(row["length"]) * 3:
            raise SystemExit("threshold codon smoke found a length mismatch")
if success_count < 1:
    raise SystemExit("threshold codon smoke did not produce any successful codon rows")
PY

echo "smoke: running diamond blast detection"
run_py "$ROOT_DIR/bin/detect_blast.py" \
  --proteins-tsv "$SOURCE_ACQUISITION_DIR/proteins.tsv" \
  --proteins-fasta "$SOURCE_ACQUISITION_DIR/proteins.faa" \
  --repeat-residue "$SMOKE_REPEAT_RESIDUE" \
  --backend diamond_blastp \
  --diamond-bin "$DIAMOND_BIN" \
  --diamond-max-target-seqs "$SMOKE_DIAMOND_MAX_TARGET_SEQS" \
  --outdir "$BLAST_DIR"

assert_tsv_has_data_rows "$BLAST_DIR/blast_calls.tsv"
assert_tsv_has_data_rows "$BLAST_DIR/run_params.tsv"

run_py - <<'PY' "$BLAST_DIR/blast_calls.tsv" "$BLAST_DIR/run_params.tsv"
import csv, sys
from lib.repeat_features import validate_call_row

calls_path, params_path = sys.argv[1], sys.argv[2]
with open(calls_path, encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if not rows:
    raise SystemExit("diamond smoke output is empty")
for row in rows:
    validate_call_row(row)
    if row["method"] != "blast":
        raise SystemExit("diamond smoke found a non-blast method row")
    if not row["score"]:
        raise SystemExit("diamond smoke found an empty score")
with open(params_path, encoding="utf-8", newline="") as handle:
    params = {(row["param_name"], row["param_value"]) for row in csv.DictReader(handle, delimiter="\t")}
for item in [("backend", "diamond_blastp"), ("diamond_masking", "0")]:
    if item not in params:
        raise SystemExit(f"diamond smoke missing run param: {item}")
PY

echo "smoke: extracting codons for diamond blast calls"
run_py "$ROOT_DIR/bin/extract_repeat_codons.py" \
  --calls-tsv "$BLAST_DIR/blast_calls.tsv" \
  --sequences-tsv "$SOURCE_ACQUISITION_DIR/sequences.tsv" \
  --cds-fasta "$SOURCE_ACQUISITION_DIR/cds.fna" \
  --outdir "$BLAST_CODON_DIR"

assert_tsv_has_data_rows "$BLAST_CODON_DIR/blast_calls.tsv"
assert_nonempty_file "$BLAST_CODON_DIR/blast_calls_codon_warnings.tsv"

run_py - <<'PY' "$BLAST_CODON_DIR/blast_calls.tsv"
import csv, sys
path = sys.argv[1]
with open(path, encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if not rows:
    raise SystemExit("diamond codon smoke output is empty")
success_count = 0
for row in rows:
    if row.get("codon_metric_name") or row.get("codon_metric_value"):
        raise SystemExit("diamond codon smoke found unexpected codon metric values")
    codon_sequence = row.get("codon_sequence", "")
    if codon_sequence:
        success_count += 1
        if len(codon_sequence) != int(row["length"]) * 3:
            raise SystemExit("diamond codon smoke found a length mismatch")
if success_count < 1:
    raise SystemExit("diamond codon smoke did not produce any successful codon rows")
PY

echo "smoke: completed successfully"
echo "smoke: run root -> $RUN_ROOT"
