"""Typesense compatibility shim — keyword search is now Meilisearch."""

from app.services.meilisearch_service import (  # noqa: F401
    MeilisearchService,
    MeilisearchService as TypesenseService,
    meilisearch_service,
    meilisearch_service as typesense_service,
)
