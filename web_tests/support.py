import json
from pathlib import Path


def build_minimal_publish_root(base_dir: Path, *, run_id: str = "run-alpha") -> Path:
    publish_root = base_dir / "publish"
    (publish_root / "manifest").mkdir(parents=True)
    (publish_root / "acquisition").mkdir(parents=True)
    (publish_root / "calls").mkdir(parents=True)

    manifest = {
        "run_id": run_id,
        "status": "success",
        "started_at_utc": "2026-04-06T12:03:46Z",
        "finished_at_utc": "2026-04-06T12:05:44Z",
        "profile": "docker",
        "git_revision": "abc123",
        "inputs": {},
        "paths": {"publish_root": f"runs/{run_id}/publish", "run_root": f"runs/{run_id}"},
        "params": {},
        "enabled_methods": ["pure"],
        "repeat_residues": ["Q"],
        "artifacts": {},
    }
    (publish_root / "manifest" / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    (publish_root / "acquisition" / "taxonomy.tsv").write_text(
        "taxon_id\ttaxon_name\tparent_taxon_id\trank\tsource\n"
        "1\troot\t\tno rank\ttest\n"
        "9606\tHomo sapiens\t1\tspecies\ttest\n",
        encoding="utf-8",
    )
    (publish_root / "acquisition" / "genomes.tsv").write_text(
        "genome_id\tsource\taccession\tgenome_name\tassembly_type\ttaxon_id\tassembly_level\tspecies_name\tdownload_path\tnotes\n"
        "genome_1\tncbi_datasets\tGCF_000001405.40\tExample genome\thaploid\t9606\tChromosome\tHomo sapiens\t/tmp/pkg\t\n",
        encoding="utf-8",
    )
    (publish_root / "acquisition" / "sequences.tsv").write_text(
        "sequence_id\tgenome_id\tsequence_name\tsequence_length\tsequence_path\tgene_symbol\ttranscript_id\tisoform_id\tassembly_accession\ttaxon_id\tsource_record_id\tprotein_external_id\ttranslation_table\tgene_group\tlinkage_status\tpartial_status\n"
        "seq_1\tgenome_1\tNM_000001.1\t900\t/tmp/cds.fna\tGENE1\tNM_000001.1\tNP_000001.1\tGCF_000001405.40\t9606\tcds-1\tNP_000001.1\t1\tGENE1\tgff\t\n"
        "seq_2\tgenome_1\tNM_000002.1\t840\t/tmp/cds_extra.fna\tGENE2\tNM_000002.1\tNP_000002.1\tGCF_000001405.40\t9606\tcds-2\tNP_000002.1\t1\tGENE2\tgff\t\n",
        encoding="utf-8",
    )
    (publish_root / "acquisition" / "proteins.tsv").write_text(
        "protein_id\tsequence_id\tgenome_id\tprotein_name\tprotein_length\tprotein_path\tgene_symbol\ttranslation_method\ttranslation_status\tassembly_accession\ttaxon_id\tgene_group\tprotein_external_id\n"
        "prot_1\tseq_1\tgenome_1\tNP_000001.1\t300\t/tmp/proteins.faa\tGENE1\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE1\tNP_000001.1\n"
        "prot_2\tseq_2\tgenome_1\tNP_000002.1\t280\t/tmp/proteins_extra.faa\tGENE2\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE2\tNP_000002.1\n",
        encoding="utf-8",
    )
    (publish_root / "calls" / "run_params.tsv").write_text(
        "method\tparam_name\tparam_value\n"
        "pure\trepeat_residue\tQ\n",
        encoding="utf-8",
    )
    (publish_root / "calls" / "repeat_calls.tsv").write_text(
        "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\tsource_file\n"
        "call_1\tpure\tgenome_1\t9606\tseq_1\tprot_1\t10\t20\t11\tQ\t11\t0\t1.0\tQQQQQQQQQQQ\t\t\t\t\t\t\t\t/tmp/proteins.faa\n",
        encoding="utf-8",
    )
    return publish_root


def create_imported_run_fixture(
    *,
    run_id: str,
    genome_id: str,
    sequence_id: str,
    protein_id: str,
    call_id: str,
    accession: str,
    taxon_key: str = "human",
    genome_name: str | None = None,
):
    from apps.browser.models import Genome, PipelineRun, Protein, RepeatCall, RunParameter, Sequence

    taxa = ensure_test_taxonomy()
    selected_taxon = taxa[taxon_key]

    pipeline_run = PipelineRun.objects.create(
        run_id=run_id,
        status="success",
        profile="docker",
        git_revision="abc123",
        manifest_path=f"/tmp/{run_id}/manifest/run_manifest.json",
        publish_root=f"/tmp/{run_id}/publish",
        manifest_payload={"run_id": run_id},
    )
    genome = Genome.objects.create(
        pipeline_run=pipeline_run,
        genome_id=genome_id,
        source="ncbi_datasets",
        accession=accession,
        genome_name=genome_name or f"Genome for {run_id}",
        assembly_type="haploid",
        taxon=selected_taxon,
        assembly_level="Chromosome",
        species_name=selected_taxon.taxon_name,
        analyzed_protein_count=1,
    )
    sequence = Sequence.objects.create(
        pipeline_run=pipeline_run,
        genome=genome,
        taxon=selected_taxon,
        sequence_id=sequence_id,
        sequence_name=f"NM_{run_id}",
        sequence_length=900,
        sequence_path=f"/tmp/{run_id}/cds.fna",
        gene_symbol="GENE1",
    )
    protein = Protein.objects.create(
        pipeline_run=pipeline_run,
        genome=genome,
        sequence=sequence,
        taxon=selected_taxon,
        protein_id=protein_id,
        protein_name=f"NP_{run_id}",
        protein_length=300,
        protein_path=f"/tmp/{run_id}/proteins.faa",
        gene_symbol="GENE1",
    )
    run_parameter = RunParameter.objects.create(
        pipeline_run=pipeline_run,
        method=RunParameter.Method.PURE,
        param_name="repeat_residue",
        param_value="Q",
    )
    repeat_call = RepeatCall.objects.create(
        pipeline_run=pipeline_run,
        genome=genome,
        sequence=sequence,
        protein=protein,
        taxon=selected_taxon,
        call_id=call_id,
        method=RepeatCall.Method.PURE,
        start=10,
        end=20,
        length=11,
        repeat_residue="Q",
        repeat_count=11,
        non_repeat_count=0,
        purity=1.0,
        aa_sequence="QQQQQQQQQQQ",
    )
    return {
        "pipeline_run": pipeline_run,
        "genome": genome,
        "sequence": sequence,
        "protein": protein,
        "run_parameter": run_parameter,
        "repeat_call": repeat_call,
        "taxon": selected_taxon,
        "taxa": taxa,
    }


def ensure_test_taxonomy():
    from apps.browser.models import Taxon, TaxonClosure

    definitions = {
        "root": {"taxon_id": 1, "taxon_name": "root", "rank": "no rank", "parent": None},
        "chordata": {"taxon_id": 7711, "taxon_name": "Chordata", "rank": "phylum", "parent": "root"},
        "mammalia": {"taxon_id": 40674, "taxon_name": "Mammalia", "rank": "class", "parent": "chordata"},
        "primates": {"taxon_id": 9443, "taxon_name": "Primates", "rank": "order", "parent": "mammalia"},
        "human": {"taxon_id": 9606, "taxon_name": "Homo sapiens", "rank": "species", "parent": "primates"},
        "mouse": {"taxon_id": 10090, "taxon_name": "Mus musculus", "rank": "species", "parent": "mammalia"},
    }

    taxa = {}
    for key, definition in definitions.items():
        parent_taxon = taxa.get(definition["parent"])
        taxon, _ = Taxon.objects.get_or_create(
            taxon_id=definition["taxon_id"],
            defaults={
                "taxon_name": definition["taxon_name"],
                "rank": definition["rank"],
                "parent_taxon": parent_taxon,
            },
        )
        update_fields = []
        if taxon.taxon_name != definition["taxon_name"]:
            taxon.taxon_name = definition["taxon_name"]
            update_fields.append("taxon_name")
        if taxon.rank != definition["rank"]:
            taxon.rank = definition["rank"]
            update_fields.append("rank")
        if taxon.parent_taxon_id != (parent_taxon.pk if parent_taxon else None):
            taxon.parent_taxon = parent_taxon
            update_fields.append("parent_taxon")
        if update_fields:
            update_fields.append("updated_at")
            taxon.save(update_fields=update_fields)
        taxa[key] = taxon

    for taxon in taxa.values():
        ancestor = taxon
        depth = 0
        while ancestor is not None:
            TaxonClosure.objects.get_or_create(
                ancestor=ancestor,
                descendant=taxon,
                defaults={"depth": depth},
            )
            ancestor = ancestor.parent_taxon
            depth += 1

    return taxa
