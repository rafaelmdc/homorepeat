from collections import Counter, OrderedDict

from .metrics import _coordinate_label, _summary_label, normalize_purity


def _trusted_accession(repeat_call):
    accession = (repeat_call.genome.accession or repeat_call.accession or "").strip()
    return accession or None


def _trusted_protein_id(repeat_call):
    protein_id = (repeat_call.protein.protein_id or "").strip()
    return protein_id or None


def _trusted_method(repeat_call):
    method = (repeat_call.method or "").strip()
    return method or None


def _trusted_residue(repeat_call):
    residue = (repeat_call.repeat_residue or "").strip().upper()
    return residue or None


def _protein_identity_key(repeat_call):
    accession = _trusted_accession(repeat_call)
    protein_id = _trusted_protein_id(repeat_call)
    method = _trusted_method(repeat_call)
    if accession is None or protein_id is None or method is None:
        return None
    return accession, protein_id, method


def _protein_residue_identity_key(repeat_call):
    protein_key = _protein_identity_key(repeat_call)
    residue = _trusted_residue(repeat_call)
    if protein_key is None or residue is None:
        return None
    return protein_key + (residue,)


def _identity_merged_protein_groups_from_repeat_calls(source_repeat_calls):
    grouped_proteins = OrderedDict()

    for repeat_call in source_repeat_calls:
        key = _protein_identity_key(repeat_call)
        if key is None:
            continue

        if key not in grouped_proteins:
            grouped_proteins[key] = {
                "accession": key[0],
                "protein_id": key[1],
                "method": key[2],
                "source_repeat_calls": [],
                "source_runs": set(),
                "gene_symbols": set(),
                "residue_keys": set(),
                "collapsed_call_keys": set(),
                "methods": set(),
                "repeat_residues": set(),
                "coordinates": set(),
                "protein_lengths": set(),
            }

        grouped_proteins[key]["source_repeat_calls"].append(repeat_call)
        grouped_proteins[key]["source_runs"].add(repeat_call.pipeline_run.run_id)
        if repeat_call.protein.gene_symbol:
            grouped_proteins[key]["gene_symbols"].add(repeat_call.protein.gene_symbol)
        residue_key = _protein_residue_identity_key(repeat_call)
        if residue_key is not None:
            grouped_proteins[key]["residue_keys"].add(residue_key)
        grouped_proteins[key]["collapsed_call_keys"].add(_collapsed_repeat_call_key(repeat_call))
        grouped_proteins[key]["methods"].add(repeat_call.method)
        residue = _trusted_residue(repeat_call)
        if residue is not None:
            grouped_proteins[key]["repeat_residues"].add(residue)
        grouped_proteins[key]["coordinates"].add((repeat_call.start, repeat_call.end))
        if repeat_call.protein.protein_length:
            grouped_proteins[key]["protein_lengths"].add(repeat_call.protein.protein_length)

    protein_groups = []
    for protein_group in grouped_proteins.values():
        representative_repeat_call = _representative_repeat_call(protein_group["source_repeat_calls"])
        protein_group["representative_repeat_call"] = representative_repeat_call
        protein_group["protein_name"] = representative_repeat_call.protein.protein_name
        protein_group["protein_length"] = representative_repeat_call.protein.protein_length
        protein_group["gene_symbols"] = sorted(protein_group["gene_symbols"])
        protein_group["gene_symbol_label"] = ", ".join(protein_group["gene_symbols"]) if protein_group["gene_symbols"] else "-"
        protein_group["source_repeat_calls"] = _sorted_source_repeat_calls(protein_group["source_repeat_calls"])
        protein_group["source_run_records"] = _sorted_source_runs(protein_group["source_repeat_calls"])
        protein_group["source_proteins"] = _sorted_source_proteins(protein_group["source_repeat_calls"])
        protein_group["source_runs"] = sorted(protein_group["source_runs"])
        protein_group["source_runs_count"] = len(protein_group["source_runs"])
        protein_group["source_proteins_count"] = len(protein_group["source_proteins"])
        protein_group["source_repeat_calls_count"] = len(protein_group["source_repeat_calls"])
        protein_group["residue_groups_count"] = len(protein_group["residue_keys"])
        protein_group["collapsed_repeat_calls_count"] = len(protein_group["collapsed_call_keys"])
        protein_group["methods"] = sorted(protein_group["methods"])
        protein_group["methods_label"] = _summary_label(protein_group["methods"])
        protein_group["repeat_residues"] = sorted(protein_group["repeat_residues"])
        protein_group["repeat_residues_label"] = _summary_label(protein_group["repeat_residues"])
        protein_group["coordinate_label"] = _coordinate_label(protein_group["coordinates"])
        protein_group["protein_length_label"] = _summary_label(sorted(protein_group["protein_lengths"], key=int))
        protein_group.pop("residue_keys")
        protein_group.pop("collapsed_call_keys")
        protein_group.pop("coordinates")
        protein_group.pop("protein_lengths")
        protein_groups.append(protein_group)

    return sorted(protein_groups, key=lambda group: (group["accession"], group["protein_id"], group["method"]))


def _identity_merged_residue_groups_from_repeat_calls(source_repeat_calls):
    grouped_residues = OrderedDict()

    for repeat_call in source_repeat_calls:
        key = _protein_residue_identity_key(repeat_call)
        if key is None:
            continue

        if key not in grouped_residues:
            grouped_residues[key] = {
                "accession": key[0],
                "protein_id": key[1],
                "method": key[2],
                "repeat_residue": key[3],
                "source_repeat_calls": [],
                "source_runs": set(),
                "source_taxa": set(),
                "gene_symbols": set(),
                "methods": set(),
                "coordinates": set(),
                "protein_lengths": set(),
                "lengths": set(),
                "purities": set(),
            }

        grouped_residues[key]["source_repeat_calls"].append(repeat_call)
        grouped_residues[key]["source_runs"].add(repeat_call.pipeline_run.run_id)
        grouped_residues[key]["source_taxa"].add(repeat_call.taxon.taxon_name)
        if repeat_call.protein.gene_symbol:
            grouped_residues[key]["gene_symbols"].add(repeat_call.protein.gene_symbol)
        grouped_residues[key]["methods"].add(repeat_call.method)
        grouped_residues[key]["coordinates"].add((repeat_call.start, repeat_call.end))
        if repeat_call.protein.protein_length:
            grouped_residues[key]["protein_lengths"].add(repeat_call.protein.protein_length)
        grouped_residues[key]["lengths"].add(repeat_call.length)
        grouped_residues[key]["purities"].add(normalize_purity(repeat_call.purity))

    residue_groups = []
    for residue_group in grouped_residues.values():
        representative_repeat_call = _representative_repeat_call(residue_group["source_repeat_calls"])
        residue_group["representative_repeat_call"] = representative_repeat_call
        residue_group["protein_name"] = representative_repeat_call.protein.protein_name
        residue_group["protein_length"] = representative_repeat_call.protein.protein_length
        residue_group["method"] = representative_repeat_call.method
        residue_group["methods"] = sorted(residue_group["methods"])
        residue_group["methods_label"] = _summary_label(residue_group["methods"])
        residue_group["start"] = representative_repeat_call.start
        residue_group["end"] = representative_repeat_call.end
        residue_group["coordinate_label"] = _coordinate_label(residue_group["coordinates"])
        residue_group["length"] = representative_repeat_call.length
        residue_group["length_label"] = _summary_label(sorted(residue_group["lengths"], key=int))
        residue_group["normalized_purity"] = normalize_purity(representative_repeat_call.purity)
        residue_group["purity_label"] = _summary_label(residue_group["purities"])
        residue_group["source_repeat_calls"] = _sorted_source_repeat_calls(residue_group["source_repeat_calls"])
        residue_group["source_run_records"] = _sorted_source_runs(residue_group["source_repeat_calls"])
        residue_group["source_proteins"] = _sorted_source_proteins(residue_group["source_repeat_calls"])
        residue_group["source_runs"] = sorted(residue_group["source_runs"])
        residue_group["source_runs_count"] = len(residue_group["source_runs"])
        residue_group["source_taxa"] = sorted(residue_group["source_taxa"])
        residue_group["source_taxa_label"] = ", ".join(residue_group["source_taxa"]) if residue_group["source_taxa"] else "-"
        residue_group["gene_symbols"] = sorted(residue_group["gene_symbols"])
        residue_group["gene_symbol_label"] = ", ".join(residue_group["gene_symbols"]) if residue_group["gene_symbols"] else "-"
        residue_group["source_proteins_count"] = len(residue_group["source_proteins"])
        residue_group["protein_length_label"] = _summary_label(sorted(residue_group["protein_lengths"], key=int))
        residue_group["source_count"] = len(residue_group["source_repeat_calls"])
        residue_group.pop("coordinates")
        residue_group.pop("protein_lengths")
        residue_group.pop("lengths")
        residue_group.pop("purities")
        residue_groups.append(residue_group)

    return sorted(
        residue_groups,
        key=lambda group: (group["accession"], group["protein_id"], group["method"], group["repeat_residue"]),
    )


def _sorted_source_repeat_calls(source_repeat_calls):
    return sorted(
        source_repeat_calls,
        key=lambda repeat_call: (
            repeat_call.pipeline_run.run_id,
            repeat_call.call_id,
        ),
    )


def _sorted_source_runs(source_repeat_calls):
    unique_runs = {repeat_call.pipeline_run.pk: repeat_call.pipeline_run for repeat_call in source_repeat_calls}
    return sorted(unique_runs.values(), key=lambda pipeline_run: (pipeline_run.run_id, pipeline_run.pk))


def _sorted_source_proteins(source_repeat_calls):
    unique_proteins = {}
    for repeat_call in source_repeat_calls:
        unique_proteins[repeat_call.protein.pk] = {
            "pk": repeat_call.protein.pk,
            "protein_id": repeat_call.protein.protein_id,
            "protein_name": repeat_call.protein.protein_name,
            "run_id": repeat_call.pipeline_run.run_id,
        }
    return sorted(
        unique_proteins.values(),
        key=lambda protein: (protein["run_id"], protein["protein_id"], protein["pk"]),
    )


def _representative_repeat_call(source_repeat_calls):
    return max(source_repeat_calls, key=_representative_repeat_call_key)


def _representative_repeat_call_key(repeat_call):
    protein_name = repeat_call.protein.protein_name or repeat_call.protein_name
    gene_symbol = repeat_call.protein.gene_symbol or repeat_call.gene_symbol
    protein_length = repeat_call.protein.protein_length or repeat_call.protein_length or 0

    return (
        int(bool(protein_name)),
        int(bool(gene_symbol)),
        int(protein_length > 0),
        int(bool(repeat_call.aa_sequence)),
        int(bool(repeat_call.method)),
        int(bool(_trusted_residue(repeat_call))),
        protein_length,
        repeat_call.length,
        float(repeat_call.purity),
        repeat_call.pipeline_run.imported_at,
        repeat_call.pipeline_run.run_id,
        repeat_call.call_id,
    )


def _identity_audit(source_repeat_calls, identity_key):
    included_by_accession = Counter()
    excluded_by_accession = Counter()

    for repeat_call in source_repeat_calls:
        accession = _trusted_accession(repeat_call)
        if identity_key(repeat_call) is None:
            if accession is not None:
                excluded_by_accession[accession] += 1
            continue
        if accession is not None:
            included_by_accession[accession] += 1

    return {
        "included_count": sum(included_by_accession.values()),
        "excluded_count": sum(excluded_by_accession.values()),
        "included_by_accession": included_by_accession,
        "excluded_by_accession": excluded_by_accession,
    }


def _merged_protein_groups_from_repeat_calls(source_repeat_calls):
    return _identity_merged_protein_groups_from_repeat_calls(source_repeat_calls)


def _collapsed_repeat_call_groups(source_repeat_calls):
    grouped_calls = OrderedDict()

    for repeat_call in source_repeat_calls:
        key = _collapsed_repeat_call_key(repeat_call)
        if key not in grouped_calls:
            grouped_calls[key] = {
                "accession": repeat_call.genome.accession,
                "protein_name": repeat_call.protein.protein_name,
                "protein_length": repeat_call.protein.protein_length,
                "method": repeat_call.method,
                "start": repeat_call.start,
                "end": repeat_call.end,
                "repeat_residue": repeat_call.repeat_residue,
                "length": repeat_call.length,
                "normalized_purity": normalize_purity(repeat_call.purity),
                "source_repeat_calls": [],
                "source_runs": set(),
                "source_taxa": set(),
                "gene_symbols": set(),
            }

        grouped_calls[key]["source_repeat_calls"].append(repeat_call)
        grouped_calls[key]["source_runs"].add(repeat_call.pipeline_run.run_id)
        grouped_calls[key]["source_taxa"].add(repeat_call.taxon.taxon_name)
        if repeat_call.protein.gene_symbol:
            grouped_calls[key]["gene_symbols"].add(repeat_call.protein.gene_symbol)

    collapsed_groups = list(grouped_calls.values())
    for group in collapsed_groups:
        group["source_repeat_calls"] = sorted(
            group["source_repeat_calls"],
            key=lambda repeat_call: (
                repeat_call.pipeline_run.run_id,
                repeat_call.call_id,
            ),
        )
        group["source_runs"] = sorted(group["source_runs"])
        group["source_runs_count"] = len(group["source_runs"])
        group["source_taxa"] = sorted(group["source_taxa"])
        group["source_taxa_label"] = ", ".join(group["source_taxa"]) if group["source_taxa"] else "-"
        group["gene_symbols"] = sorted(group["gene_symbols"])
        group["gene_symbol_label"] = ", ".join(group["gene_symbols"]) if group["gene_symbols"] else "-"
        group["source_count"] = len(group["source_repeat_calls"])

    collapsed_groups.sort(
        key=lambda group: (
            group["method"],
            group["protein_name"],
            group["start"],
            group["end"],
            group["repeat_residue"],
            group["normalized_purity"],
        )
    )
    return collapsed_groups


def _collapsed_repeat_call_key(repeat_call):
    return (
        repeat_call.genome.accession,
        repeat_call.protein.protein_name,
        repeat_call.protein.protein_length,
        repeat_call.method,
        repeat_call.start,
        repeat_call.end,
        repeat_call.repeat_residue,
        repeat_call.length,
        normalize_purity(repeat_call.purity),
    )
