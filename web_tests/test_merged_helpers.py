from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.browser.merged import (
    _identity_merged_protein_groups_from_repeat_calls,
    _identity_merged_residue_groups_from_repeat_calls,
    _protein_identity_key,
    _protein_residue_identity_key,
    _representative_repeat_call,
    merged_protein_groups,
    merged_repeat_call_groups,
)
from apps.browser.models import Genome, PipelineRun, Protein, RepeatCall, Sequence

from .support import ensure_test_taxonomy


class MergedHelperTests(TestCase):
    def setUp(self):
        self.taxa = ensure_test_taxonomy()
        self.human = self.taxa["human"]
        self._source_counter = 0

    def _create_repeat_call_source(
        self,
        *,
        run_id,
        accession,
        protein_id,
        residue="Q",
        protein_name="SharedProtein",
        protein_length=300,
        gene_symbol="GENE1",
        start=10,
        length=11,
        purity=1.0,
        aa_sequence=None,
        imported_at=None,
    ):
        self._source_counter += 1
        suffix = str(self._source_counter)

        pipeline_run = PipelineRun.objects.create(
            run_id=run_id,
            status="success",
            profile="docker",
            acquisition_publish_mode="raw",
            git_revision="abc123",
            manifest_path=f"/tmp/{run_id}/metadata/run_manifest.json",
            publish_root=f"/tmp/{run_id}/publish",
            manifest_payload={"run_id": run_id, "acquisition_publish_mode": "raw"},
        )
        if imported_at is not None:
            PipelineRun.objects.filter(pk=pipeline_run.pk).update(imported_at=imported_at)
            pipeline_run.imported_at = imported_at

        genome = Genome.objects.create(
            pipeline_run=pipeline_run,
            genome_id=f"genome_{suffix}",
            source="ncbi_datasets",
            accession=accession,
            genome_name=f"Genome {suffix}",
            assembly_type="haploid",
            taxon=self.human,
            assembly_level="Chromosome",
            species_name=self.human.taxon_name,
            analyzed_protein_count=20,
        )
        sequence = Sequence.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            taxon=self.human,
            sequence_id=f"seq_{suffix}",
            sequence_name=f"NM_{suffix}",
            sequence_length=900,
            gene_symbol=gene_symbol or "",
        )
        protein = Protein.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            sequence=sequence,
            taxon=self.human,
            protein_id=protein_id,
            protein_name=protein_name,
            protein_length=protein_length,
            accession=accession,
            gene_symbol=gene_symbol or "",
        )

        if aa_sequence is None:
            aa_sequence = (residue or "A") * length

        repeat_count = length if residue else 0
        non_repeat_count = max(length - repeat_count, 0)
        return RepeatCall.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            sequence=sequence,
            protein=protein,
            taxon=self.human,
            call_id=f"call_{suffix}",
            method=RepeatCall.Method.PURE,
            accession=accession,
            gene_symbol=gene_symbol or "",
            protein_name=protein_name,
            protein_length=protein_length,
            start=start,
            end=start + length - 1,
            length=length,
            repeat_residue=residue,
            repeat_count=repeat_count,
            non_repeat_count=non_repeat_count,
            purity=purity,
            aa_sequence=aa_sequence,
        )

    def test_protein_identity_groups_collapse_on_accession_and_protein_id(self):
        alpha = self._create_repeat_call_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            protein_name="SharedProteinAlpha",
            protein_length=300,
            start=10,
        )
        beta = self._create_repeat_call_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            protein_name="SharedProteinBeta",
            protein_length=301,
            start=14,
            purity=0.875,
            aa_sequence="Q" * 10 + "A",
        )

        protein_groups = _identity_merged_protein_groups_from_repeat_calls([alpha, beta])

        self.assertEqual(len(protein_groups), 1)
        self.assertEqual(_protein_identity_key(alpha), ("GCF_SHARED", "prot_shared", RepeatCall.Method.PURE))
        self.assertEqual(_protein_identity_key(beta), ("GCF_SHARED", "prot_shared", RepeatCall.Method.PURE))
        self.assertEqual(protein_groups[0]["accession"], "GCF_SHARED")
        self.assertEqual(protein_groups[0]["protein_id"], "prot_shared")
        self.assertEqual(protein_groups[0]["method"], RepeatCall.Method.PURE)
        self.assertEqual(protein_groups[0]["source_runs_count"], 2)
        self.assertEqual(protein_groups[0]["source_proteins_count"], 2)
        self.assertEqual(protein_groups[0]["source_repeat_calls_count"], 2)
        self.assertEqual(protein_groups[0]["residue_groups_count"], 1)

    def test_residue_identity_groups_split_same_protein_by_residue(self):
        q_call = self._create_repeat_call_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            residue="Q",
        )
        n_call = self._create_repeat_call_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            residue="N",
        )

        protein_groups = _identity_merged_protein_groups_from_repeat_calls([q_call, n_call])
        residue_groups = _identity_merged_residue_groups_from_repeat_calls([q_call, n_call])

        self.assertEqual(len(protein_groups), 1)
        self.assertEqual(len(residue_groups), 2)
        self.assertEqual(
            sorted(group["repeat_residue"] for group in residue_groups),
            ["N", "Q"],
        )
        self.assertEqual(
            _protein_residue_identity_key(q_call),
            ("GCF_SHARED", "prot_shared", RepeatCall.Method.PURE, "Q"),
        )
        self.assertEqual(
            _protein_residue_identity_key(n_call),
            ("GCF_SHARED", "prot_shared", RepeatCall.Method.PURE, "N"),
        )

    def test_identity_groups_split_same_protein_by_method(self):
        pure_call = self._create_repeat_call_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            residue="Q",
        )
        threshold_call = self._create_repeat_call_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            residue="Q",
        )
        threshold_call.method = RepeatCall.Method.THRESHOLD

        protein_groups = _identity_merged_protein_groups_from_repeat_calls([pure_call, threshold_call])
        residue_groups = _identity_merged_residue_groups_from_repeat_calls([pure_call, threshold_call])

        self.assertEqual(len(protein_groups), 2)
        self.assertEqual(len(residue_groups), 2)
        self.assertEqual(
            sorted((group["protein_id"], group["method"]) for group in protein_groups),
            [
                ("prot_shared", RepeatCall.Method.PURE),
                ("prot_shared", RepeatCall.Method.THRESHOLD),
            ],
        )
        self.assertEqual(
            sorted((group["protein_id"], group["method"], group["repeat_residue"]) for group in residue_groups),
            [
                ("prot_shared", RepeatCall.Method.PURE, "Q"),
                ("prot_shared", RepeatCall.Method.THRESHOLD, "Q"),
            ],
        )

    def test_identity_helpers_exclude_rows_without_trustworthy_keys(self):
        valid_call = self._create_repeat_call_source(
            run_id="run-valid",
            accession="GCF_VALID",
            protein_id="prot_valid",
            residue="Q",
        )
        missing_accession = self._create_repeat_call_source(
            run_id="run-no-accession",
            accession="",
            protein_id="prot_no_accession",
            residue="Q",
        )
        missing_protein = self._create_repeat_call_source(
            run_id="run-no-protein",
            accession="GCF_VALID",
            protein_id="",
            residue="Q",
        )
        missing_residue = self._create_repeat_call_source(
            run_id="run-no-residue",
            accession="GCF_VALID",
            protein_id="prot_no_residue",
            residue="",
        )

        protein_groups = _identity_merged_protein_groups_from_repeat_calls(
            [valid_call, missing_accession, missing_protein, missing_residue]
        )
        residue_groups = _identity_merged_residue_groups_from_repeat_calls(
            [valid_call, missing_accession, missing_protein, missing_residue]
        )

        self.assertIsNone(_protein_identity_key(missing_accession))
        self.assertIsNone(_protein_identity_key(missing_protein))
        self.assertIsNone(_protein_residue_identity_key(missing_residue))
        self.assertEqual(
            sorted((group["accession"], group["protein_id"], group["method"]) for group in protein_groups),
            [
                ("GCF_VALID", "prot_no_residue", RepeatCall.Method.PURE),
                ("GCF_VALID", "prot_valid", RepeatCall.Method.PURE),
            ],
        )
        self.assertEqual(
            [
                (group["accession"], group["protein_id"], group["method"], group["repeat_residue"])
                for group in residue_groups
            ],
            [("GCF_VALID", "prot_valid", RepeatCall.Method.PURE, "Q")],
        )

    def test_representative_row_prefers_more_complete_row_before_newer_run(self):
        now = timezone.now()
        older_complete = self._create_repeat_call_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            protein_id="prot_ranked",
            protein_name="NamedProtein",
            protein_length=300,
            gene_symbol="GENE1",
            aa_sequence="Q" * 11,
            imported_at=now - timedelta(days=1),
        )
        newer_incomplete = self._create_repeat_call_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            protein_id="prot_ranked",
            protein_name="",
            protein_length=0,
            gene_symbol="",
            aa_sequence="",
            imported_at=now,
        )

        representative = _representative_repeat_call([older_complete, newer_incomplete])

        self.assertEqual(representative.pk, older_complete.pk)

    def test_representative_row_uses_newer_run_as_final_tiebreaker(self):
        now = timezone.now()
        older = self._create_repeat_call_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            protein_id="prot_ranked",
            imported_at=now - timedelta(days=2),
        )
        newer = self._create_repeat_call_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            protein_id="prot_ranked",
            imported_at=now,
        )

        representative = _representative_repeat_call([older, newer])
        protein_group = _identity_merged_protein_groups_from_repeat_calls([older, newer])[0]

        self.assertEqual(representative.pk, newer.pk)
        self.assertEqual(protein_group["representative_repeat_call"].pk, newer.pk)

    def test_merged_group_helpers_do_not_issue_n_plus_one_queries(self):
        self._create_repeat_call_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            residue="Q",
            protein_length=300,
        )
        self._create_repeat_call_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            residue="N",
            protein_length=301,
        )

        with self.assertNumQueries(1):
            protein_groups = merged_protein_groups()
        with self.assertNumQueries(1):
            residue_groups = merged_repeat_call_groups()

        self.assertEqual(len(protein_groups), 1)
        self.assertEqual(len(residue_groups), 2)

    def test_filter_inclusion_operates_on_matching_evidence_not_identity_keys(self):
        self._create_repeat_call_source(
            run_id="run-alpha",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            residue="Q",
            purity=1.0,
        )
        self._create_repeat_call_source(
            run_id="run-beta",
            accession="GCF_SHARED",
            protein_id="prot_shared",
            residue="Q",
            purity=0.6,
        )

        protein_groups = merged_protein_groups(purity_min="0.9")
        residue_groups = merged_repeat_call_groups(purity_min="0.9")

        self.assertEqual(len(protein_groups), 1)
        self.assertEqual(protein_groups[0]["protein_id"], "prot_shared")
        self.assertEqual(protein_groups[0]["source_repeat_calls_count"], 1)
        self.assertEqual(len(residue_groups), 1)
        self.assertEqual(residue_groups[0]["repeat_residue"], "Q")
        self.assertEqual(residue_groups[0]["source_count"], 1)
