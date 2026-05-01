import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from apps.imports.services.published_run import (
    ImportContractError,
    inspect_published_run,
    iter_accession_call_count_rows,
    iter_accession_status_rows,
    iter_matched_protein_rows,
    iter_matched_sequence_rows,
    iter_repeat_context_rows,
    iter_repeat_call_rows,
    iter_codon_usage_rows,
    iter_run_level_genome_rows,
    iter_run_parameter_rows,
)

from .support import (
    build_minimal_v2_publish_root,
    build_no_call_v2_publish_root,
)


class PublishedRunImportServiceTests(SimpleTestCase):
    def test_inspect_published_run_accepts_v2_flat_contract(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))

            inspected = inspect_published_run(publish_root)

            self.assertEqual(inspected.pipeline_run["run_id"], "run-alpha-v2")
            self.assertEqual(inspected.manifest["publish_contract_version"], 2)
            self.assertEqual(inspected.artifact_paths.publish_root, publish_root.resolve())
            self.assertEqual(
                inspected.artifact_paths.repeat_calls_tsv,
                publish_root.resolve() / "calls" / "repeat_calls.tsv",
            )
            self.assertEqual(
                inspected.artifact_paths.matched_sequences_tsv,
                publish_root.resolve() / "tables" / "matched_sequences.tsv",
            )
            self.assertEqual(
                inspected.artifact_paths.matched_proteins_tsv,
                publish_root.resolve() / "tables" / "matched_proteins.tsv",
            )
            self.assertEqual(
                inspected.artifact_paths.repeat_call_codon_usage_tsv,
                publish_root.resolve() / "tables" / "repeat_call_codon_usage.tsv",
            )
            self.assertFalse(hasattr(inspected.artifact_paths, "acquisition_batches"))

    def test_inspect_published_run_accepts_v2_merged_publish_mode(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(
                Path(tempdir),
                acquisition_publish_mode="merged",
                include_merged_side_artifacts=True,
            )

            inspected = inspect_published_run(publish_root)

            self.assertEqual(inspected.manifest["acquisition_publish_mode"], "merged")
            self.assertEqual(inspected.manifest["publish_contract_version"], 2)
            self.assertTrue((publish_root / "reports" / "summary.html").is_file())
            self.assertTrue((publish_root / "databases" / "homorepeat.sqlite").is_file())

    def test_inspect_published_run_accepts_v2_no_call_fixture(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_no_call_v2_publish_root(Path(tempdir))

            inspected = inspect_published_run(publish_root)

            self.assertEqual(inspected.manifest["publish_contract_version"], 2)
            self.assertEqual(list(iter_repeat_call_rows(inspected.artifact_paths.repeat_calls_tsv)), [])
            self.assertEqual(list(iter_matched_sequence_rows(inspected.artifact_paths.matched_sequences_tsv)), [])
            self.assertEqual(list(iter_matched_protein_rows(inspected.artifact_paths.matched_proteins_tsv)), [])
            self.assertEqual(list(iter_codon_usage_rows(inspected.artifact_paths.repeat_call_codon_usage_tsv)), [])
            self.assertEqual(list(iter_repeat_context_rows(inspected.artifact_paths.repeat_context_tsv)), [])
            self.assertEqual(
                list(iter_accession_status_rows(inspected.artifact_paths.accession_status_tsv))[0][
                    "terminal_status"
                ],
                "completed_no_calls",
            )
            self.assertEqual(
                list(iter_accession_call_count_rows(inspected.artifact_paths.accession_call_counts_tsv))[0][
                    "n_repeat_calls"
                ],
                0,
            )

    def test_inspect_published_run_rejects_v2_missing_required_file(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            (publish_root / "tables" / "repeat_call_codon_usage.tsv").unlink()

            with self.assertRaisesRegex(ImportContractError, "repeat_call_codon_usage.tsv"):
                inspect_published_run(publish_root)

    def test_inspect_published_run_rejects_v2_manifest_missing_contract_version(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            manifest_path = publish_root / "metadata" / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("publish_contract_version")
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ImportContractError, "publish_contract_version"):
                inspect_published_run(publish_root)

    def test_inspect_published_run_rejects_unsupported_v2_contract_version(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            manifest_path = publish_root / "metadata" / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["publish_contract_version"] = 3
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ImportContractError, "publish_contract_version"):
                inspect_published_run(publish_root)

    def test_v2_matched_sequence_and_protein_iterators_include_body_columns(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            inspected = inspect_published_run(publish_root)

            sequence_rows = list(iter_matched_sequence_rows(inspected.artifact_paths.matched_sequences_tsv))
            protein_rows = list(iter_matched_protein_rows(inspected.artifact_paths.matched_proteins_tsv))

            self.assertEqual(sequence_rows[0]["batch_id"], "batch_0001")
            self.assertEqual(sequence_rows[0]["sequence_id"], "seq_1")
            self.assertEqual(sequence_rows[0]["nucleotide_sequence"], "CAG" * 30)
            self.assertEqual(protein_rows[0]["batch_id"], "batch_0001")
            self.assertEqual(protein_rows[0]["protein_id"], "prot_1")
            self.assertEqual(protein_rows[0]["amino_acid_sequence"], "Q" * 30)

    def test_v2_repeat_context_iterator_parses_flanks_and_window_sizes(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            inspected = inspect_published_run(publish_root)

            context_rows = list(iter_repeat_context_rows(inspected.artifact_paths.repeat_context_tsv))

            self.assertEqual(
                context_rows,
                [
                    {
                        "call_id": "call_1",
                        "protein_id": "prot_1",
                        "sequence_id": "seq_1",
                        "aa_left_flank": "M",
                        "aa_right_flank": "A",
                        "nt_left_flank": "ATG",
                        "nt_right_flank": "GCT",
                        "aa_context_window_size": 12,
                        "nt_context_window_size": 36,
                    }
                ],
            )

    def test_v2_matched_sequence_iterator_requires_nucleotide_sequence(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            path = publish_root / "tables" / "matched_sequences.tsv"
            path.write_text(
                "batch_id\tsequence_id\tgenome_id\tsequence_name\tsequence_length\n"
                "batch_0001\tseq_1\tgenome_1\tNM_000001.1\t90\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ImportContractError, "nucleotide_sequence"):
                list(iter_matched_sequence_rows(path))

    def test_codon_usage_iterator_requires_positive_dna_triplets(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            path = publish_root / "tables" / "repeat_call_codon_usage.tsv"

            path.write_text(
                "call_id\tmethod\trepeat_residue\tsequence_id\tprotein_id\tamino_acid\tcodon\tcodon_count\tcodon_fraction\n"
                "call_1\tpure\tQ\tseq_1\tprot_1\tQ\tcag\t1\t1.0\n",
                encoding="utf-8",
            )
            self.assertEqual(list(iter_codon_usage_rows(path))[0]["codon"], "CAG")

            path.write_text(
                "call_id\tmethod\trepeat_residue\tsequence_id\tprotein_id\tamino_acid\tcodon\tcodon_count\tcodon_fraction\n"
                "call_1\tpure\tQ\tseq_1\tprot_1\tQ\tCAG\t0\t1.0\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ImportContractError, "codon_count"):
                list(iter_codon_usage_rows(path))

            path.write_text(
                "call_id\tmethod\trepeat_residue\tsequence_id\tprotein_id\tamino_acid\tcodon\tcodon_count\tcodon_fraction\n"
                "call_1\tpure\tQ\tseq_1\tprot_1\tQ\tNAG\t1\t1.0\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ImportContractError, "DNA codon"):
                list(iter_codon_usage_rows(path))

    def test_inspect_published_run_rejects_malformed_manifest(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            (publish_root / "metadata" / "run_manifest.json").write_text("{", encoding="utf-8")

            with self.assertRaises(ImportContractError):
                inspect_published_run(publish_root)

    def test_inspect_published_run_rejects_missing_required_columns(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            (publish_root / "tables" / "genomes.tsv").write_text(
                "genome_id\tsource\tgenome_name\tassembly_type\ttaxon_id\n"
                "genome_1\tncbi_datasets\tExample genome\thaploid\t9606\n",
                encoding="utf-8",
            )

            with self.assertRaises(ImportContractError):
                inspected = inspect_published_run(publish_root)
                list(iter_run_level_genome_rows(inspected.artifact_paths.genomes_tsv))

    def test_inspect_published_run_rejects_manifest_missing_required_keys(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
            (publish_root / "metadata" / "run_manifest.json").write_text(
                json.dumps({"run_id": "run-alpha"}, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ImportContractError):
                inspect_published_run(publish_root)

    def test_inspect_published_run_accepts_v2_non_raw_publish_mode(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir), acquisition_publish_mode="merged")

            inspected = inspect_published_run(publish_root)

            self.assertEqual(inspected.manifest["acquisition_publish_mode"], "merged")

    def test_inspect_published_run_accepts_seed_extend_and_repeat_residue_scoped_params(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_v2_publish_root(Path(tempdir))
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
