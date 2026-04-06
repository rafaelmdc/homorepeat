#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_STAMP="$(date -u +%Y-%m-%d_%H-%M-%SZ)"
RUN_ID="${HOMOREPEAT_PHASE4_RUN_ID:-phase4_pipeline_${RUN_STAMP}}"
RUN_ROOT="${HOMOREPEAT_PHASE4_RUN_ROOT:-$ROOT_DIR/results/phase4/$RUN_ID}"
OUTPUT_DIR="${HOMOREPEAT_PHASE4_OUTPUT_DIR:-$RUN_ROOT/results}"
PROFILE="${HOMOREPEAT_PHASE4_PROFILE:-local}"
NEXTFLOW_BIN="${NEXTFLOW_BIN:-nextflow}"
PARAMS_FILE="${HOMOREPEAT_PARAMS_FILE:-}"

if [[ $# -lt 1 ]] && [[ -z "${HOMOREPEAT_ACCESSIONS_FILE:-}" ]]; then
  echo "usage: $0 <accessions_file> [additional nextflow args...]" >&2
  echo "or set HOMOREPEAT_ACCESSIONS_FILE in the environment" >&2
  exit 2
fi

ACCESSIONS_FILE="${HOMOREPEAT_ACCESSIONS_FILE:-${1:-}}"
if [[ $# -gt 0 ]] && [[ -z "${HOMOREPEAT_ACCESSIONS_FILE:-}" ]]; then
  shift
fi

if [[ "$ACCESSIONS_FILE" != /* ]]; then
  ACCESSIONS_FILE="${ROOT_DIR}/${ACCESSIONS_FILE}"
fi

if [[ -n "$PARAMS_FILE" ]] && [[ "$PARAMS_FILE" != /* ]]; then
  PARAMS_FILE="${ROOT_DIR}/${PARAMS_FILE}"
fi

TAXONOMY_DB="${HOMOREPEAT_TAXONOMY_DB:-$ROOT_DIR/cache/taxonomy/ncbi_taxonomy.sqlite}"
if [[ "$TAXONOMY_DB" != /* ]]; then
  TAXONOMY_DB="${ROOT_DIR}/${TAXONOMY_DB}"
fi

if [[ ! -f "$ACCESSIONS_FILE" ]]; then
  echo "accessions file not found: $ACCESSIONS_FILE" >&2
  exit 2
fi

if [[ -n "$PARAMS_FILE" ]] && [[ ! -f "$PARAMS_FILE" ]]; then
  echo "params file not found: $PARAMS_FILE" >&2
  exit 2
fi

if [[ ! -f "$TAXONOMY_DB" ]]; then
  echo "taxonomy DB not found: $TAXONOMY_DB" >&2
  echo "set HOMOREPEAT_TAXONOMY_DB to override it" >&2
  exit 2
fi

if [[ -n "${HOMOREPEAT_NXF_HOME:-}" ]]; then
  export NXF_HOME="$HOMOREPEAT_NXF_HOME"
fi

mkdir -p "$RUN_ROOT/nextflow"
LOG_FILE="${RUN_ROOT}/nextflow/nextflow.log"
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RUN_ROOT/run_started_at_utc.txt"

{
  printf 'RUN_ID=%q\n' "$RUN_ID"
  printf 'RUN_ROOT=%q\n' "$RUN_ROOT"
  printf 'OUTPUT_DIR=%q\n' "$OUTPUT_DIR"
  printf 'PROFILE=%q\n' "$PROFILE"
  printf 'ACCESSIONS_FILE=%q\n' "$ACCESSIONS_FILE"
  printf 'TAXONOMY_DB=%q\n' "$TAXONOMY_DB"
  printf 'PARAMS_FILE=%q\n' "$PARAMS_FILE"
} > "$RUN_ROOT/run_context.env"

NEXTFLOW_ARGS=(
  -log "$LOG_FILE"
  run "$ROOT_DIR"
  -profile "$PROFILE"
  --accessions_file "$ACCESSIONS_FILE"
  --taxonomy_db "$TAXONOMY_DB"
  --output_dir "$OUTPUT_DIR"
)

if [[ -n "$PARAMS_FILE" ]]; then
  NEXTFLOW_ARGS+=(-params-file "$PARAMS_FILE")
fi

if [[ $# -gt 0 ]]; then
  NEXTFLOW_ARGS+=("$@")
fi

{
  printf '%q ' "$NEXTFLOW_BIN"
  printf '%q ' "${NEXTFLOW_ARGS[@]}"
  printf '\n'
} > "$RUN_ROOT/nextflow_command.sh"
chmod +x "$RUN_ROOT/nextflow_command.sh"

cd "$RUN_ROOT"

"$NEXTFLOW_BIN" "${NEXTFLOW_ARGS[@]}"
STATUS=$?

if [[ $STATUS -eq 0 ]]; then
  ln -sfn "$RUN_ID" "$ROOT_DIR/results/phase4/latest"
fi

exit $STATUS
