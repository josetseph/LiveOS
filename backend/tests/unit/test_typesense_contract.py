"""
Unit tests for TypesenseService contract.

Regression guard:
  - update_node_community always includes node_id in the PATCH document
    (prevents the 7,468 "Field node_id has been declared in schema" 400 errors)
  - index_node includes both node_id and name
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


def _make_typesense_service():
    from app.services.typesense_service import TypesenseService

    svc = TypesenseService.__new__(TypesenseService)
    svc.client = MagicMock()
    svc.is_available = MagicMock(return_value=True)
    return svc


class TestUpdateNodeCommunity:
    def test_patch_path_always_includes_node_id(self):
        """When name is not provided, the PATCH doc must still include node_id."""
        svc = _make_typesense_service()

        # Simulate successful PATCH
        svc.client.collections.__getitem__.return_value.documents.__getitem__.return_value.update = (
            MagicMock()
        )

        svc.update_node_community(
            node_id="abc-123",
            # name intentionally omitted — triggers the PATCH path
        )

        update_call = (
            svc.client.collections.__getitem__.return_value.documents.__getitem__.return_value.update
        )
        update_call.assert_called_once()
        doc_arg = update_call.call_args[0][0]
        assert (
            "node_id" in doc_arg
        ), "PATCH document must include node_id to satisfy Typesense schema"
        assert doc_arg["node_id"] == "abc-123"

    def test_upsert_path_includes_node_id_and_name(self):
        """When name IS provided, the upsert must include both node_id and name."""
        svc = _make_typesense_service()
        svc.client.collections.__getitem__.return_value.documents.upsert = MagicMock()

        svc.update_node_community(
            node_id="abc-123",
            name="Alice Smith",
        )

        upsert_call = svc.client.collections.__getitem__.return_value.documents.upsert
        upsert_call.assert_called_once()
        doc_arg = upsert_call.call_args[0][0]
        assert "node_id" in doc_arg
        assert doc_arg["node_id"] == "abc-123"
        assert "name" in doc_arg
        assert doc_arg["name"] == "Alice Smith"

    def test_404_not_found_is_silenced(self):
        """Genuine 404 (doc not in index) must not propagate as an exception."""
        svc = _make_typesense_service()
        svc.client.collections.__getitem__.return_value.documents.__getitem__.return_value.update = MagicMock(
            side_effect=Exception("object not found")
        )

        # Must not raise
        svc.update_node_community(node_id="missing")

    def test_400_schema_error_is_logged_not_raised(self):
        """Schema contract errors must be caught and logged, not propagated."""
        svc = _make_typesense_service()
        svc.client.collections.__getitem__.return_value.documents.__getitem__.return_value.update = MagicMock(
            side_effect=Exception(
                "Field 'node_id' has been declared in the schema, but is not found in the document"
            )
        )

        with patch("app.services.typesense_service.logger") as mock_logger:
            svc.update_node_community(node_id="bad-node")
            # Should log at debug level, not raise
            mock_logger.debug.assert_called()


class TestIndexNode:
    def test_index_node_includes_node_id_and_name(self):
        """index_node must always include both required schema fields."""
        from app.services.typesense_service import TypesenseService

        svc = TypesenseService.__new__(TypesenseService)
        svc.client = MagicMock()
        svc.is_available = MagicMock(return_value=True)
        svc.client.collections.__getitem__.return_value.documents.upsert = MagicMock()

        svc.index_node(
            node_id="xyz-456",
            name="Bob Jones",
            node_type="person",
        )

        upsert_call = svc.client.collections.__getitem__.return_value.documents.upsert
        upsert_call.assert_called_once()
        doc_arg = upsert_call.call_args[0][0]
        assert "node_id" in doc_arg
        assert doc_arg["node_id"] == "xyz-456"
        assert "name" in doc_arg
        assert doc_arg["name"] == "Bob Jones"
