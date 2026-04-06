from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.summaries import build_echarts_options, serialize_echarts_options
from lib.tsv_io import write_tsv


REPO_ROOT = Path(__file__).resolve().parents[1]


class PhaseSixReportRenderTest(unittest.TestCase):
    def test_render_echarts_report_writes_html_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            summary = tmp / "summary_by_taxon.tsv"
            regression = tmp / "regression_input.tsv"
            options_json = tmp / "echarts_options.json"
            outdir = tmp / "report"

            summary_rows, regression_rows = self._build_rows()
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
                ],
            )
            options_json.write_text(
                serialize_echarts_options(build_echarts_options(summary_rows, regression_rows)),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "render_echarts_report.py"),
                    "--summary-tsv",
                    str(summary),
                    "--regression-tsv",
                    str(regression),
                    "--options-json",
                    str(options_json),
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
                    f"render_echarts_report.py failed unexpectedly with exit code {result.returncode}\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            html = (outdir / "echarts_report.html").read_text(encoding="utf-8")
            self.assertTrue((outdir / "echarts.min.js").is_file())
            self.assertIn("chart-taxon_method_overview", html)
            self.assertIn("chart-repeat_length_distribution", html)
            self.assertIn('src="./echarts.min.js"', html)
            self.assertIn("Methods", html)
            self.assertIn("pure, threshold", html)
            self.assertIn("Repeat Residues", html)
            self.assertIn("Q", html)
            self.assertIn("Total Calls", html)
            self.assertIn(">16<", html)

    def test_render_echarts_report_requires_minimal_chart_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            summary = tmp / "summary_by_taxon.tsv"
            regression = tmp / "regression_input.tsv"
            options_json = tmp / "echarts_options.json"
            outdir = tmp / "report"

            summary_rows, regression_rows = self._build_rows()
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
                ],
            )
            options_json.write_text(
                json.dumps({"taxon_method_overview": {"title": {"text": "Only one chart"}}}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "render_echarts_report.py"),
                    "--summary-tsv",
                    str(summary),
                    "--regression-tsv",
                    str(regression),
                    "--options-json",
                    str(options_json),
                    "--outdir",
                    str(outdir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 3)
            self.assertIn("missing required chart blocks", result.stderr)

    def _build_rows(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        summary_rows = [
            {
                "method": "pure",
                "repeat_residue": "Q",
                "taxon_id": "9606",
                "taxon_name": "Homo sapiens",
                "n_genomes": "1",
                "n_proteins": "4",
                "n_calls": "6",
                "mean_length": "8.5",
                "mean_purity": "1",
            },
            {
                "method": "threshold",
                "repeat_residue": "Q",
                "taxon_id": "9606",
                "taxon_name": "Homo sapiens",
                "n_genomes": "1",
                "n_proteins": "5",
                "n_calls": "10",
                "mean_length": "11.2",
                "mean_purity": "0.8",
            },
        ]
        regression_rows = [
            {
                "method": "pure",
                "repeat_residue": "Q",
                "group_label": "Homo sapiens",
                "repeat_length": "6",
                "n_observations": "2",
            },
            {
                "method": "threshold",
                "repeat_residue": "Q",
                "group_label": "Homo sapiens",
                "repeat_length": "8",
                "n_observations": "3",
            },
        ]
        return summary_rows, regression_rows
