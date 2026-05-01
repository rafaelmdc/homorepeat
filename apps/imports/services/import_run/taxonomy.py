from __future__ import annotations

from apps.browser.models.taxonomy import Taxon, TaxonClosure
from apps.imports.services.published_run import (
    ImportContractError,
    InspectedPublishedRun,
    V2ArtifactPaths,
    iter_taxonomy_rows,
)

from .copy import BULK_CREATE_BATCH_SIZE


def _load_taxonomy_rows(inspected: InspectedPublishedRun) -> list[dict[str, object]]:
    merged_by_taxon_id: dict[int, dict[str, object]] = {}
    ordered_taxon_ids: list[int] = []

    if isinstance(inspected.artifact_paths, V2ArtifactPaths):
        row_sources = (iter_taxonomy_rows(inspected.artifact_paths.taxonomy_tsv),)
    else:
        row_sources = (
            iter_taxonomy_rows(batch_paths.taxonomy_tsv)
            for batch_paths in inspected.artifact_paths.acquisition_batches
        )

    for rows in row_sources:
        for row in rows:
            taxon_id = int(row["taxon_id"])
            existing = merged_by_taxon_id.get(taxon_id)
            if existing is None:
                merged_by_taxon_id[taxon_id] = row
                ordered_taxon_ids.append(taxon_id)
                continue
            if existing != row:
                raise ImportContractError(
                    f"Conflicting duplicate taxonomy rows were found for taxon_id={taxon_id!r}"
                )

    return [merged_by_taxon_id[taxon_id] for taxon_id in ordered_taxon_ids]


def _upsert_taxa(rows: list[dict[str, object]]) -> dict[int, Taxon]:
    taxon_ids = [int(row["taxon_id"]) for row in rows]
    parent_taxon_ids = {
        int(row["parent_taxon_id"])
        for row in rows
        if row.get("parent_taxon_id") is not None
    }
    existing = Taxon.objects.in_bulk(set(taxon_ids) | parent_taxon_ids, field_name="taxon_id")

    for row in rows:
        taxon_id = int(row["taxon_id"])
        taxon = existing.get(taxon_id)
        if taxon is None:
            taxon = Taxon.objects.create(
                taxon_id=taxon_id,
                taxon_name=str(row["taxon_name"]),
                rank=str(row["rank"]),
                source=str(row["source"]),
            )
        else:
            taxon.taxon_name = str(row["taxon_name"])
            taxon.rank = str(row["rank"])
            taxon.source = str(row["source"])
            taxon.save(update_fields=["taxon_name", "rank", "source", "updated_at"])
        existing[taxon_id] = taxon

    for row in rows:
        taxon = existing[int(row["taxon_id"])]
        parent_taxon_id = row.get("parent_taxon_id")
        parent = existing.get(int(parent_taxon_id)) if parent_taxon_id is not None else None
        if parent_taxon_id is not None and parent is None:
            raise ImportContractError(
                f"Taxonomy references missing parent taxon_id {parent_taxon_id!r}"
            )
        if taxon.parent_taxon_id != (parent.pk if parent else None):
            taxon.parent_taxon = parent
            taxon.save(update_fields=["parent_taxon", "updated_at"])

    return existing


def _rebuild_taxon_closure() -> None:
    taxa = list(Taxon.objects.only("id", "parent_taxon_id"))
    by_pk = {taxon.pk: taxon for taxon in taxa}
    closure_rows: list[TaxonClosure] = []

    for descendant in taxa:
        current = descendant
        depth = 0
        seen: set[int] = set()
        while current is not None:
            if current.pk in seen:
                raise ImportContractError("Taxonomy contains a parent cycle and cannot build closure")
            seen.add(current.pk)
            closure_rows.append(
                TaxonClosure(
                    ancestor_id=current.pk,
                    descendant_id=descendant.pk,
                    depth=depth,
                )
            )
            parent_pk = current.parent_taxon_id
            if parent_pk is None:
                current = None
            else:
                current = by_pk.get(parent_pk)
                if current is None:
                    raise ImportContractError(
                        f"Taxonomy references missing parent primary key {parent_pk!r}"
                    )
                depth += 1

    TaxonClosure.objects.all().delete()
    TaxonClosure.objects.bulk_create(closure_rows, batch_size=BULK_CREATE_BATCH_SIZE)


def _require_taxon(
    natural_taxon_id: object,
    taxon_by_taxon_id: dict[int, Taxon],
    label: str,
) -> Taxon:
    if natural_taxon_id is None:
        raise ImportContractError(f"{label.capitalize()} row is missing a required taxon_id")
    taxon = taxon_by_taxon_id.get(int(natural_taxon_id))
    if taxon is None:
        raise ImportContractError(
            f"{label.capitalize()} row references missing taxon_id {natural_taxon_id!r}"
        )
    return taxon
