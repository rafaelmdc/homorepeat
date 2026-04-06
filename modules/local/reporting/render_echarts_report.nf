process RENDER_ECHARTS_REPORT {
    label 'reporting'
    publishDir "${params.output_dir}/report_prep", mode: 'copy'

    input:
    path(summary_tsv)
    path(regression_tsv)
    path(echarts_options)

    output:
    path('echarts_report.html'), emit: echarts_report
    path('echarts.min.js'), emit: echarts_asset

    script:
    """
    export PYTHONPATH="${projectDir}:\${PYTHONPATH:-}"

    ${params.python_bin} ${projectDir}/bin/render_echarts_report.py \
      --summary-tsv ${summary_tsv} \
      --regression-tsv ${regression_tsv} \
      --options-json ${echarts_options} \
      --outdir report_render_tmp

    mv report_render_tmp/echarts_report.html echarts_report.html
    mv report_render_tmp/echarts.min.js echarts.min.js
    """
}
