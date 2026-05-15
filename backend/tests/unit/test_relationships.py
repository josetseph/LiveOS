"""Unit tests for app/schemas/relationships.py — pure relationship logic functions.

All functions are pure Python with no I/O. No mocking required.
"""

import pytest

from app.schemas.relationships import (
    can_evolve,
    get_contradicting_types,
    get_expected_relationships,
    get_inverse_type,
    is_bidirectional,
)

# ── get_contradicting_types ───────────────────────────────────────────────────


class TestGetContradictingTypes:
    def test_friends_with_contradicted_by_enemies(self):
        result = get_contradicting_types("friends_with")
        assert "enemies_with" in result
        assert "hates" in result

    def test_known_relationship_returns_list(self):
        result = get_contradicting_types("friends_with")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_all_values_are_strings(self):
        result = get_contradicting_types("friends_with")
        for item in result:
            assert isinstance(item, str), f"Expected str, got {type(item)}: {item!r}"

    def test_knows_has_no_contradictions(self):
        assert get_contradicting_types("knows") == []

    def test_unknown_type_returns_empty_list(self):
        assert get_contradicting_types("invented_nonexistent_type") == []

    def test_empty_string_returns_empty_list(self):
        assert get_contradicting_types("") == []


# ── get_expected_relationships ────────────────────────────────────────────────


class TestGetExpectedRelationships:
    def test_person_to_person_contains_knows(self):
        result = get_expected_relationships("Person", "Person")
        assert "knows" in result

    def test_person_to_person_contains_friends_with(self):
        result = get_expected_relationships("Person", "Person")
        assert "friends_with" in result

    def test_person_to_task_contains_assigned_to(self):
        result = get_expected_relationships("Person", "Task")
        assert "assigned_to" in result

    def test_entity_to_entity_contains_depends_on(self):
        result = get_expected_relationships("Entity", "Entity")
        assert "depends_on" in result

    def test_unknown_pair_returns_empty_list(self):
        result = get_expected_relationships("Unicorn", "Dragon")
        assert result == []

    def test_returns_list_type(self):
        result = get_expected_relationships("Person", "Person")
        assert isinstance(result, list)


# ── can_evolve ────────────────────────────────────────────────────────────────


class TestCanEvolve:
    def test_knows_can_evolve_to_friends_with(self):
        assert can_evolve("knows", "friends_with") is True

    def test_knows_cannot_evolve_to_married_to(self):
        assert can_evolve("knows", "married_to") is False

    def test_friends_with_can_evolve_to_married_to(self):
        assert can_evolve("friends_with", "married_to") is True

    def test_learning_can_evolve_to_expert_in(self):
        assert can_evolve("learning", "expert_in") is True

    def test_unknown_current_type_returns_false(self):
        assert can_evolve("totally_made_up_type", "friends_with") is False

    def test_empty_current_type_returns_false(self):
        assert can_evolve("", "friends_with") is False

    def test_returns_bool(self):
        result = can_evolve("knows", "friends_with")
        assert isinstance(result, bool)


# ── is_bidirectional ──────────────────────────────────────────────────────────


class TestIsBidirectional:
    @pytest.mark.parametrize(
        "rel_type",
        [
            "works_with",
            "collaborates_with",
            "friends_with",
            "married_to",
            "partners_with",
            "knows",
            "related_to",
        ],
    )
    def test_known_bidirectional_types(self, rel_type):
        assert is_bidirectional(rel_type) is True

    def test_directional_type_returns_false(self):
        assert is_bidirectional("created_by") is False

    def test_owns_is_directional(self):
        assert is_bidirectional("owns") is False

    def test_unknown_type_returns_false(self):
        assert is_bidirectional("invented_type_xyz") is False

    def test_returns_bool(self):
        result = is_bidirectional("knows")
        assert isinstance(result, bool)


# ── get_inverse_type ──────────────────────────────────────────────────────────


class TestGetInverseType:
    def test_created_by_inverts_to_owns(self):
        assert get_inverse_type("created_by") == "owns"

    def test_owns_inverts_to_created_by(self):
        assert get_inverse_type("owns") == "created_by"

    def test_contains_inverts_to_part_of(self):
        assert get_inverse_type("contains") == "part_of"

    def test_part_of_inverts_to_contains(self):
        assert get_inverse_type("part_of") == "contains"

    def test_related_to_has_no_inverse(self):
        # related_to is bidirectional; there is no asymmetric inverse
        assert get_inverse_type("related_to") is None

    def test_unknown_type_returns_none(self):
        assert get_inverse_type("completely_unknown_xyz") is None

    def test_empty_string_returns_none(self):
        assert get_inverse_type("") is None
