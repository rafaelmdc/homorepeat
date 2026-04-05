from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.repeat_features import CALL_FIELDNAMES, build_call_row
from lib.run_params import RUN_PARAM_FIELDNAMES
from lib.tsv_io import write_tsv


REPO_ROOT = Path(__file__).resolve().parents[1]


class SliceSevenSqliteBuildTest(unittest.TestCase):
    def test_build_sqlite_cli_imports_flat_outputs_and_validates_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            inputs_dir = tmp / "inputs"
            outdir = tmp / "sqlite"
            inputs_dir.mkdir(parents=True, exist_ok=True)

            paths = self._write_minimal_inputs(inputs_dir)

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "build_sqlite.py"),
                    "--taxonomy-tsv",
                    str(paths["taxonomy"]),
                    "--genomes-tsv",
                    str(paths["genomes"]),
                    "--sequences-tsv",
                    str(paths["sequences"]),
                    "--proteins-tsv",
                    str(paths["proteins"]),
                    "--call-tsv",
                    str(paths["calls"]),
                    "--run-params-tsv",
                    str(paths["run_params"]),
                    "--outdir",
                    str(outdir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.fail(
                    f"build_sqlite.py failed with exit code {result.returncode}\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            sqlite_path = outdir / "homorepeat.sqlite"
            validation_path = outdir / "sqlite_validation.json"
            self.assertTrue(sqlite_path.is_file())
            self.assertTrue(validation_path.is_file())

            validation_payload = json.loads(validation_path.read_text(encoding="utf-8"))
            self.assertEqual(validation_payload["status"], "pass")
            self.assertEqual(validation_payload["counts"]["taxonomy"], 1)
            self.assertEqual(validation_payload["counts"]["genomes"], 1)
            self.assertEqual(validation_payload["counts"]["sequences"], 1)
            self.assertEqual(validation_payload["counts"]["proteins"], 1)
            self.assertEqual(validation_payload["counts"]["run_params"], 1)
            self.assertEqual(validation_payload["counts"]["repeat_calls"], 1)
            self.assertTrue(all(validation_payload["checks"].values()))

            connection = sqlite3.connect(sqlite_path)
            try:
                repeat_call = connection.execute(
                    "SELECT method, repeat_residue, start, end, aa_sequence FROM repeat_calls"
                ).fetchone()
                self.assertEqual(repeat_call, ("pure", "A", 2, 7, "AAAAAA"))
                protein = connection.execute(
                    "SELECT protein_id, sequence_id, genome_id FROM proteins"
                ).fetchone()
                self.assertEqual(protein, ("prot_001", "seq_001", "genome_001"))
            finally:
                connection.close()

    def test_build_sqlite_cli_hard_fails_on_relational_integrity_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            inputs_dir = tmp / "inputs"
            outdir = tmp / "sqlite"
            inputs_dir.mkdir(parents=True, exist_ok=True)

            paths = self._write_minimal_inputs(inputs_dir, orphan_call_protein=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "build_sqlite.py"),
                    "--taxonomy-tsv",
                    str(paths["taxonomy"]),
                    "--genomes-tsv",
                    str(paths["genomes"]),
                    "--sequences-tsv",
                    str(paths["sequences"]),
                    "--proteins-tsv",
                    str(paths["proteins"]),
                    "--call-tsv",
                    str(paths["calls"]),
                    "--run-params-tsv",
                    str(paths["run_params"]),
                    "--outdir",
                    str(outdir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("SQLite import failed integrity checks", result.stderr)

    def _write_minimal_inputs(self, inputs_dir: Path, *, orphan_call_protein: bool = False) -> dict[str, Path]:
        taxonomy_path = inputs_dir / "taxonomy.tsv"
        genomes_path = inputs_dir / "genomes.tsv"
        sequences_path = inputs_dir / "sequences.tsv"
        proteins_path = inputs_dir / "proteins.tsv"
        calls_path = inputs_dir / "pure_calls.tsv"
        run_params_path = inputs_dir / "run_params.tsv"

        write_tsv(
            taxonomy_path,
            [
                {
                    "taxon_id": "9606",
                    "taxon_name": "Homo sapiens",
                    "parent_taxon_id": "9605",
                    "rank": "species",
                    "lineage": "root > Homo > Homo sapiens",
                    "source": "taxon_weaver:test",
                }
            ],
            fieldnames=["taxon_id", "taxon_name", "parent_taxon_id", "rank", "lineage", "source"],
        )
        write_tsv(
            genomes_path,
            [
                {
                    "genome_id": "genome_001",
                    "source": "ncbi_datasets",
                    "accession": "GCF_TEST_1.1",
                    "genome_name": "Homo sapiens",
                    "assembly_type": "Chromosome",
                    "taxon_id": "9606",
                    "assembly_level": "Chromosome",
                    "species_name": "Homo sapiens",
                    "download_path": str(inputs_dir.resolve()),
                    "notes": "",
                }
            ],
            fieldnames=[
                "genome_id",
                "source",
                "accession",
                "genome_name",
                "assembly_type",
                "taxon_id",
                "assembly_level",
                "species_name",
                "download_path",
                "notes",
            ],
        )
        write_tsv(
            sequences_path,
            [
                {
                    "sequence_id": "seq_001",
                    "genome_id": "genome_001",
                    "sequence_name": "tx1",
                    "sequence_length": 21,
                    "sequence_path": str((inputs_dir / "cds.fna").resolve()),
                    "gene_symbol": "GENE1",
                    "transcript_id": "tx1",
                    "isoform_id": "NP_TEST.1",
                    "assembly_accession": "GCF_TEST_1.1",
                    "taxon_id": "9606",
                    "source_record_id": "cds-tx1",
                    "protein_external_id": "NP_TEST.1",
                    "translation_table": "1",
                    "gene_group": "GENE1",
                    "linkage_status": "gff_transcript",
                    "partial_status": "",
                }
            ],
            fieldnames=[
                "sequence_id",
                "genome_id",
                "sequence_name",
                "sequence_length",
                "sequence_path",
                "gene_symbol",
                "transcript_id",
                "isoform_id",
                "assembly_accession",
                "taxon_id",
                "source_record_id",
                "protein_external_id",
                "translation_table",
                "gene_group",
                "linkage_status",
                "partial_status",
            ],
        )
        write_tsv(
            proteins_path,
            [
                {
                    "protein_id": "prot_001",
                    "sequence_id": "seq_001",
                    "genome_id": "genome_001",
                    "protein_name": "NP_TEST.1",
                    "protein_length": 7,
                    "protein_path": str((inputs_dir / "proteins.faa").resolve()),
                    "gene_symbol": "GENE1",
                    "translation_method": "local_cds_translation",
                    "translation_status": "translated",
                    "assembly_accession": "GCF_TEST_1.1",
                    "taxon_id": "9606",
                    "gene_group": "GENE1",
                    "protein_external_id": "NP_TEST.1",
                }
            ],
            fieldnames=[
                "protein_id",
                "sequence_id",
                "genome_id",
                "protein_name",
                "protein_length",
                "protein_path",
                "gene_symbol",
                "translation_method",
                "translation_status",
                "assembly_accession",
                "taxon_id",
                "gene_group",
                "protein_external_id",
            ],
        )
        call_row = build_call_row(
            method="pure",
            genome_id="genome_001",
            taxon_id="9606",
            sequence_id="seq_001",
            protein_id="missing_protein" if orphan_call_protein else "prot_001",
            repeat_residue="A",
            start=2,
            end=7,
            aa_sequence="AAAAAA",
            source_file=str((inputs_dir / "proteins.faa").resolve()),
            merge_rule="contiguous_run",
        )
        write_tsv(calls_path, [call_row], fieldnames=CALL_FIELDNAMES)
        write_tsv(
            run_params_path,
            [{"method": "pure", "param_name": "min_repeat_count", "param_value": 6}],
            fieldnames=RUN_PARAM_FIELDNAMES,
        )

        return {
            "taxonomy": taxonomy_path,
            "genomes": genomes_path,
            "sequences": sequences_path,
            "proteins": proteins_path,
            "calls": calls_path,
            "run_params": run_params_path,
        }
