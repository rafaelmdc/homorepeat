# Phase 7 Reference

This folder defines the usability and reproducibility layer for the current workflow.

Current Phase 7 goals:
- make the repo runnable without ad hoc local scratch files
- document the primary run paths clearly
- provide checked-in example inputs
- make the container bootstrap step explicit
- document the expected run output tree

Current first-pass usability assets:
- [README.md](../../../README.md)
- [smoke_human.txt](../../../examples/accessions/smoke_human.txt)
- [smoke_default.json](../../../examples/params/smoke_default.json)
- [multi_residue_qn.json](../../../examples/params/multi_residue_qn.json)
- [build_dev_containers.sh](../../../scripts/build_dev_containers.sh)
- [run_phase4_pipeline.sh](../../../scripts/run_phase4_pipeline.sh)
- [output-layout.md](output-layout.md)

Current first-pass boundaries:
- the pipeline still starts from an accession list, not a taxon-driven generator
- the validated execution path is still the `docker` profile
- cluster-oriented runtime profiles are deferred
