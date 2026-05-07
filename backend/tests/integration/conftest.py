"""
Shared pytest fixtures for integration tests.

Integration tests run against real local infrastructure (Kuzu, Qdrant,
Typesense, Postgres) using isolated test namespaces so they don't
pollute production data.

Prerequisites:
  - docker-compose.yml services are running (qdrant, typesense, postgres)
  - Kuzu test DB is in a temp directory (created per-session)

Skip these tests with: pytest tests/unit/ -k "not integration"
"""

from __future__ import annotations

import os
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Skip guard — skip integration suite if env flag is not set
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring live infrastructure",
    )


# ---------------------------------------------------------------------------
# Kuzu test database (isolated temp dir per session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def kuzu_test_db_path(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("kuzu_test")
    return str(db_dir / "test_graph")


@pytest.fixture(scope="session")
def kuzu_test_service(kuzu_test_db_path):
    """Return a GraphService instance pointed at the isolated test Kuzu DB."""
    from app.services.graph import GraphService

    svc = GraphService.__new__(GraphService)
    svc._init_db(kuzu_test_db_path)
    yield svc
    # Kuzu is embedded; cleanup handled by tmp_path_factory


# ---------------------------------------------------------------------------
# Typesense test collection
# ---------------------------------------------------------------------------


TEST_TYPESENSE_COLLECTION = "liveos_test_nodes"


@pytest.fixture(scope="session")
def typesense_test_service():
    """Return a TypesenseService instance using a test collection."""
    from app.services.typesense_service import TypesenseService

    svc = TypesenseService.__new__(TypesenseService)
    svc._collection_name = TEST_TYPESENSE_COLLECTION
    svc._init_client()

    # Ensure clean slate
    try:
        svc.client.collections[TEST_TYPESENSE_COLLECTION].delete()
    except Exception:
        pass
    svc._create_collection_if_missing()

    yield svc

    # Teardown
    try:
        svc.client.collections[TEST_TYPESENSE_COLLECTION].delete()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Environment marker
# ---------------------------------------------------------------------------


INTEGRATION_ENV_VAR = "RUN_INTEGRATION_TESTS"


def pytest_collection_modifyitems(config, items):
    if not os.environ.get(INTEGRATION_ENV_VAR):
        skip_marker = pytest.mark.skip(
            reason=f"Set {INTEGRATION_ENV_VAR}=1 to run integration tests"
        )
        for item in items:
            if "integration" in item.nodeid:
                item.add_marker(skip_marker)
