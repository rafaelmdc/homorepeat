from __future__ import annotations


def bump_catalog_version() -> int:
    """Increment CatalogVersion and return the new version number."""
    from apps.imports.models import CatalogVersion

    return CatalogVersion.increment()
