import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from apps.imports.services import ImportContractError, load_published_run

from .support import build_minimal_publish_root

class PublishedRunImportServiceTests(SimpleTestCase):
    def test_load_published_run_parses_real_smoke_run(self):
        publish_root = Path(__file__).resolve().parents[1] / "runs" / "latest" / "publish"
        if not publish_root.exists():
            self.skipTest("requires runs/latest/publish")

        payload = load_published_run(publish_root)

        self.assertEqual(payload.pipeline_run["run_id"], "phase4_pipeline_2026-04-06_12-03-46Z")
        self.assertGreater(len(payload.taxonomy_rows), 0)
        self.assertGreater(len(payload.genome_rows), 0)
        self.assertGreater(len(payload.sequence_rows), 0)
        self.assertGreater(len(payload.protein_rows), 0)
        self.assertGreater(len(payload.repeat_call_rows), 0)

    def test_load_published_run_rejects_missing_required_file(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "acquisition" / "genomes.tsv").unlink()

            with self.assertRaises(ImportContractError):
                load_published_run(publish_root)

    def test_load_published_run_rejects_malformed_manifest(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "manifest" / "run_manifest.json").write_text("{", encoding="utf-8")

            with self.assertRaises(ImportContractError):
                load_published_run(publish_root)

    def test_load_published_run_rejects_missing_required_columns(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "acquisition" / "genomes.tsv").write_text(
                "genome_id\tsource\tgenome_name\tassembly_type\ttaxon_id\n"
                "genome_1\tncbi_datasets\tExample genome\thaploid\t9606\n",
                encoding="utf-8",
            )

            with self.assertRaises(ImportContractError):
                load_published_run(publish_root)

    def test_load_published_run_rejects_manifest_missing_required_keys(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "manifest" / "run_manifest.json").write_text(
                json.dumps({"run_id": "run-alpha"}, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ImportContractError):
                load_published_run(publish_root)

    def test_load_published_run_compacts_taxonomy_to_principal_ranks(self):
        with TemporaryDirectory() as tempdir:
            publish_root = build_minimal_publish_root(Path(tempdir))
            (publish_root / "acquisition" / "taxonomy.tsv").write_text(
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
            self.assertEqual(
                list(taxonomy_by_id.keys()),
                [1, 2759, 33208, 7711, 40674, 9443, 9604, 9605, 9606],
            )
            self.assertNotIn(131567, taxonomy_by_id)
            self.assertNotIn(7742, taxonomy_by_id)
            self.assertNotIn(314146, taxonomy_by_id)
            self.assertIsNone(taxonomy_by_id[1]["parent_taxon_id"])
            self.assertEqual(taxonomy_by_id[2759]["parent_taxon_id"], 1)
            self.assertEqual(taxonomy_by_id[40674]["parent_taxon_id"], 7711)
            self.assertEqual(taxonomy_by_id[9443]["parent_taxon_id"], 40674)
            self.assertEqual(taxonomy_by_id[9606]["parent_taxon_id"], 9605)
