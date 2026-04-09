import csv
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from apps.imports.services import ImportContractError, load_published_run

from .support import build_minimal_publish_root, build_multibatch_publish_root


SIBLING_PIPELINE_RUNS_ROOT = Path(__file__).resolve().parents[2] / "homorepeat_pipeline" / "runs"
SMALL_REAL_RUN_ID = "live_raw_effective_params_2026_04_09"
LARGE_REAL_RUN_ID = "chr_all3_raw_2026_04_09"


def _sibling_publish_root(run_id: str) -> Path:
    return SIBLING_PIPELINE_RUNS_ROOT / run_id / "publish"


def _tsv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return sum(1 for _ in reader)


def _unique_tsv_row_count(paths: list[Path], key_fields: list[str]) -> int:
    keys = set()
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                keys.add(tuple((row.get(field) or "").strip() for field in key_fields))
    return len(keys)


def _tsv_value_set(path: Path, field_name: str) -> set[str]:
    values = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            value = (row.get(field_name) or "").strip()
            if value:
                values.add(value)
    return values


def _sum_tsv_int_column(path: Path, field_name: str) -> int:
    total = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            total += int((row.get(field_name) or "0").strip())
    return total


def _sum_tsv_row_counts(paths: list[Path]) -> int:
    return sum(_tsv_row_count(path) for path in paths)


class PublishedRunImportServiceTests(SimpleTestCase):
    def test_load_published_run_parses_real_small_raw_run_from_sibling_pipeline(self):
        publish_root = _sibling_publish_root(SMALL_REAL_RUN_ID)
        if not publish_root.exists():
            self.skipTest(f"requires sibling pipeline run at {publish_root}")

        payload = load_published_run(publish_root)
        batch_paths = list(sorted((publish_root / "acquisition" / "batches").glob("*/")))

        self.assertEqual(payload.pipeline_run["run_id"], SMALL_REAL_RUN_ID)
        self.assertEqual(payload.manifest["acquisition_publish_mode"], "raw")
        self.assertEqual(len(payload.artifact_paths.acquisition_batches), 1)
        self.assertEqual(len(payload.batch_summaries), 1)
        self.assertEqual(payload.genome_rows[0]["batch_id"], payload.artifact_paths.acquisition_batches[0].batch_id)
        self.assertEqual({row["method"] for row in payload.run_parameter_rows}, {"pure", "threshold"})
        self.assertEqual({row["repeat_residue"] for row in payload.run_parameter_rows}, {"Q"})
        self.assertEqual(
            len(payload.taxonomy_rows),
            _unique_tsv_row_count(
                [batch_path / "taxonomy.tsv" for batch_path in batch_paths],
                ["taxon_id"],
            ),
        )
        self.assertEqual(
            len(payload.genome_rows),
            _unique_tsv_row_count(
                [batch_path / "genomes.tsv" for batch_path in batch_paths],
                ["genome_id"],
            ),
        )
        self.assertEqual(
            len(payload.sequence_rows),
            _unique_tsv_row_count(
                [batch_path / "sequences.tsv" for batch_path in batch_paths],
                ["sequence_id"],
            ),
        )
        self.assertEqual(
            len(payload.protein_rows),
            _unique_tsv_row_count(
                [batch_path / "proteins.tsv" for batch_path in batch_paths],
                ["protein_id"],
            ),
        )
        self.assertEqual(
            len(payload.run_parameter_rows),
            _unique_tsv_row_count(
                [publish_root / "calls" / "run_params.tsv"],
                ["method", "repeat_residue", "param_name"],
            ),
        )
        self.assertEqual(
            len(payload.repeat_call_rows),
            _tsv_row_count(publish_root / "calls" / "repeat_calls.tsv"),
        )
        self.assertEqual(
            len(payload.accession_status_rows),
            _unique_tsv_row_count(
                [publish_root / "status" / "accession_status.tsv"],
                ["assembly_accession"],
            ),
        )
        self.assertEqual(
            len(payload.accession_call_count_rows),
            _unique_tsv_row_count(
                [publish_root / "status" / "accession_call_counts.tsv"],
                ["assembly_accession", "method", "repeat_residue"],
            ),
        )
        self.assertEqual(
            len(payload.download_manifest_rows),
            _sum_tsv_row_counts([batch_path / "download_manifest.tsv" for batch_path in batch_paths]),
        )
        self.assertEqual(
            len(payload.normalization_warning_rows),
            _sum_tsv_row_counts([batch_path / "normalization_warnings.tsv" for batch_path in batch_paths]),
        )
        self.assertEqual(payload.batch_summaries[0].acquisition_validation["scope"], "batch")
        self.assertEqual(payload.batch_summaries[0].total_repeat_calls, len(payload.repeat_call_rows))
        self.assertEqual(
            payload.batch_summaries[0].total_repeat_linked_sequences,
            len(payload.repeat_linked_ids.sequence_ids),
        )
        self.assertEqual(
            payload.batch_summaries[0].total_repeat_linked_proteins,
            len(payload.repeat_linked_ids.protein_ids),
        )

    def test_load_published_run_rejects_missing_required_file(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "acquisition" / "batches" / "batch_0001" / "genomes.tsv").unlink()

            with self.assertRaises(ImportContractError):
                load_published_run(publish_root)

    def test_load_published_run_rejects_malformed_manifest(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "metadata" / "run_manifest.json").write_text("{", encoding="utf-8")

            with self.assertRaises(ImportContractError):
                load_published_run(publish_root)

    def test_load_published_run_rejects_missing_required_columns(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "acquisition" / "batches" / "batch_0001" / "genomes.tsv").write_text(
                "genome_id\tsource\tgenome_name\tassembly_type\ttaxon_id\n"
                "genome_1\tncbi_datasets\tExample genome\thaploid\t9606\n",
                encoding="utf-8",
            )

            with self.assertRaises(ImportContractError):
                load_published_run(publish_root)

    def test_load_published_run_rejects_manifest_missing_required_keys(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "metadata" / "run_manifest.json").write_text(
                json.dumps({"run_id": "run-alpha"}, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ImportContractError):
                load_published_run(publish_root)

    def test_load_published_run_preserves_full_raw_taxonomy(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "acquisition" / "batches" / "batch_0001" / "taxonomy.tsv").write_text(
                "taxon_id\ttaxon_name\tparent_taxon_id\trank\tsource\n"
                "1\troot\t\tno rank\ttest\n"
                "131567\tcellular organisms\t1\tno rank\ttest\n"
                "2759\tEukaryota\t131567\tsuperkingdom\ttest\n"
                "33208\tMetazoa\t2759\tkingdom\ttest\n"
                "7711\tChordata\t33208\tphylum\ttest\n"
                "7742\tVertebrata\t7711\tno rank\ttest\n"
                "40674\tMammalia\t7742\tclass\ttest\n"
                "314146\tEuarchontoglires\t40674\tno rank\ttest\n"
                "9443\tPrimates\t314146\torder\ttest\n"
                "9604\tHominidae\t9443\tfamily\ttest\n"
                "9605\tHomo\t9604\tgenus\ttest\n"
                "9606\tHomo sapiens\t9605\tspecies\ttest\n",
                encoding="utf-8",
            )

            payload = load_published_run(publish_root)

            taxonomy_by_id = {row["taxon_id"]: row for row in payload.taxonomy_rows}
            self.assertEqual(len(taxonomy_by_id), 12)
            self.assertIn(131567, taxonomy_by_id)
            self.assertIn(7742, taxonomy_by_id)
            self.assertIn(314146, taxonomy_by_id)
            self.assertIsNone(taxonomy_by_id[1]["parent_taxon_id"])
            self.assertEqual(taxonomy_by_id[2759]["parent_taxon_id"], 131567)
            self.assertEqual(taxonomy_by_id[40674]["parent_taxon_id"], 7742)
            self.assertEqual(taxonomy_by_id[9443]["parent_taxon_id"], 314146)
            self.assertEqual(taxonomy_by_id[9606]["parent_taxon_id"], 9605)

    def test_load_published_run_rejects_non_raw_publish_mode(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            manifest_path = publish_root / "metadata" / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["acquisition_publish_mode"] = "merged"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaises(ImportContractError):
                load_published_run(publish_root)

    def test_load_published_run_accepts_seed_extend_and_repeat_residue_scoped_params(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "calls" / "run_params.tsv").write_text(
                "method\trepeat_residue\tparam_name\tparam_value\n"
                "seed_extend\tQ\tseed_window_size\t8\n",
                encoding="utf-8",
            )
            (publish_root / "calls" / "repeat_calls.tsv").write_text(
                "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
                "call_1\tseed_extend\tgenome_1\t9606\tseq_1\tprot_1\t10\t22\t13\tQ\t11\t2\t0.8461538462\tQQQQQAQQQQQQQ\t\t\t\tseed:Q6/8|extend:Q8/12\t\tseed_extend_connected_windows\t\n",
                encoding="utf-8",
            )

            payload = load_published_run(publish_root)

            self.assertEqual(payload.run_parameter_rows[0]["method"], "seed_extend")
            self.assertEqual(payload.run_parameter_rows[0]["repeat_residue"], "Q")
            self.assertEqual(payload.repeat_call_rows[0]["method"], "seed_extend")

    def test_load_published_run_supports_multi_batch_raw_layout(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_multibatch_publish_root(Path(tempdir))

            payload = load_published_run(publish_root)

            self.assertEqual(
                [batch.batch_id for batch in payload.artifact_paths.acquisition_batches],
                ["batch_0001", "batch_0002"],
            )
            self.assertEqual(len(payload.taxonomy_rows), 3)
            self.assertEqual(len(payload.genome_rows), 2)
            self.assertEqual(len(payload.sequence_rows), 3)
            self.assertEqual(len(payload.protein_rows), 3)
            self.assertEqual(len(payload.repeat_call_rows), 2)
            self.assertEqual(len(payload.download_manifest_rows), 2)
            self.assertEqual(len(payload.normalization_warning_rows), 1)
            self.assertEqual(len(payload.accession_status_rows), 2)
            self.assertEqual(len(payload.accession_call_count_rows), 2)
            self.assertEqual(payload.repeat_linked_ids.genome_ids, ("genome_1", "genome_2"))
            self.assertEqual(payload.repeat_linked_ids.sequence_ids, ("seq_1", "seq_3"))
            self.assertEqual(payload.repeat_linked_ids.protein_ids, ("prot_1", "prot_3"))
            self.assertEqual(
                Counter(row["batch_id"] for row in payload.genome_rows),
                Counter({"batch_0001": 1, "batch_0002": 1}),
            )
            self.assertEqual(
                Counter(row["batch_id"] for row in payload.sequence_rows),
                Counter({"batch_0001": 2, "batch_0002": 1}),
            )
            self.assertEqual(
                Counter(row["batch_id"] for row in payload.protein_rows),
                Counter({"batch_0001": 2, "batch_0002": 1}),
            )
            batch_summaries = {summary.artifact_paths.batch_id: summary for summary in payload.batch_summaries}
            self.assertEqual(batch_summaries["batch_0001"].total_genomes, 1)
            self.assertEqual(batch_summaries["batch_0001"].total_sequences, 2)
            self.assertEqual(batch_summaries["batch_0001"].total_proteins, 2)
            self.assertEqual(batch_summaries["batch_0001"].total_download_manifest_rows, 1)
            self.assertEqual(batch_summaries["batch_0001"].total_normalization_warning_rows, 0)
            self.assertEqual(batch_summaries["batch_0001"].total_repeat_calls, 1)
            self.assertEqual(batch_summaries["batch_0001"].total_repeat_linked_sequences, 1)
            self.assertEqual(batch_summaries["batch_0001"].total_repeat_linked_proteins, 1)
            self.assertEqual(batch_summaries["batch_0001"].acquisition_validation["status"], "pass")
            self.assertEqual(batch_summaries["batch_0002"].total_genomes, 1)
            self.assertEqual(batch_summaries["batch_0002"].total_sequences, 1)
            self.assertEqual(batch_summaries["batch_0002"].total_proteins, 1)
            self.assertEqual(batch_summaries["batch_0002"].total_download_manifest_rows, 1)
            self.assertEqual(batch_summaries["batch_0002"].total_normalization_warning_rows, 1)
            self.assertEqual(batch_summaries["batch_0002"].total_repeat_calls, 1)
            self.assertEqual(batch_summaries["batch_0002"].total_repeat_linked_sequences, 1)
            self.assertEqual(batch_summaries["batch_0002"].total_repeat_linked_proteins, 1)
            self.assertEqual(batch_summaries["batch_0002"].acquisition_validation["status"], "warn")

    def test_load_published_run_parses_large_real_raw_run_without_db_import(self):
        publish_root = _sibling_publish_root(LARGE_REAL_RUN_ID)
        if not publish_root.exists():
            self.skipTest(f"requires sibling pipeline run at {publish_root}")

        payload = load_published_run(publish_root)
        batch_paths = list(sorted((publish_root / "acquisition" / "batches").glob("*/")))

        self.assertEqual(payload.pipeline_run["run_id"], LARGE_REAL_RUN_ID)
        self.assertEqual(len(payload.batch_summaries), len(batch_paths))
        self.assertEqual(
            len(payload.download_manifest_rows),
            _sum_tsv_row_counts([batch_path / "download_manifest.tsv" for batch_path in batch_paths]),
        )
        self.assertEqual(
            len(payload.normalization_warning_rows),
            _sum_tsv_row_counts([batch_path / "normalization_warnings.tsv" for batch_path in batch_paths]),
        )
        self.assertEqual(
            sum(summary.total_repeat_calls for summary in payload.batch_summaries),
            len(payload.repeat_call_rows),
        )
        self.assertGreater(len(payload.repeat_linked_ids.sequence_ids), 0)
        self.assertGreater(len(payload.repeat_linked_ids.protein_ids), 0)
        self.assertTrue(
            all(summary.acquisition_validation.get("scope") == "batch" for summary in payload.batch_summaries)
        )

    def test_large_real_raw_run_contract_counts_align_without_db_import(self):
        publish_root = _sibling_publish_root(LARGE_REAL_RUN_ID)
        if not publish_root.exists():
            self.skipTest(f"requires sibling pipeline run at {publish_root}")

        manifest = json.loads((publish_root / "metadata" / "run_manifest.json").read_text(encoding="utf-8"))
        batch_dirs = sorted(path for path in (publish_root / "acquisition" / "batches").iterdir() if path.is_dir())
        run_params_path = publish_root / "calls" / "run_params.tsv"
        repeat_calls_path = publish_root / "calls" / "repeat_calls.tsv"
        accession_status_path = publish_root / "status" / "accession_status.tsv"
        accession_call_counts_path = publish_root / "status" / "accession_call_counts.tsv"

        self.assertEqual(manifest["run_id"], LARGE_REAL_RUN_ID)
        self.assertEqual(manifest["acquisition_publish_mode"], "raw")
        self.assertEqual(set(manifest["enabled_methods"]), {"pure", "threshold", "seed_extend"})
        self.assertEqual(set(manifest["repeat_residues"]), {"Q"})
        self.assertEqual(len(batch_dirs), 91)

        for batch_dir in batch_dirs[:3]:
            self.assertTrue((batch_dir / "genomes.tsv").is_file())
            self.assertTrue((batch_dir / "taxonomy.tsv").is_file())
            self.assertTrue((batch_dir / "sequences.tsv").is_file())
            self.assertTrue((batch_dir / "proteins.tsv").is_file())
            self.assertTrue((batch_dir / "cds.fna").is_file())
            self.assertTrue((batch_dir / "proteins.faa").is_file())

        self.assertEqual(
            _tsv_value_set(run_params_path, "method"),
            {"pure", "threshold", "seed_extend"},
        )
        self.assertEqual(_tsv_value_set(run_params_path, "repeat_residue"), {"Q"})
        self.assertEqual(_tsv_value_set(repeat_calls_path, "method"), {"pure", "threshold", "seed_extend"})
        self.assertEqual(_tsv_value_set(repeat_calls_path, "repeat_residue"), {"Q"})
        self.assertEqual(
            _tsv_value_set(accession_call_counts_path, "method"),
            {"pure", "threshold", "seed_extend"},
        )
        self.assertEqual(_tsv_value_set(accession_call_counts_path, "repeat_residue"), {"Q"})

        self.assertEqual(
            len(batch_dirs),
            _unique_tsv_row_count([accession_status_path], ["batch_id"]),
        )
        self.assertEqual(
            _tsv_row_count(repeat_calls_path),
            _sum_tsv_int_column(accession_status_path, "n_repeat_calls"),
        )
        self.assertEqual(
            _tsv_row_count(repeat_calls_path),
            _sum_tsv_int_column(accession_call_counts_path, "n_repeat_calls"),
        )
