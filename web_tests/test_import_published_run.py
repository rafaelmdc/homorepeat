import csv
import json
import os
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from apps.imports.services.published_run import (
    ImportContractError,
    inspect_published_run,
    iter_codon_usage_artifact_rows,
    iter_accession_call_count_rows,
    iter_accession_status_rows,
    iter_download_manifest_rows,
    iter_genome_rows,
    iter_normalization_warning_rows,
    iter_protein_rows,
    iter_repeat_call_rows,
    iter_run_parameter_rows,
    iter_sequence_rows,
    iter_taxonomy_rows,
    load_published_run,
)

from .support import add_finalized_codon_usage_artifact, build_minimal_publish_root, build_multibatch_publish_root


SIBLING_PIPELINE_RUNS_ROOT = Path(__file__).resolve().parents[2] / "homorepeat_pipeline" / "runs"
SMALL_REAL_RUN_ID = "live_raw_effective_params_2026_04_09"
LARGE_REAL_RUN_ID = "chr_all3_raw_2026_04_09"
RUN_LARGE_REAL_RUN_TESTS = os.environ.get("HOMOREPEAT_RUN_LARGE_IMPORT_TESTS", "").strip() == "1"


def _sibling_publish_root(run_id: str) -> Path:
    return SIBLING_PIPELINE_RUNS_ROOT / run_id / "publish"


def _require_large_real_run_validation(test_case: SimpleTestCase) -> Path:
    if not RUN_LARGE_REAL_RUN_TESTS:
        test_case.skipTest(
            "large real-run import contract checks are manual final validation; "
            "set HOMOREPEAT_RUN_LARGE_IMPORT_TESTS=1 to run them"
        )
    publish_root = _sibling_publish_root(LARGE_REAL_RUN_ID)
    if not publish_root.exists():
        test_case.skipTest(f"requires sibling pipeline run at {publish_root}")
    return publish_root


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


def _stream_tsv_stats(
    path: Path,
    *,
    value_fields: list[str] | None = None,
    distinct_fields: list[str] | None = None,
    sum_int_fields: list[str] | None = None,
) -> dict[str, object]:
    value_fields = value_fields or []
    distinct_fields = distinct_fields or []
    sum_int_fields = sum_int_fields or []
    value_sets = {field: set() for field in value_fields}
    distinct_sets = {field: set() for field in distinct_fields}
    int_sums = {field: 0 for field in sum_int_fields}
    row_count = 0

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            row_count += 1
            for field in value_fields:
                value = (row.get(field) or "").strip()
                if value:
                    value_sets[field].add(value)
            for field in distinct_fields:
                value = (row.get(field) or "").strip()
                if value:
                    distinct_sets[field].add(value)
            for field in sum_int_fields:
                int_sums[field] += int((row.get(field) or "0").strip())

    return {
        "row_count": row_count,
        "value_sets": value_sets,
        "distinct_counts": {field: len(values) for field, values in distinct_sets.items()},
        "int_sums": int_sums,
    }


def _iter_batch_rows(inspected, *, path_attr: str, iterator, include_batch_id: bool = False):
    for batch_paths in inspected.artifact_paths.acquisition_batches:
        kwargs = {"batch_id": batch_paths.batch_id} if include_batch_id else {}
        yield from iterator(getattr(batch_paths, path_attr), **kwargs)


def _merge_rows_by_key(rows, *, key_field: str):
    merged = {}
    ordered_keys = []
    for row in rows:
        key = row[key_field]
        if key not in merged:
            merged[key] = row
            ordered_keys.append(key)
            continue
        if merged[key] != row:
            raise AssertionError(f"conflicting duplicate rows for {key_field}={key!r}")
    return [merged[key] for key in ordered_keys]


class PublishedRunImportServiceTests(SimpleTestCase):
    def test_inspect_published_run_exposes_real_small_raw_run_with_streaming_iterators(self):
        publish_root = _sibling_publish_root(SMALL_REAL_RUN_ID)
        if not publish_root.exists():
            self.skipTest(f"requires sibling pipeline run at {publish_root}")

        inspected = inspect_published_run(publish_root)
        batch_paths = list(sorted((publish_root / "acquisition" / "batches").glob("*/")))
        taxonomy_rows = _merge_rows_by_key(
            list(_iter_batch_rows(inspected, path_attr="taxonomy_tsv", iterator=iter_taxonomy_rows)),
            key_field="taxon_id",
        )
        genome_rows = _merge_rows_by_key(
            list(
                _iter_batch_rows(
                    inspected,
                    path_attr="genomes_tsv",
                    iterator=iter_genome_rows,
                    include_batch_id=True,
                )
            ),
            key_field="genome_id",
        )
        sequence_rows = _merge_rows_by_key(
            list(
                _iter_batch_rows(
                    inspected,
                    path_attr="sequences_tsv",
                    iterator=iter_sequence_rows,
                    include_batch_id=True,
                )
            ),
            key_field="sequence_id",
        )
        protein_rows = _merge_rows_by_key(
            list(
                _iter_batch_rows(
                    inspected,
                    path_attr="proteins_tsv",
                    iterator=iter_protein_rows,
                    include_batch_id=True,
                )
            ),
            key_field="protein_id",
        )
        run_parameter_rows = list(iter_run_parameter_rows(inspected.artifact_paths.run_params_tsv))
        repeat_call_rows = list(iter_repeat_call_rows(inspected.artifact_paths.repeat_calls_tsv))
        accession_status_rows = list(iter_accession_status_rows(inspected.artifact_paths.accession_status_tsv))
        accession_call_count_rows = list(
            iter_accession_call_count_rows(inspected.artifact_paths.accession_call_counts_tsv)
        )
        download_manifest_rows = list(
            _iter_batch_rows(
                inspected,
                path_attr="download_manifest_tsv",
                iterator=iter_download_manifest_rows,
                include_batch_id=True,
            )
        )
        normalization_warning_rows = list(
            _iter_batch_rows(
                inspected,
                path_attr="normalization_warnings_tsv",
                iterator=iter_normalization_warning_rows,
                include_batch_id=True,
            )
        )
        repeat_linked_sequence_ids = {str(row["sequence_id"]) for row in repeat_call_rows}
        repeat_linked_protein_ids = {str(row["protein_id"]) for row in repeat_call_rows}

        self.assertEqual(inspected.pipeline_run["run_id"], SMALL_REAL_RUN_ID)
        self.assertEqual(inspected.manifest["acquisition_publish_mode"], "raw")
        self.assertEqual(len(inspected.artifact_paths.acquisition_batches), 1)
        self.assertEqual(genome_rows[0]["batch_id"], inspected.artifact_paths.acquisition_batches[0].batch_id)
        self.assertEqual({row["method"] for row in run_parameter_rows}, {"pure", "threshold"})
        self.assertEqual({row["repeat_residue"] for row in run_parameter_rows}, {"Q"})
        self.assertEqual(
            len(taxonomy_rows),
            _unique_tsv_row_count(
                [batch_path / "taxonomy.tsv" for batch_path in batch_paths],
                ["taxon_id"],
            ),
        )
        self.assertEqual(
            len(genome_rows),
            _unique_tsv_row_count(
                [batch_path / "genomes.tsv" for batch_path in batch_paths],
                ["genome_id"],
            ),
        )
        self.assertEqual(
            len(sequence_rows),
            _unique_tsv_row_count(
                [batch_path / "sequences.tsv" for batch_path in batch_paths],
                ["sequence_id"],
            ),
        )
        self.assertEqual(
            len(protein_rows),
            _unique_tsv_row_count(
                [batch_path / "proteins.tsv" for batch_path in batch_paths],
                ["protein_id"],
            ),
        )
        self.assertEqual(
            len(run_parameter_rows),
            _unique_tsv_row_count(
                [publish_root / "calls" / "run_params.tsv"],
                ["method", "repeat_residue", "param_name"],
            ),
        )
        self.assertEqual(
            len(repeat_call_rows),
            _tsv_row_count(publish_root / "calls" / "repeat_calls.tsv"),
        )
        self.assertEqual(
            len(accession_status_rows),
            _unique_tsv_row_count(
                [publish_root / "status" / "accession_status.tsv"],
                ["assembly_accession"],
            ),
        )
        self.assertEqual(
            len(accession_call_count_rows),
            _unique_tsv_row_count(
                [publish_root / "status" / "accession_call_counts.tsv"],
                ["assembly_accession", "method", "repeat_residue"],
            ),
        )
        self.assertEqual(
            len(download_manifest_rows),
            _sum_tsv_row_counts([batch_path / "download_manifest.tsv" for batch_path in batch_paths]),
        )
        self.assertEqual(
            len(normalization_warning_rows),
            _sum_tsv_row_counts([batch_path / "normalization_warnings.tsv" for batch_path in batch_paths]),
        )
        self.assertTrue(repeat_linked_sequence_ids.issubset({str(row["sequence_id"]) for row in sequence_rows}))
        self.assertTrue(repeat_linked_protein_ids.issubset({str(row["protein_id"]) for row in protein_rows}))

    def test_inspect_published_run_discovers_finalized_codon_usage_artifacts(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_multibatch_publish_root(Path(tempdir))
            add_finalized_codon_usage_artifact(
                publish_root,
                method="pure",
                repeat_residue="Q",
                batch_id="batch_0001",
                rows=[
                    {
                        "call_id": "call_1",
                        "sequence_id": "seq_1",
                        "protein_id": "prot_1",
                        "amino_acid": "Q",
                        "codon": "CAG",
                        "codon_count": 11,
                        "codon_fraction": "1.0",
                    }
                ],
            )
            add_finalized_codon_usage_artifact(
                publish_root,
                method="threshold",
                repeat_residue="Q",
                batch_id="batch_0002",
                rows=[
                    {
                        "call_id": "call_2",
                        "sequence_id": "seq_3",
                        "protein_id": "prot_3",
                        "amino_acid": "Q",
                        "codon": "CAA",
                        "codon_count": 4,
                        "codon_fraction": "0.4",
                    },
                    {
                        "call_id": "call_2",
                        "sequence_id": "seq_3",
                        "protein_id": "prot_3",
                        "amino_acid": "Q",
                        "codon": "CAG",
                        "codon_count": 6,
                        "codon_fraction": "0.6",
                    },
                ],
            )

            inspected = inspect_published_run(publish_root)

            self.assertEqual(
                [
                    (artifact.method, artifact.repeat_residue, artifact.batch_id)
                    for artifact in inspected.artifact_paths.codon_usage_artifacts
                ],
                [
                    ("pure", "Q", "batch_0001"),
                    ("threshold", "Q", "batch_0002"),
                ],
            )
            self.assertEqual(
                len(list(iter_codon_usage_artifact_rows(inspected.artifact_paths.codon_usage_artifacts))),
                3,
            )

    def test_inspect_published_run_rejects_missing_finalized_codon_usage_file(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "calls" / "finalized" / "pure" / "Q" / "batch_0001").mkdir(parents=True)

            with self.assertRaises(ImportContractError):
                inspect_published_run(publish_root)

    def test_inspect_published_run_rejects_missing_required_file(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "acquisition" / "batches" / "batch_0001" / "genomes.tsv").unlink()

            with self.assertRaises(ImportContractError):
                inspect_published_run(publish_root)

    def test_inspect_published_run_rejects_malformed_manifest(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "metadata" / "run_manifest.json").write_text("{", encoding="utf-8")

            with self.assertRaises(ImportContractError):
                inspect_published_run(publish_root)

    def test_inspect_published_run_rejects_missing_required_columns(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "acquisition" / "batches" / "batch_0001" / "genomes.tsv").write_text(
                "genome_id\tsource\tgenome_name\tassembly_type\ttaxon_id\n"
                "genome_1\tncbi_datasets\tExample genome\thaploid\t9606\n",
                encoding="utf-8",
            )

            with self.assertRaises(ImportContractError):
                inspected = inspect_published_run(publish_root)
                list(
                    _iter_batch_rows(
                        inspected,
                        path_attr="genomes_tsv",
                        iterator=iter_genome_rows,
                        include_batch_id=True,
                    )
                )

    def test_inspect_published_run_rejects_manifest_missing_required_keys(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "metadata" / "run_manifest.json").write_text(
                json.dumps({"run_id": "run-alpha"}, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ImportContractError):
                inspect_published_run(publish_root)

    def test_inspect_published_run_preserves_full_raw_taxonomy(self):
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

            inspected = inspect_published_run(publish_root)
            taxonomy_rows = _merge_rows_by_key(
                list(_iter_batch_rows(inspected, path_attr="taxonomy_tsv", iterator=iter_taxonomy_rows)),
                key_field="taxon_id",
            )

            taxonomy_by_id = {row["taxon_id"]: row for row in taxonomy_rows}
            self.assertEqual(len(taxonomy_by_id), 12)
            self.assertIn(131567, taxonomy_by_id)
            self.assertIn(7742, taxonomy_by_id)
            self.assertIn(314146, taxonomy_by_id)
            self.assertIsNone(taxonomy_by_id[1]["parent_taxon_id"])
            self.assertEqual(taxonomy_by_id[2759]["parent_taxon_id"], 131567)
            self.assertEqual(taxonomy_by_id[40674]["parent_taxon_id"], 7742)
            self.assertEqual(taxonomy_by_id[9443]["parent_taxon_id"], 314146)
            self.assertEqual(taxonomy_by_id[9606]["parent_taxon_id"], 9605)

    def test_inspect_published_run_rejects_non_raw_publish_mode(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            manifest_path = publish_root / "metadata" / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["acquisition_publish_mode"] = "merged"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaises(ImportContractError):
                inspect_published_run(publish_root)

    def test_inspect_published_run_accepts_seed_extend_and_repeat_residue_scoped_params(self):
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

            inspected = inspect_published_run(publish_root)
            run_parameter_rows = list(iter_run_parameter_rows(inspected.artifact_paths.run_params_tsv))
            repeat_call_rows = list(iter_repeat_call_rows(inspected.artifact_paths.repeat_calls_tsv))

            self.assertEqual(run_parameter_rows[0]["method"], "seed_extend")
            self.assertEqual(run_parameter_rows[0]["repeat_residue"], "Q")
            self.assertEqual(repeat_call_rows[0]["method"], "seed_extend")

    def test_inspect_published_run_supports_multi_batch_raw_layout(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_multibatch_publish_root(Path(tempdir))

            inspected = inspect_published_run(publish_root)
            taxonomy_rows = _merge_rows_by_key(
                list(_iter_batch_rows(inspected, path_attr="taxonomy_tsv", iterator=iter_taxonomy_rows)),
                key_field="taxon_id",
            )
            genome_rows = _merge_rows_by_key(
                list(
                    _iter_batch_rows(
                        inspected,
                        path_attr="genomes_tsv",
                        iterator=iter_genome_rows,
                        include_batch_id=True,
                    )
                ),
                key_field="genome_id",
            )
            sequence_rows = _merge_rows_by_key(
                list(
                    _iter_batch_rows(
                        inspected,
                        path_attr="sequences_tsv",
                        iterator=iter_sequence_rows,
                        include_batch_id=True,
                    )
                ),
                key_field="sequence_id",
            )
            protein_rows = _merge_rows_by_key(
                list(
                    _iter_batch_rows(
                        inspected,
                        path_attr="proteins_tsv",
                        iterator=iter_protein_rows,
                        include_batch_id=True,
                    )
                ),
                key_field="protein_id",
            )
            repeat_call_rows = list(iter_repeat_call_rows(inspected.artifact_paths.repeat_calls_tsv))
            download_manifest_rows = list(
                _iter_batch_rows(
                    inspected,
                    path_attr="download_manifest_tsv",
                    iterator=iter_download_manifest_rows,
                    include_batch_id=True,
                )
            )
            normalization_warning_rows = list(
                _iter_batch_rows(
                    inspected,
                    path_attr="normalization_warnings_tsv",
                    iterator=iter_normalization_warning_rows,
                    include_batch_id=True,
                )
            )
            accession_status_rows = list(iter_accession_status_rows(inspected.artifact_paths.accession_status_tsv))
            accession_call_count_rows = list(
                iter_accession_call_count_rows(inspected.artifact_paths.accession_call_counts_tsv)
            )
            repeat_linked_genome_ids = tuple(sorted({str(row["genome_id"]) for row in repeat_call_rows}))
            repeat_linked_sequence_ids = tuple(sorted({str(row["sequence_id"]) for row in repeat_call_rows}))
            repeat_linked_protein_ids = tuple(sorted({str(row["protein_id"]) for row in repeat_call_rows}))

            self.assertEqual(
                [batch.batch_id for batch in inspected.artifact_paths.acquisition_batches],
                ["batch_0001", "batch_0002"],
            )
            self.assertEqual(len(taxonomy_rows), 3)
            self.assertEqual(len(genome_rows), 2)
            self.assertEqual(len(sequence_rows), 3)
            self.assertEqual(len(protein_rows), 2)
            self.assertEqual(len(repeat_call_rows), 2)
            self.assertEqual(len(download_manifest_rows), 2)
            self.assertEqual(len(normalization_warning_rows), 1)
            self.assertEqual(len(accession_status_rows), 2)
            self.assertEqual(len(accession_call_count_rows), 2)
            self.assertEqual(repeat_linked_genome_ids, ("genome_1", "genome_2"))
            self.assertEqual(repeat_linked_sequence_ids, ("seq_1", "seq_3"))
            self.assertEqual(repeat_linked_protein_ids, ("prot_1", "prot_3"))
            self.assertEqual(
                Counter(row["batch_id"] for row in genome_rows),
                Counter({"batch_0001": 1, "batch_0002": 1}),
            )
            self.assertEqual(
                Counter(row["batch_id"] for row in sequence_rows),
                Counter({"batch_0001": 2, "batch_0002": 1}),
            )
            self.assertEqual(
                Counter(row["batch_id"] for row in protein_rows),
                Counter({"batch_0001": 1, "batch_0002": 1}),
            )
            self.assertEqual(inspected.artifact_paths.acquisition_batches[0].batch_id, "batch_0001")
            self.assertEqual(inspected.artifact_paths.acquisition_batches[1].batch_id, "batch_0002")

    def test_load_published_run_is_retired_to_avoid_materializing_large_runs(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))

            with self.assertRaisesRegex(ImportContractError, "retired"):
                load_published_run(publish_root)

    def test_inspect_published_run_exposes_large_real_raw_run_without_db_import(self):
        publish_root = _require_large_real_run_validation(self)

        inspected = inspect_published_run(publish_root)
        batch_paths = list(sorted((publish_root / "acquisition" / "batches").glob("*/")))
        first_batch = inspected.artifact_paths.acquisition_batches[0]
        first_genome = next(iter(iter_genome_rows(first_batch.genomes_tsv, batch_id=first_batch.batch_id)))
        first_run_parameter = next(iter(iter_run_parameter_rows(inspected.artifact_paths.run_params_tsv)))
        first_repeat_call = next(iter(iter_repeat_call_rows(inspected.artifact_paths.repeat_calls_tsv)))
        first_accession_status = next(iter(iter_accession_status_rows(inspected.artifact_paths.accession_status_tsv)))
        first_accession_call_count = next(
            iter(iter_accession_call_count_rows(inspected.artifact_paths.accession_call_counts_tsv))
        )

        self.assertEqual(inspected.pipeline_run["run_id"], LARGE_REAL_RUN_ID)
        self.assertEqual(inspected.manifest["acquisition_publish_mode"], "raw")
        self.assertEqual(len(inspected.artifact_paths.acquisition_batches), len(batch_paths))
        self.assertEqual(first_genome["batch_id"], first_batch.batch_id)
        self.assertIn(first_run_parameter["method"], {"pure", "threshold", "seed_extend"})
        self.assertIn(first_repeat_call["method"], {"pure", "threshold", "seed_extend"})
        self.assertEqual(first_accession_status["terminal_status"], "completed")
        self.assertIn(first_accession_call_count["method"], {"pure", "threshold", "seed_extend"})

    def test_large_real_raw_run_contract_counts_align_without_db_import(self):
        publish_root = _require_large_real_run_validation(self)

        manifest = json.loads((publish_root / "metadata" / "run_manifest.json").read_text(encoding="utf-8"))
        batch_dirs = sorted(path for path in (publish_root / "acquisition" / "batches").iterdir() if path.is_dir())
        run_params_path = publish_root / "calls" / "run_params.tsv"
        repeat_calls_path = publish_root / "calls" / "repeat_calls.tsv"
        accession_status_path = publish_root / "status" / "accession_status.tsv"
        accession_call_counts_path = publish_root / "status" / "accession_call_counts.tsv"
        run_param_stats = _stream_tsv_stats(
            run_params_path,
            value_fields=["method", "repeat_residue"],
        )
        repeat_call_stats = _stream_tsv_stats(
            repeat_calls_path,
            value_fields=["method", "repeat_residue"],
        )
        accession_status_stats = _stream_tsv_stats(
            accession_status_path,
            distinct_fields=["batch_id"],
            sum_int_fields=["n_repeat_calls"],
        )
        accession_call_count_stats = _stream_tsv_stats(
            accession_call_counts_path,
            value_fields=["method", "repeat_residue"],
            sum_int_fields=["n_repeat_calls"],
        )

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

        self.assertEqual(run_param_stats["value_sets"]["method"], {"pure", "threshold", "seed_extend"})
        self.assertEqual(run_param_stats["value_sets"]["repeat_residue"], {"Q"})
        self.assertEqual(repeat_call_stats["value_sets"]["method"], {"pure", "threshold", "seed_extend"})
        self.assertEqual(repeat_call_stats["value_sets"]["repeat_residue"], {"Q"})
        self.assertEqual(
            accession_call_count_stats["value_sets"]["method"],
            {"pure", "threshold", "seed_extend"},
        )
        self.assertEqual(accession_call_count_stats["value_sets"]["repeat_residue"], {"Q"})

        self.assertEqual(
            len(batch_dirs),
            accession_status_stats["distinct_counts"]["batch_id"],
        )
        self.assertEqual(
            repeat_call_stats["row_count"],
            accession_status_stats["int_sums"]["n_repeat_calls"],
        )
        self.assertEqual(
            repeat_call_stats["row_count"],
            accession_call_count_stats["int_sums"]["n_repeat_calls"],
        )
