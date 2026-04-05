from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from lib.detect_blast import find_template_local_tracts
from lib.repeat_features import validate_call_row
from lib.tsv_io import read_tsv, write_tsv


REPO_ROOT = Path(__file__).resolve().parents[1]


class SliceFiveBlastDetectionTest(unittest.TestCase):
    def test_find_template_local_tracts_reproduces_phase2_worked_example(self) -> None:
        tracts = find_template_local_tracts("MQAASTAAQAAVAP", "A")
        self.assertEqual(len(tracts), 1)
        tract = tracts[0]
        self.assertEqual((tract.start, tract.end, tract.aa_sequence, tract.score), (3, 13, "AASTAAQAAVA", 10))

    def test_find_template_local_tracts_merges_close_positive_segments(self) -> None:
        tracts = find_template_local_tracts("MAAAAAAQAAAAAAM", "A")
        self.assertEqual(len(tracts), 1)
        tract = tracts[0]
        self.assertEqual((tract.start, tract.end, tract.aa_sequence), (2, 14, "AAAAAAQAAAAAA"))
        self.assertEqual(tract.score, 23)

    def test_detect_blast_cli_writes_calls_and_run_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            inputs_dir = tmp / "merged" / "acquisition"
            outdir = tmp / "merged" / "detection" / "blast"
            inputs_dir.mkdir(parents=True, exist_ok=True)

            proteins_tsv = inputs_dir / "proteins.tsv"
            proteins_faa = inputs_dir / "proteins.faa"
            write_tsv(
                proteins_tsv,
                [
                    {
                        "protein_id": "prot_blast_1",
                        "sequence_id": "seq_blast_1",
                        "genome_id": "genome_001",
                        "protein_name": "blast_example",
                        "protein_length": 14,
                        "protein_path": str(proteins_faa.resolve()),
                        "gene_symbol": "GENE1",
                        "translation_method": "local_cds_translation",
                        "translation_status": "translated",
                        "assembly_accession": "GCF_TEST_1.1",
                        "taxon_id": "9606",
                        "gene_group": "GENE1",
                        "protein_external_id": "NP_TEST_BLAST.1",
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
            proteins_faa.write_text(">prot_blast_1\nMQAASTAAQAAVAP\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "detect_blast.py"),
                    "--proteins-tsv",
                    str(proteins_tsv),
                    "--proteins-fasta",
                    str(proteins_faa),
                    "--repeat-residue",
                    "A",
                    "--backend",
                    "template_local",
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
                    f"detect_blast.py failed with exit code {result.returncode}\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            call_rows = read_tsv(outdir / "blast_calls.tsv")
            param_rows = read_tsv(outdir / "run_params.tsv")

            self.assertEqual(len(call_rows), 1)
            row = call_rows[0]
            validate_call_row(row)
            self.assertEqual(row["method"], "blast")
            self.assertEqual(row["protein_id"], "prot_blast_1")
            self.assertEqual(row["start"], "3")
            self.assertEqual(row["end"], "13")
            self.assertEqual(row["aa_sequence"], "AASTAAQAAVA")
            self.assertEqual(row["repeat_residue"], "A")
            self.assertEqual(row["repeat_count"], "7")
            self.assertEqual(row["non_repeat_count"], "4")
            self.assertEqual(row["length"], "11")
            self.assertEqual(row["purity"], "0.6363636364")
            self.assertEqual(row["template_name"], "A10")
            self.assertEqual(row["score"], "10")
            self.assertEqual(row["merge_rule"], "positive_segment_gap<=5")

            self.assertEqual(
                {(item["param_name"], item["param_value"]) for item in param_rows},
                {
                    ("backend", "template_local"),
                    ("repeat_residue", "A"),
                    ("template_length", "10"),
                    ("template_name", "A10"),
                    ("match_score", "2"),
                    ("mismatch_score", "-1"),
                    ("min_repeat_count", "6"),
                    ("merge_gap_max", "5"),
                },
            )

    def test_detect_blast_cli_runs_diamond_backend_via_stubbed_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            inputs_dir = tmp / "merged" / "acquisition"
            outdir = tmp / "merged" / "detection" / "blast"
            fake_bin_dir = tmp / "fake_bin"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            fake_bin_dir.mkdir(parents=True, exist_ok=True)
            self._write_fake_diamond(fake_bin_dir / "diamond")

            proteins_tsv = inputs_dir / "proteins.tsv"
            proteins_faa = inputs_dir / "proteins.faa"
            write_tsv(
                proteins_tsv,
                [
                    {
                        "protein_id": "prot_blast_1",
                        "sequence_id": "seq_blast_1",
                        "genome_id": "genome_001",
                        "protein_name": "blast_example",
                        "protein_length": 14,
                        "protein_path": str(proteins_faa.resolve()),
                        "taxon_id": "9606",
                    }
                ],
                fieldnames=[
                    "protein_id",
                    "sequence_id",
                    "genome_id",
                    "protein_name",
                    "protein_length",
                    "protein_path",
                    "taxon_id",
                ],
            )
            proteins_faa.write_text(">prot_blast_1\nMQAASTAAQAAVAP\n", encoding="utf-8")

            env = dict(os.environ)
            env["PATH"] = f"{fake_bin_dir}:{env.get('PATH', '')}"

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "detect_blast.py"),
                    "--proteins-tsv",
                    str(proteins_tsv),
                    "--proteins-fasta",
                    str(proteins_faa),
                    "--repeat-residue",
                    "A",
                    "--backend",
                    "diamond_blastp",
                    "--outdir",
                    str(outdir),
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.fail(
                    f"detect_blast.py failed with exit code {result.returncode}\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            call_rows = read_tsv(outdir / "blast_calls.tsv")
            param_rows = read_tsv(outdir / "run_params.tsv")

            self.assertEqual(len(call_rows), 1)
            row = call_rows[0]
            validate_call_row(row)
            self.assertEqual(row["method"], "blast")
            self.assertEqual(row["protein_id"], "prot_blast_1")
            self.assertEqual(row["start"], "3")
            self.assertEqual(row["end"], "13")
            self.assertEqual(row["aa_sequence"], "AASTAAQAAVA")
            self.assertEqual(row["repeat_count"], "7")
            self.assertEqual(row["non_repeat_count"], "4")
            self.assertEqual(row["length"], "11")
            self.assertEqual(row["template_name"], "A10")
            self.assertEqual(row["merge_rule"], "diamond_hsp_trim")
            self.assertAlmostEqual(float(row["score"]), 42.0)

            self.assertEqual(
                {(item["param_name"], item["param_value"]) for item in param_rows},
                {
                    ("backend", "diamond_blastp"),
                    ("repeat_residue", "A"),
                    ("template_length", "10"),
                    ("template_name", "A10"),
                    ("min_repeat_count", "6"),
                    ("diamond_evalue", "1000.0"),
                    ("diamond_max_target_seqs", "1"),
                    ("diamond_masking", "0"),
                },
            )

    def _write_fake_diamond(self, path: Path) -> None:
        path.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import sys
                from pathlib import Path

                argv = sys.argv[1:]
                command = argv[0]

                def arg_value(flag: str) -> str:
                    index = argv.index(flag)
                    return argv[index + 1]

                if command == "makedb":
                    db_prefix = Path(arg_value("--db"))
                    db_prefix.parent.mkdir(parents=True, exist_ok=True)
                    db_prefix.with_suffix(".dmnd").write_text("fake db", encoding="utf-8")
                    raise SystemExit(0)

                if command == "blastp":
                    out_path = Path(arg_value("--out"))
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(
                        "\\n".join(
                            [
                                "prot_blast_1\\tA10\\t30.0\\t2\\t13\\t1\\t10\\t58.3\\t12\\t1e-03",
                                "prot_blast_1\\tA10\\t42.0\\t2\\t13\\t1\\t10\\t70.0\\t12\\t1e-05",
                            ]
                        )
                        + "\\n",
                        encoding="utf-8",
                    )
                    raise SystemExit(0)

                raise SystemExit(2)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
