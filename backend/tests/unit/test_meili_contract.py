"""
Unit tests for MeilisearchService contract.

Regression guard:
  - update_node_community always includes node_id in the document
  - index_node includes both node_id and name
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_meili_service():
    from app.services.meilisearch_service import MeilisearchService

    svc = MeilisearchService.__new__(MeilisearchService)
    svc.client = MagicMock()
    svc.collection = "test_nodes"
    svc._enabled = True
    svc.is_available = MagicMock(return_value=True)
    index = MagicMock()
    task = MagicMock()
    task.task_uid = 1
    index.add_documents.return_value = task
    svc._index = MagicMock(return_value=index)
    svc.client.wait_for_task = MagicMock()
    return svc, index


class TestUpdateNodeCommunity:
    def test_update_always_includes_node_id(self):
        svc, index = _make_meili_service()
        svc.get_node = MagicMock(return_value=None)

        svc.update_node_community(node_id="abc-123")

        index.add_documents.assert_called_once()
        docs = index.add_documents.call_args[0][0]
        assert docs[0]["node_id"] == "abc-123"

    def test_update_with_name_includes_node_id_and_name(self):
        svc, index = _make_meili_service()
        svc.get_node = MagicMock(return_value={"node_id": "abc-123"})

        svc.update_node_community(node_id="abc-123", name="Alice Smith")

        docs = index.add_documents.call_args[0][0]
        assert docs[0]["node_id"] == "abc-123"
        assert docs[0]["name"] == "Alice Smith"

    def test_errors_are_logged_not_raised(self):
        svc, index = _make_meili_service()
        svc.get_node = MagicMock(return_value={"node_id": "bad-node"})
        index.add_documents.side_effect = Exception("index error")

        with patch("app.services.meilisearch_service.logger") as mock_logger:
            svc.update_node_community(node_id="bad-node")
            mock_logger.debug.assert_called()


class TestIndexNode:
    def test_index_node_includes_node_id_and_name(self):
        svc, index = _make_meili_service()

        svc.index_node(
            node_id="xyz-456",
            name="Bob Jones",
            node_type="person",
        )

        docs = index.add_documents.call_args[0][0]
        assert docs[0]["node_id"] == "xyz-456"
        assert docs[0]["name"] == "Bob Jones"
