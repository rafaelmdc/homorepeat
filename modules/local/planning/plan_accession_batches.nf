process PLAN_ACCESSION_BATCHES {
    label 'planning'
    publishDir("${params.output_dir}/planning", mode: 'copy', saveAs: { filename ->
        filename.startsWith('planning_artifacts/') ? filename.substring('planning_artifacts/'.length()) : filename
    })

    input:
    path(accessions_file)

    output:
    path("planning_artifacts/accession_batches.tsv"), emit: batch_table
    path("planning_artifacts/selected_accessions.txt"), emit: selected_accessions
    path("planning_artifacts/batch_manifests"), emit: batch_manifests_dir

    script:
    """
    export PYTHONPATH="${projectDir}:\${PYTHONPATH:-}"

    ${params.python_bin} ${projectDir}/bin/plan_accession_batches.py \
      --accessions-file ${accessions_file} \
      --target-batch-size ${params.batch_size} \
      --outdir planning_artifacts
    """
}
