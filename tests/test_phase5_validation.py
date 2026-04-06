from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.repeat_features import CALL_FIELDNAMES, build_call_row
from lib.tsv_io import write_tsv


REPO_ROOT = Path(__file__).resolve().parents[1]


class PhaseFiveValidationTest(unittest.TestCase):
    def test_validate_phase5_outputs_warns_when_upstream_acquisition_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self._write_inputs(tmp)

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "validate_phase5_outputs.py"),
                    "--taxonomy-tsv",
                    str(paths["taxonomy"]),
                    "--genomes-tsv",
                    str(paths["genomes"]),
                    "--proteins-tsv",
                    str(paths["proteins"]),
                    "--call-tsv",
                    str(paths["pure_calls"]),
                    "--call-tsv",
                    str(paths["threshold_calls"]),
                    "--summary-tsv",
                    str(paths["summary"]),
                    "--regression-tsv",
                    str(paths["regression"]),
                    "--acquisition-validation-json",
                    str(paths["acquisition_validation"]),
                    "--sqlite-validation-json",
                    str(paths["sqlite_validation"]),
                    "--outpath",
                    str(paths["report"]),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.fail(
                    f"validate_phase5_outputs.py failed unexpectedly with exit code {result.returncode}\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            payload = json.loads(paths["report"].read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "warn")
            self.assertTrue(payload["checks"]["summary_values_match"])
            self.assertTrue(payload["checks"]["regression_values_match"])
            self.assertTrue(payload["checks"]["sqlite_validation_pass"])
            self.assertEqual(payload["warnings"], ["acquisition validation status is warn"])

    def test_validate_phase5_outputs_fails_on_summary_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self._write_inputs(tmp, corrupt_summary=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "validate_phase5_outputs.py"),
                    "--taxonomy-tsv",
                    str(paths["taxonomy"]),
                    "--genomes-tsv",
                    str(paths["genomes"]),
                    "--proteins-tsv",
                    str(paths["proteins"]),
                    "--call-tsv",
                    str(paths["pure_calls"]),
                    "--call-tsv",
                    str(paths["threshold_calls"]),
                    "--summary-tsv",
                    str(paths["summary"]),
                    "--regression-tsv",
                    str(paths["regression"]),
                    "--sqlite-validation-json",
                    str(paths["sqlite_validation"]),
                    "--outpath",
                    str(paths["report"]),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("Phase 5 validation failed", result.stderr)
            payload = json.loads(paths["report"].read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "fail")
            self.assertFalse(payload["checks"]["summary_values_match"])

    def _write_inputs(self, tmp: Path, *, corrupt_summary: bool = False) -> dict[str, Path]:
        taxonomy = tmp / "taxonomy.tsv"
        genomes = tmp / "genomes.tsv"
        proteins = tmp / "proteins.tsv"
        pure_calls = tmp / "pure_calls.tsv"
        threshold_calls = tmp / "threshold_calls.tsv"
        summary = tmp / "summary_by_taxon.tsv"
        regression = tmp / "regression_input.tsv"
        acquisition_validation = tmp / "acquisition_validation.json"
        sqlite_validation = tmp / "sqlite_validation.json"
        report = tmp / "validation_report.json"

        write_tsv(
            taxonomy,
            [
                {"taxon_id": "1", "taxon_name": "root", "parent_taxon_id": "", "rank": "no rank", "source": "taxon_weaver:test"},
                {"taxon_id": "9605", "taxon_name": "Homo", "parent_taxon_id": "1", "rank": "genus", "source": "taxon_weaver:test"},
                {"taxon_id": "9606", "taxon_name": "Homo sapiens", "parent_taxon_id": "9605", "rank": "species", "source": "taxon_weaver:test"},
            ],
            fieldnames=["taxon_id", "taxon_name", "parent_taxon_id", "rank", "source"],
        )
        write_tsv(
            genomes,
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
                    "download_path": str(tmp.resolve()),
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
            proteins,
            [
                {
                    "protein_id": "prot_001",
                    "sequence_id": "seq_001",
                    "genome_id": "genome_001",
                    "protein_name": "PROT1",
                    "protein_length": 10,
                    "protein_path": str((tmp / "proteins.faa").resolve()),
                    "gene_symbol": "GENE1",
                    "translation_method": "local_cds_translation",
                    "translation_status": "translated",
                    "assembly_accession": "GCF_TEST_1.1",
                    "taxon_id": "9606",
                    "gene_group": "GENE1",
                    "protein_external_id": "NP_TEST.1",
                },
                {
                    "protein_id": "prot_002",
                    "sequence_id": "seq_002",
                    "genome_id": "genome_001",
                    "protein_name": "PROT2",
                    "protein_length": 20,
                    "protein_path": str((tmp / "proteins.faa").resolve()),
                    "gene_symbol": "GENE2",
                    "translation_method": "local_cds_translation",
                    "translation_status": "translated",
                    "assembly_accession": "GCF_TEST_1.1",
                    "taxon_id": "9606",
                    "gene_group": "GENE2",
                    "protein_external_id": "NP_TEST.2",
                },
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

        pure_rows = [
            build_call_row(
                method="pure",
                genome_id="genome_001",
                taxon_id="9606",
                sequence_id="seq_001",
                protein_id="prot_001",
                repeat_residue="Q",
                start=1,
                end=6,
                aa_sequence="QQQQQQ",
                source_file=str((tmp / "proteins.faa").resolve()),
                merge_rule="contiguous_run",
            ),
            build_call_row(
                method="pure",
                genome_id="genome_001",
                taxon_id="9606",
                sequence_id="seq_002",
                protein_id="prot_002",
                repeat_residue="Q",
                start=3,
                end=9,
                aa_sequence="QQQQQQQ",
                source_file=str((tmp / "proteins.faa").resolve()),
                merge_rule="contiguous_run",
            ),
        ]
        threshold_rows = [
            build_call_row(
                method="threshold",
                genome_id="genome_001",
                taxon_id="9606",
                sequence_id="seq_002",
                protein_id="prot_002",
                repeat_residue="Q",
                start=2,
                end=10,
                aa_sequence="QQAQQQQQQ",
                source_file=str((tmp / "proteins.faa").resolve()),
                window_definition="Q6/8",
                merge_rule="merge_adjacent_or_overlap",
            )
        ]
        write_tsv(pure_calls, pure_rows, fieldnames=CALL_FIELDNAMES)
        write_tsv(threshold_calls, threshold_rows, fieldnames=CALL_FIELDNAMES)

        summary_rows = [
            {
                "method": "pure",
                "repeat_residue": "Q",
                "taxon_id": "9606",
                "taxon_name": "Homo sapiens",
                "n_genomes": "1",
                "n_proteins": "2",
                "n_calls": "99" if corrupt_summary else "2",
                "mean_length": "6.5",
                "mean_purity": "1",
                "codon_metric_name": "",
                "mean_codon_metric": "",
                "median_length": "6.5",
                "max_length": "7",
                "mean_start_fraction": "0.125",
            },
            {
                "method": "threshold",
                "repeat_residue": "Q",
                "taxon_id": "9606",
                "taxon_name": "Homo sapiens",
                "n_genomes": "1",
                "n_proteins": "1",
                "n_calls": "1",
                "mean_length": "9",
                "mean_purity": "0.8888888889",
                "codon_metric_name": "",
                "mean_codon_metric": "",
                "median_length": "9",
                "max_length": "9",
                "mean_start_fraction": "0.1",
            },
        ]
        regression_rows = [
            {
                "method": "pure",
                "repeat_residue": "Q",
                "group_label": "Homo sapiens",
                "repeat_length": "6",
                "n_observations": "1",
                "codon_metric_name": "",
                "mean_codon_metric": "",
                "filtered_max_length": "",
                "transformed_codon_metric": "",
            },
            {
                "method": "pure",
                "repeat_residue": "Q",
                "group_label": "Homo sapiens",
                "repeat_length": "7",
                "n_observations": "1",
                "codon_metric_name": "",
                "mean_codon_metric": "",
                "filtered_max_length": "",
                "transformed_codon_metric": "",
            },
            {
                "method": "threshold",
                "repeat_residue": "Q",
                "group_label": "Homo sapiens",
                "repeat_length": "9",
                "n_observations": "1",
                "codon_metric_name": "",
                "mean_codon_metric": "",
                "filtered_max_length": "",
                "transformed_codon_metric": "",
            },
        ]
        write_tsv(
            summary,
            summary_rows,
            fieldnames=[
                "method",
                "repeat_residue",
                "taxon_id",
                "taxon_name",
                "n_genomes",
                "n_proteins",
                "n_calls",
                "mean_length",
                "mean_purity",
                "codon_metric_name",
                "mean_codon_metric",
                "median_length",
                "max_length",
                "mean_start_fraction",
            ],
        )
        write_tsv(
            regression,
            regression_rows,
            fieldnames=[
                "method",
                "repeat_residue",
                "group_label",
                "repeat_length",
                "n_observations",
                "codon_metric_name",
                "mean_codon_metric",
                "filtered_max_length",
                "transformed_codon_metric",
            ],
        )

        acquisition_validation.write_text(json.dumps({"status": "warn"}) + "\n", encoding="utf-8")
        sqlite_validation.write_text(json.dumps({"status": "pass"}) + "\n", encoding="utf-8")

        return {
            "taxonomy": taxonomy,
            "genomes": genomes,
            "proteins": proteins,
            "pure_calls": pure_calls,
            "threshold_calls": threshold_calls,
            "summary": summary,
            "regression": regression,
            "acquisition_validation": acquisition_validation,
            "sqlite_validation": sqlite_validation,
            "report": report,
        }


if __name__ == "__main__":
    unittest.main()
