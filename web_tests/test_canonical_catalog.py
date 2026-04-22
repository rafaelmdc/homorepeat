from io import StringIO

from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.browser.catalog import sync_canonical_catalog_for_run
from apps.browser.catalog.sync import _import_batch_row_count
from apps.browser.models import (
    AcquisitionBatch,
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalRepeatCallCodonUsage,
    CanonicalSequence,
    Genome,
    PipelineRun,
    Protein,
    RepeatCall,
    RepeatCallCodonUsage,
    RunParameter,
    Sequence,
)
from apps.imports.models import ImportBatch
from web_tests.support import ensure_test_taxonomy


class CanonicalModelTests(TestCase):
    def setUp(self):
        self.taxa = ensure_test_taxonomy()
        self.pipeline_run = PipelineRun.objects.create(run_id="run-alpha", status="success")
        self.import_batch = ImportBatch.objects.create(
            pipeline_run=self.pipeline_run,
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.COMPLETED,
            finished_at=timezone.now(),
            phase="completed",
        )
        self.last_seen_at = timezone.now()
        self.genome = CanonicalGenome.objects.create(
            latest_pipeline_run=self.pipeline_run,
            latest_import_batch=self.import_batch,
            last_seen_at=self.last_seen_at,
            genome_id="genome_1",
            source="ncbi_datasets",
            accession="GCF_000001405.40",
            genome_name="Example genome",
            assembly_type="haploid",
            taxon=self.taxa["human"],
            assembly_level="Chromosome",
            species_name="Homo sapiens",
            analyzed_protein_count=1,
        )
        self.sequence = CanonicalSequence.objects.create(
            latest_pipeline_run=self.pipeline_run,
            latest_import_batch=self.import_batch,
            last_seen_at=self.last_seen_at,
            genome=self.genome,
            taxon=self.taxa["human"],
            sequence_id="seq_1",
            sequence_name="NM_000001.1",
            sequence_length=900,
            gene_symbol="GENE1",
            assembly_accession=self.genome.accession,
        )
        self.protein = CanonicalProtein.objects.create(
            latest_pipeline_run=self.pipeline_run,
            latest_import_batch=self.import_batch,
            last_seen_at=self.last_seen_at,
            genome=self.genome,
            sequence=self.sequence,
            taxon=self.taxa["human"],
            protein_id="prot_1",
            protein_name="NP_000001.1",
            protein_length=300,
            accession=self.genome.accession,
            gene_symbol="GENE1",
        )

    def test_import_batch_row_count_uses_progress_counts_before_db_row_counts(self):
        self.import_batch.progress_payload = {
            "counts": {
                "repeat_call_codon_usages": "12",
            },
        }
        self.import_batch.row_counts = {
            "repeat_call_codon_usages": 5,
        }

        self.assertEqual(_import_batch_row_count(self.import_batch, "repeat_call_codon_usages"), 12)

    def test_import_batch_row_count_falls_back_to_saved_row_counts(self):
        self.import_batch.progress_payload = {}
        self.import_batch.row_counts = {
            "repeat_call_codon_usages": 5,
        }

        self.assertEqual(_import_batch_row_count(self.import_batch, "repeat_call_codon_usages"), 5)

    def test_canonical_genome_links_to_latest_import_provenance(self):
        self.assertEqual(self.genome.latest_pipeline_run, self.pipeline_run)
        self.assertEqual(self.genome.latest_import_batch, self.import_batch)

    def test_canonical_genome_accession_must_be_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CanonicalGenome.objects.create(
                    latest_pipeline_run=self.pipeline_run,
                    latest_import_batch=self.import_batch,
                    last_seen_at=self.last_seen_at,
                    genome_id="genome_2",
                    source="ncbi_datasets",
                    accession=self.genome.accession,
                    genome_name="Duplicate",
                    assembly_type="haploid",
                    taxon=self.taxa["human"],
                )

    def test_canonical_sequence_is_unique_within_genome(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CanonicalSequence.objects.create(
                    latest_pipeline_run=self.pipeline_run,
                    latest_import_batch=self.import_batch,
                    last_seen_at=self.last_seen_at,
                    genome=self.genome,
                    taxon=self.taxa["human"],
                    sequence_id=self.sequence.sequence_id,
                    sequence_name="Duplicate sequence",
                    sequence_length=901,
                )

    def test_canonical_protein_is_unique_within_genome(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CanonicalProtein.objects.create(
                    latest_pipeline_run=self.pipeline_run,
                    latest_import_batch=self.import_batch,
                    last_seen_at=self.last_seen_at,
                    genome=self.genome,
                    sequence=self.sequence,
                    taxon=self.taxa["human"],
                    protein_id=self.protein.protein_id,
                    protein_name="Duplicate protein",
                    protein_length=301,
                )

    def test_canonical_repeat_call_is_unique_within_method_scoped_location(self):
        CanonicalRepeatCall.objects.create(
            latest_pipeline_run=self.pipeline_run,
            latest_import_batch=self.import_batch,
            last_seen_at=self.last_seen_at,
            genome=self.genome,
            sequence=self.sequence,
            protein=self.protein,
            taxon=self.taxa["human"],
            method=RunParameter.Method.PURE,
            accession=self.genome.accession,
            gene_symbol="GENE1",
            protein_name=self.protein.protein_name,
            protein_length=self.protein.protein_length,
            start=10,
            end=20,
            length=11,
            repeat_residue="Q",
            repeat_count=11,
            non_repeat_count=0,
            purity=1.0,
            aa_sequence="QQQQQQQQQQQ",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CanonicalRepeatCall.objects.create(
                    latest_pipeline_run=self.pipeline_run,
                    latest_import_batch=self.import_batch,
                    last_seen_at=self.last_seen_at,
                    genome=self.genome,
                    sequence=self.sequence,
                    protein=self.protein,
                    taxon=self.taxa["human"],
                    method=RunParameter.Method.PURE,
                    accession=self.genome.accession,
                    gene_symbol="GENE1",
                    protein_name=self.protein.protein_name,
                    protein_length=self.protein.protein_length,
                    start=10,
                    end=20,
                    length=11,
                    repeat_residue="Q",
                    repeat_count=11,
                    non_repeat_count=0,
                    purity=1.0,
                    aa_sequence="QQQQQQQQQQQ",
                )

    def test_canonical_repeat_call_codon_usage_is_unique_per_call_amino_acid_and_codon(self):
        repeat_call = CanonicalRepeatCall.objects.create(
            latest_pipeline_run=self.pipeline_run,
            latest_import_batch=self.import_batch,
            last_seen_at=self.last_seen_at,
            genome=self.genome,
            sequence=self.sequence,
            protein=self.protein,
            taxon=self.taxa["human"],
            method=RunParameter.Method.PURE,
            accession=self.genome.accession,
            gene_symbol="GENE1",
            protein_name=self.protein.protein_name,
            protein_length=self.protein.protein_length,
            start=10,
            end=20,
            length=11,
            repeat_residue="Q",
            repeat_count=11,
            non_repeat_count=0,
            purity=1.0,
            aa_sequence="QQQQQQQQQQQ",
        )
        CanonicalRepeatCallCodonUsage.objects.create(
            repeat_call=repeat_call,
            amino_acid="Q",
            codon="CAG",
            codon_count=11,
            codon_fraction=1.0,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CanonicalRepeatCallCodonUsage.objects.create(
                    repeat_call=repeat_call,
                    amino_acid="Q",
                    codon="CAG",
                    codon_count=11,
                    codon_fraction=1.0,
                )


class CatalogSyncTests(TestCase):
    def setUp(self):
        self.taxa = ensure_test_taxonomy()

    def test_sync_creates_canonical_rows_and_provenance_links(self):
        raw = self._create_raw_run(
            run_id="run-alpha",
            accession="GCF_000001405.40",
            genome_name="Genome alpha",
            protein_name="Protein alpha",
            methods=[RunParameter.Method.PURE],
            calls=[
                {
                    "call_id": "call_alpha",
                    "method": RunParameter.Method.PURE,
                    "start": 10,
                    "end": 20,
                    "repeat_residue": "Q",
                }
            ],
        )

        result = sync_canonical_catalog_for_run(
            raw["pipeline_run"],
            import_batch=raw["import_batch"],
        )

        canonical_genome = CanonicalGenome.objects.get(accession="GCF_000001405.40")
        canonical_sequence = CanonicalSequence.objects.get(genome=canonical_genome, sequence_id="seq_1")
        canonical_protein = CanonicalProtein.objects.get(genome=canonical_genome, protein_id="prot_1")
        canonical_repeat_call = CanonicalRepeatCall.objects.get(protein=canonical_protein)

        self.assertEqual(result.genomes, 1)
        self.assertEqual(result.repeat_calls, 1)
        self.assertEqual(canonical_genome.latest_pipeline_run, raw["pipeline_run"])
        self.assertEqual(canonical_genome.latest_import_batch, raw["import_batch"])
        self.assertEqual(canonical_sequence.latest_pipeline_run, raw["pipeline_run"])
        self.assertEqual(canonical_protein.latest_import_batch, raw["import_batch"])
        self.assertEqual(canonical_repeat_call.latest_repeat_call, raw["repeat_calls"][0])
        self.assertEqual(canonical_repeat_call.source_call_id, "call_alpha")
        self.assertEqual(raw["pipeline_run"].canonical_sync_batch, raw["import_batch"])
        self.assertIsNotNone(raw["pipeline_run"].canonical_synced_at)

    def test_sync_copies_repeat_call_codon_usage_rows_into_canonical_catalog(self):
        raw = self._create_raw_run(
            run_id="run-codon-usage",
            accession="GCF_000001405.40",
            genome_name="Genome alpha",
            protein_name="Protein alpha",
            methods=[RunParameter.Method.PURE],
            calls=[
                {
                    "call_id": "call_alpha",
                    "method": RunParameter.Method.PURE,
                    "start": 10,
                    "end": 20,
                    "repeat_residue": "Q",
                }
            ],
        )
        RepeatCallCodonUsage.objects.bulk_create(
            [
                RepeatCallCodonUsage(
                    repeat_call=raw["repeat_calls"][0],
                    amino_acid="Q",
                    codon="CAA",
                    codon_count=1,
                    codon_fraction=1 / 11,
                ),
                RepeatCallCodonUsage(
                    repeat_call=raw["repeat_calls"][0],
                    amino_acid="Q",
                    codon="CAG",
                    codon_count=10,
                    codon_fraction=10 / 11,
                ),
            ]
        )

        sync_canonical_catalog_for_run(raw["pipeline_run"], import_batch=raw["import_batch"])

        self.assertEqual(CanonicalRepeatCallCodonUsage.objects.count(), 2)
        self.assertEqual(
            list(
                CanonicalRepeatCallCodonUsage.objects.order_by("codon").values_list(
                    "repeat_call__source_call_id",
                    "codon",
                    "codon_count",
                )
            ),
            [
                ("call_alpha", "CAA", 1),
                ("call_alpha", "CAG", 10),
            ],
        )

    def test_sync_updates_canonical_rows_in_place_for_same_identity(self):
        first = self._create_raw_run(
            run_id="run-alpha",
            accession="GCF_000001405.40",
            genome_name="Genome alpha",
            protein_name="Protein alpha",
            methods=[RunParameter.Method.PURE],
            calls=[
                {
                    "call_id": "call_alpha",
                    "method": RunParameter.Method.PURE,
                    "start": 10,
                    "end": 20,
                    "repeat_residue": "Q",
                }
            ],
        )
        sync_canonical_catalog_for_run(first["pipeline_run"], import_batch=first["import_batch"])

        canonical_genome = CanonicalGenome.objects.get(accession="GCF_000001405.40")
        canonical_sequence = CanonicalSequence.objects.get(genome=canonical_genome, sequence_id="seq_1")
        canonical_protein = CanonicalProtein.objects.get(genome=canonical_genome, protein_id="prot_1")

        second = self._create_raw_run(
            run_id="run-beta",
            accession="GCF_000001405.40",
            genome_name="Genome beta",
            protein_name="Protein beta",
            sequence_name="NM_beta",
            methods=[RunParameter.Method.PURE],
            calls=[
                {
                    "call_id": "call_beta",
                    "method": RunParameter.Method.PURE,
                    "start": 12,
                    "end": 24,
                    "repeat_residue": "Q",
                }
            ],
        )
        sync_canonical_catalog_for_run(second["pipeline_run"], import_batch=second["import_batch"])

        canonical_genome.refresh_from_db()
        canonical_sequence.refresh_from_db()
        canonical_protein.refresh_from_db()
        canonical_repeat_call = CanonicalRepeatCall.objects.get(protein=canonical_protein)

        self.assertEqual(canonical_genome.pk, CanonicalGenome.objects.get(accession="GCF_000001405.40").pk)
        self.assertEqual(canonical_sequence.pk, CanonicalSequence.objects.get(genome=canonical_genome, sequence_id="seq_1").pk)
        self.assertEqual(canonical_protein.pk, CanonicalProtein.objects.get(genome=canonical_genome, protein_id="prot_1").pk)
        self.assertEqual(canonical_genome.genome_name, "Genome beta")
        self.assertEqual(canonical_sequence.sequence_name, "NM_beta")
        self.assertEqual(canonical_protein.protein_name, "Protein beta")
        self.assertEqual(canonical_genome.latest_pipeline_run, second["pipeline_run"])
        self.assertEqual(canonical_repeat_call.source_call_id, "call_beta")
        self.assertEqual((canonical_repeat_call.start, canonical_repeat_call.end), (12, 24))
        self.assertEqual(second["pipeline_run"].canonical_sync_batch, second["import_batch"])

    def test_sync_replaces_only_touched_method_scope(self):
        first = self._create_raw_run(
            run_id="run-alpha",
            accession="GCF_000001405.40",
            genome_name="Genome alpha",
            protein_name="Protein alpha",
            methods=[RunParameter.Method.PURE, RunParameter.Method.THRESHOLD],
            calls=[
                {
                    "call_id": "call_alpha_pure",
                    "method": RunParameter.Method.PURE,
                    "start": 10,
                    "end": 20,
                    "repeat_residue": "Q",
                },
                {
                    "call_id": "call_alpha_threshold",
                    "method": RunParameter.Method.THRESHOLD,
                    "start": 30,
                    "end": 39,
                    "repeat_residue": "Q",
                },
            ],
        )
        sync_canonical_catalog_for_run(first["pipeline_run"], import_batch=first["import_batch"])

        second = self._create_raw_run(
            run_id="run-beta",
            accession="GCF_000001405.40",
            genome_name="Genome beta",
            protein_name="Protein beta",
            methods=[RunParameter.Method.PURE],
            calls=[
                {
                    "call_id": "call_beta_pure",
                    "method": RunParameter.Method.PURE,
                    "start": 14,
                    "end": 25,
                    "repeat_residue": "Q",
                }
            ],
        )
        sync_canonical_catalog_for_run(second["pipeline_run"], import_batch=second["import_batch"])

        canonical_protein = CanonicalProtein.objects.get(protein_id="prot_1")
        canonical_calls = list(
            CanonicalRepeatCall.objects.filter(protein=canonical_protein).order_by("method", "start")
        )

        self.assertEqual(len(canonical_calls), 2)
        self.assertEqual(
            {(call.method, call.source_call_id) for call in canonical_calls},
            {
                (RunParameter.Method.PURE, "call_beta_pure"),
                (RunParameter.Method.THRESHOLD, "call_alpha_threshold"),
            },
        )
        self.assertEqual(canonical_protein.repeat_call_count, 2)

    def test_sync_clears_method_scope_when_latest_run_has_no_current_calls(self):
        first = self._create_raw_run(
            run_id="run-alpha",
            accession="GCF_000001405.40",
            genome_name="Genome alpha",
            protein_name="Protein alpha",
            methods=[RunParameter.Method.PURE],
            calls=[
                {
                    "call_id": "call_alpha",
                    "method": RunParameter.Method.PURE,
                    "start": 10,
                    "end": 20,
                    "repeat_residue": "Q",
                }
            ],
        )
        sync_canonical_catalog_for_run(first["pipeline_run"], import_batch=first["import_batch"])

        second = self._create_raw_run(
            run_id="run-beta",
            accession="GCF_000001405.40",
            genome_name="Genome beta",
            protein_name="Protein beta",
            methods=[RunParameter.Method.PURE],
            calls=[],
        )
        sync_canonical_catalog_for_run(second["pipeline_run"], import_batch=second["import_batch"])

        canonical_protein = CanonicalProtein.objects.get(protein_id="prot_1")

        self.assertFalse(CanonicalRepeatCall.objects.filter(protein=canonical_protein, method=RunParameter.Method.PURE).exists())
        self.assertEqual(canonical_protein.repeat_call_count, 0)

    def test_sync_preserves_numeric_codon_ratio_value(self):
        raw = self._create_raw_run(
            run_id="run-codon-ratio",
            accession="GCF_000001405.40",
            genome_name="Genome alpha",
            protein_name="Protein alpha",
            methods=[RunParameter.Method.PURE],
            calls=[
                {
                    "call_id": "call_alpha",
                    "method": RunParameter.Method.PURE,
                    "start": 10,
                    "end": 20,
                    "repeat_residue": "Q",
                    "codon_metric_name": "codon_ratio",
                    "codon_metric_value": "1.5",
                    "codon_ratio_value": 1.5,
                }
            ],
        )

        sync_canonical_catalog_for_run(raw["pipeline_run"], import_batch=raw["import_batch"])

        canonical_repeat_call = CanonicalRepeatCall.objects.get()

        self.assertEqual(canonical_repeat_call.codon_metric_name, "codon_ratio")
        self.assertEqual(canonical_repeat_call.codon_metric_value, "1.5")
        self.assertEqual(canonical_repeat_call.codon_ratio_value, 1.5)

    def _create_raw_run(
        self,
        *,
        run_id,
        accession,
        genome_name,
        protein_name,
        methods,
        calls,
        sequence_name="NM_000001.1",
    ):
        pipeline_run = PipelineRun.objects.create(
            run_id=run_id,
            status="success",
            acquisition_publish_mode="raw",
        )
        import_batch = ImportBatch.objects.create(
            pipeline_run=pipeline_run,
            source_path=f"/tmp/{run_id}/publish",
            status=ImportBatch.Status.COMPLETED,
            finished_at=timezone.now(),
            phase="completed",
        )
        batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0001",
        )
        genome = Genome.objects.create(
            pipeline_run=pipeline_run,
            batch=batch,
            genome_id="genome_1",
            source="ncbi_datasets",
            accession=accession,
            genome_name=genome_name,
            assembly_type="haploid",
            taxon=self.taxa["human"],
            assembly_level="Chromosome",
            species_name="Homo sapiens",
            analyzed_protein_count=1,
        )
        sequence = Sequence.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            taxon=self.taxa["human"],
            sequence_id="seq_1",
            sequence_name=sequence_name,
            sequence_length=900,
            nucleotide_sequence="CAG" * 30,
            gene_symbol="GENE1",
            transcript_id="NM_000001.1",
            isoform_id="NP_000001.1",
            assembly_accession=accession,
            source_record_id=f"{run_id}-seq",
            protein_external_id="NP_000001.1",
            translation_table="1",
            gene_group="GENE1",
            linkage_status="gff",
        )
        protein = Protein.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            sequence=sequence,
            taxon=self.taxa["human"],
            protein_id="prot_1",
            protein_name=protein_name,
            protein_length=300,
            accession=accession,
            amino_acid_sequence="Q" * 30,
            gene_symbol="GENE1",
            translation_method="translated",
            translation_status="translated",
            assembly_accession=accession,
            gene_group="GENE1",
            protein_external_id="NP_000001.1",
            repeat_call_count=len(calls),
        )

        for method in methods:
            RunParameter.objects.create(
                pipeline_run=pipeline_run,
                method=method,
                repeat_residue="Q",
                param_name="min_repeat_count",
                param_value="6",
            )

        repeat_calls = []
        for call in calls:
            repeat_calls.append(
                RepeatCall.objects.create(
                    pipeline_run=pipeline_run,
                    genome=genome,
                    sequence=sequence,
                    protein=protein,
                    taxon=self.taxa["human"],
                    call_id=call["call_id"],
                    method=call["method"],
                    accession=accession,
                    gene_symbol="GENE1",
                    protein_name=protein_name,
                    protein_length=300,
                    start=call["start"],
                    end=call["end"],
                    length=(call["end"] - call["start"]) + 1,
                    repeat_residue=call["repeat_residue"],
                    repeat_count=(call["end"] - call["start"]) + 1,
                    non_repeat_count=0,
                    purity=1.0,
                    aa_sequence=call["repeat_residue"] * ((call["end"] - call["start"]) + 1),
                    codon_metric_name=call.get("codon_metric_name", ""),
                    codon_metric_value=call.get("codon_metric_value", ""),
                    codon_ratio_value=call.get("codon_ratio_value"),
                )
            )

        return {
            "pipeline_run": pipeline_run,
            "import_batch": import_batch,
            "batch": batch,
            "genome": genome,
            "sequence": sequence,
            "protein": protein,
            "repeat_calls": repeat_calls,
        }


class CanonicalCatalogBackfillCommandTests(TestCase):
    def setUp(self):
        self.taxa = ensure_test_taxonomy()

    def test_backfill_canonical_catalog_populates_missing_rows(self):
        raw = self._create_backfill_raw_run(run_id="run-backfill")
        raw["pipeline_run"].canonical_sync_batch = None
        raw["pipeline_run"].canonical_synced_at = None
        raw["pipeline_run"].save(update_fields=["canonical_sync_batch", "canonical_synced_at"])
        stdout = StringIO()

        self.assertEqual(CanonicalGenome.objects.count(), 0)
        self.assertEqual(CanonicalSequence.objects.count(), 0)
        self.assertEqual(CanonicalProtein.objects.count(), 0)
        self.assertEqual(CanonicalRepeatCall.objects.count(), 0)

        call_command("backfill_canonical_catalog", run_id="run-backfill", stdout=stdout)

        raw["pipeline_run"].refresh_from_db()
        self.assertEqual(CanonicalGenome.objects.count(), 1)
        self.assertEqual(CanonicalSequence.objects.count(), 1)
        self.assertEqual(CanonicalProtein.objects.count(), 1)
        self.assertEqual(CanonicalRepeatCall.objects.count(), 1)
        self.assertEqual(raw["pipeline_run"].canonical_sync_batch, raw["import_batch"])
        self.assertIsNotNone(raw["pipeline_run"].canonical_synced_at)
        self.assertEqual(RepeatCall.objects.count(), 1)
        self.assertIn("Backfilled run-backfill", stdout.getvalue())
        self.assertIn("updated: 1", stdout.getvalue())
        self.assertIn("skipped: 0", stdout.getvalue())

    def test_backfill_canonical_catalog_skips_currently_synced_run_without_force(self):
        raw = self._create_backfill_raw_run(run_id="run-skip")
        sync_canonical_catalog_for_run(raw["pipeline_run"], import_batch=raw["import_batch"])
        synced_at = raw["pipeline_run"].canonical_synced_at
        stdout = StringIO()

        call_command("backfill_canonical_catalog", run_id="run-skip", stdout=stdout)

        raw["pipeline_run"].refresh_from_db()
        self.assertEqual(raw["pipeline_run"].canonical_synced_at, synced_at)
        self.assertEqual(CanonicalGenome.objects.count(), 1)
        self.assertIn("Skipped run-skip", stdout.getvalue())
        self.assertIn("updated: 0", stdout.getvalue())
        self.assertIn("skipped: 1", stdout.getvalue())

    def test_backfill_canonical_catalog_force_resyncs_rows(self):
        raw = self._create_backfill_raw_run(run_id="run-force")
        sync_canonical_catalog_for_run(raw["pipeline_run"], import_batch=raw["import_batch"])
        repeat_call = raw["repeat_calls"][0]
        repeat_call.method = RunParameter.Method.THRESHOLD
        repeat_call.repeat_residue = "A"
        repeat_call.save(update_fields=["method", "repeat_residue"])
        protein = raw["protein"]
        protein.protein_name = "Protein forced"
        protein.save(update_fields=["protein_name"])
        stdout = StringIO()

        call_command("backfill_canonical_catalog", run_id="run-force", force=True, stdout=stdout)

        canonical_repeat_call = CanonicalRepeatCall.objects.get()
        canonical_protein = CanonicalProtein.objects.get()
        self.assertEqual(canonical_repeat_call.method, RunParameter.Method.THRESHOLD)
        self.assertEqual(canonical_repeat_call.repeat_residue, "A")
        self.assertEqual(canonical_protein.protein_name, "Protein forced")
        self.assertIn("Backfilled run-force", stdout.getvalue())
        self.assertIn("updated: 1", stdout.getvalue())

    def test_backfill_canonical_catalog_errors_for_missing_run(self):
        with self.assertRaises(CommandError):
            call_command("backfill_canonical_catalog", run_id="no-such-run")

    def _create_backfill_raw_run(self, *, run_id):
        pipeline_run = PipelineRun.objects.create(
            run_id=run_id,
            status="success",
            acquisition_publish_mode="raw",
            publish_root=f"/tmp/{run_id}/publish",
        )
        import_batch = ImportBatch.objects.create(
            pipeline_run=pipeline_run,
            source_path=pipeline_run.publish_root,
            status=ImportBatch.Status.COMPLETED,
            finished_at=timezone.now(),
            phase="completed",
            row_counts={
                "genomes": 1,
                "sequences": 1,
                "proteins": 1,
                "repeat_calls": 1,
                "accession_status_rows": 0,
                "accession_call_count_rows": 0,
                "download_manifest_entries": 0,
                "normalization_warnings": 0,
            },
        )
        batch = AcquisitionBatch.objects.create(
            pipeline_run=pipeline_run,
            batch_id="batch_0001",
        )
        genome = Genome.objects.create(
            pipeline_run=pipeline_run,
            batch=batch,
            genome_id="genome_1",
            source="ncbi_datasets",
            accession="GCF_000001405.40",
            genome_name="Genome backfill",
            assembly_type="haploid",
            taxon=self.taxa["human"],
            assembly_level="Chromosome",
            species_name="Homo sapiens",
            analyzed_protein_count=1,
        )
        sequence = Sequence.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            taxon=self.taxa["human"],
            sequence_id="seq_1",
            sequence_name="NM_000001.1",
            sequence_length=900,
            nucleotide_sequence="CAG" * 30,
            gene_symbol="GENE1",
            assembly_accession=genome.accession,
        )
        protein = Protein.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            sequence=sequence,
            taxon=self.taxa["human"],
            protein_id="prot_1",
            protein_name="Protein backfill",
            protein_length=300,
            accession=genome.accession,
            amino_acid_sequence="Q" * 30,
            gene_symbol="GENE1",
            repeat_call_count=1,
        )
        RunParameter.objects.create(
            pipeline_run=pipeline_run,
            method=RunParameter.Method.PURE,
            repeat_residue="Q",
            param_name="min_repeat_count",
            param_value="6",
        )
        repeat_call = RepeatCall.objects.create(
            pipeline_run=pipeline_run,
            genome=genome,
            sequence=sequence,
            protein=protein,
            taxon=self.taxa["human"],
            call_id=f"{run_id}-call",
            method=RunParameter.Method.PURE,
            accession=genome.accession,
            gene_symbol="GENE1",
            protein_name=protein.protein_name,
            protein_length=protein.protein_length,
            start=10,
            end=20,
            length=11,
            repeat_residue="Q",
            repeat_count=11,
            non_repeat_count=0,
            purity=1.0,
            aa_sequence="Q" * 11,
        )
        return {
            "pipeline_run": pipeline_run,
            "import_batch": import_batch,
            "batch": batch,
            "genome": genome,
            "sequence": sequence,
            "protein": protein,
            "repeat_calls": [repeat_call],
        }
