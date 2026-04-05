from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.repeat_features import CALL_FIELDNAMES, build_call_row
from lib.tsv_io import read_tsv, write_tsv


REPO_ROOT = Path(__file__).resolve().parents[1]


class SliceEightSummariesTest(unittest.TestCase):
    def test_export_summary_tables_and_prepare_report_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            acquisition_dir = tmp / "merged" / "acquisition"
            calls_dir = tmp / "merged" / "calls"
            reports_dir = tmp / "merged" / "reports"
            acquisition_dir.mkdir(parents=True, exist_ok=True)
            calls_dir.mkdir(parents=True, exist_ok=True)

            taxonomy_tsv = acquisition_dir / "taxonomy.tsv"
            proteins_tsv = acquisition_dir / "proteins.tsv"
            pure_calls_tsv = calls_dir / "pure_calls.tsv"
            threshold_calls_tsv = calls_dir / "threshold_calls.tsv"

            write_tsv(
                taxonomy_tsv,
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
                proteins_tsv,
                [
                    {
                        "protein_id": "prot_001",
                        "sequence_id": "seq_001",
                        "genome_id": "genome_001",
                        "protein_name": "PROT1",
                        "protein_length": 10,
                        "protein_path": str((acquisition_dir / "proteins.faa").resolve()),
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
                        "protein_path": str((acquisition_dir / "proteins.faa").resolve()),
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
                    source_file=str((acquisition_dir / "proteins.faa").resolve()),
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
                    source_file=str((acquisition_dir / "proteins.faa").resolve()),
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
                    source_file=str((acquisition_dir / "proteins.faa").resolve()),
                    window_definition="Q6/8",
                    merge_rule="merge_adjacent_or_overlap",
                )
            ]
            write_tsv(pure_calls_tsv, pure_rows, fieldnames=CALL_FIELDNAMES)
            write_tsv(threshold_calls_tsv, threshold_rows, fieldnames=CALL_FIELDNAMES)

            export_result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "export_summary_tables.py"),
                    "--taxonomy-tsv",
                    str(taxonomy_tsv),
                    "--proteins-tsv",
                    str(proteins_tsv),
                    "--call-tsv",
                    str(pure_calls_tsv),
                    "--call-tsv",
                    str(threshold_calls_tsv),
                    "--outdir",
                    str(reports_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if export_result.returncode != 0:
                self.fail(
                    f"export_summary_tables.py failed with exit code {export_result.returncode}\n"
                    f"stdout:\n{export_result.stdout}\n"
                    f"stderr:\n{export_result.stderr}"
                )

            summary_rows = read_tsv(reports_dir / "summary_by_taxon.tsv")
            regression_rows = read_tsv(reports_dir / "regression_input.tsv")
            self.assertEqual(len(summary_rows), 2)
            self.assertEqual(len(regression_rows), 3)

            pure_summary = next(row for row in summary_rows if row["method"] == "pure")
            self.assertEqual(pure_summary["taxon_name"], "Homo sapiens")
            self.assertEqual(pure_summary["repeat_residue"], "Q")
            self.assertEqual(pure_summary["n_genomes"], "1")
            self.assertEqual(pure_summary["n_proteins"], "2")
            self.assertEqual(pure_summary["n_calls"], "2")
            self.assertEqual(pure_summary["mean_length"], "6.5")
            self.assertEqual(pure_summary["median_length"], "6.5")
            self.assertEqual(pure_summary["max_length"], "7")
            self.assertEqual(pure_summary["mean_purity"], "1")
            self.assertEqual(pure_summary["mean_start_fraction"], "0.125")
            self.assertEqual(pure_summary["codon_metric_name"], "")
            self.assertEqual(pure_summary["mean_codon_metric"], "")

            report_result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "prepare_report_tables.py"),
                    "--summary-tsv",
                    str(reports_dir / "summary_by_taxon.tsv"),
                    "--regression-tsv",
                    str(reports_dir / "regression_input.tsv"),
                    "--outdir",
                    str(reports_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if report_result.returncode != 0:
                self.fail(
                    f"prepare_report_tables.py failed with exit code {report_result.returncode}\n"
                    f"stdout:\n{report_result.stdout}\n"
                    f"stderr:\n{report_result.stderr}"
                )

            options = json.loads((reports_dir / "echarts_options.json").read_text(encoding="utf-8"))
            self.assertIn("taxon_method_overview", options)
            self.assertIn("repeat_length_distribution", options)
            overview = options["taxon_method_overview"]
            self.assertEqual(overview["series"][0]["data"], [2, 1])
            scatter = options["repeat_length_distribution"]["dataset"]["source"]
            self.assertEqual(len(scatter), 3)
            self.assertEqual({row["group_label"] for row in scatter}, {"Homo sapiens"})
