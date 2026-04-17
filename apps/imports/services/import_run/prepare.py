from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apps.imports.models import ImportBatch
from apps.imports.services.published_run import (
    ImportContractError,
    InspectedPublishedRun,
    iter_repeat_call_rows,
)

from .copy import BULK_CREATE_BATCH_SIZE
from .state import ImportPhase, _ImportBatchStateReporter, _set_batch_state


@dataclass(frozen=True)
class PreparedStreamedImportData:
    retained_genome_ids: frozenset[str]
    retained_sequence_ids: frozenset[str]
    retained_protein_ids: frozenset[str]
    repeat_call_counts_by_protein: dict[str, int]
    total_repeat_calls: int


def _prepare_streamed_import_data(
    batch: ImportBatch,
    inspected: InspectedPublishedRun,
    *,
    reporter: _ImportBatchStateReporter | None = None,
) -> PreparedStreamedImportData:
    retained_genome_ids: set[str] = set()
    retained_sequence_ids: set[str] = set()
    retained_protein_ids: set[str] = set()
    repeat_call_counts_by_protein: dict[str, int] = {}
    total_repeat_calls = 0

    for row in iter_repeat_call_rows(inspected.artifact_paths.repeat_calls_tsv):
        genome_id = str(row["genome_id"])
        sequence_id = str(row["sequence_id"])
        protein_id = str(row["protein_id"])
        retained_genome_ids.add(genome_id)
        retained_sequence_ids.add(sequence_id)
        retained_protein_ids.add(protein_id)
        repeat_call_counts_by_protein[protein_id] = repeat_call_counts_by_protein.get(protein_id, 0) + 1
        total_repeat_calls += 1
        if total_repeat_calls % BULK_CREATE_BATCH_SIZE == 0:
            _set_batch_state(
                batch,
                phase=ImportPhase.PREPARING,
                progress_payload={
                    "message": "Scanning repeat calls to determine retained sequence and protein IDs.",
                    "batch_count": len(inspected.artifact_paths.acquisition_batches),
                    "repeat_calls": total_repeat_calls,
                    "retained_sequences": len(retained_sequence_ids),
                    "retained_proteins": len(retained_protein_ids),
                },
                reporter=reporter,
            )

    return PreparedStreamedImportData(
        retained_genome_ids=frozenset(retained_genome_ids),
        retained_sequence_ids=frozenset(retained_sequence_ids),
        retained_protein_ids=frozenset(retained_protein_ids),
        repeat_call_counts_by_protein=repeat_call_counts_by_protein,
        total_repeat_calls=total_repeat_calls,
    )

def _read_fasta_subset(
    path: Path,
    retained_ids: set[str],
    *,
    existing_records: dict[str, str],
    label: str,
) -> dict[str, str]:
    records: dict[str, str] = {}
    current_record_id = ""
    current_chunks: list[str] = []

    def store_current_record() -> None:
        if not current_record_id or current_record_id not in retained_ids:
            return
        sequence_value = "".join(current_chunks).strip()
        existing_value = existing_records.get(current_record_id, records.get(current_record_id))
        if existing_value is not None and existing_value != sequence_value:
            raise ImportContractError(
                f"Conflicting duplicate {label} FASTA records were found for {current_record_id!r}"
            )
        records[current_record_id] = sequence_value

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                store_current_record()
                current_record_id = line[1:].split()[0]
                current_chunks = []
                continue
            if not current_record_id:
                raise ImportContractError(f"{path} contains FASTA sequence data before the first header")
            current_chunks.append(line)

    store_current_record()
    return records
