"""
Relationship Schema for Knowledge Graph
Defines universal relationship types supporting any-to-any node connections
"""

from typing import List, Dict, Set
from enum import Enum


class RelationshipType(str, Enum):
    """Universal relationship types (any node → any node)"""

    # Structural
    PART_OF = "part_of"
    CONTAINS = "contains"
    COMPOSED_OF = "composed_of"

    # Dependency & Sequence
    DEPENDS_ON = "depends_on"
    BLOCKS = "blocks"
    PREREQUISITE_FOR = "prerequisite_for"
    ENABLES = "enables"
    LEADS_TO = "leads_to"

    # Association & Reference
    RELATED_TO = "related_to"
    REFERENCES = "references"
    MENTIONED_IN = "mentioned_in"
    ASSOCIATED_WITH = "associated_with"

    # Ownership & Responsibility
    OWNS = "owns"
    CREATED_BY = "created_by"
    RESPONSIBLE_FOR = "responsible_for"
    ASSIGNED_TO = "assigned_to"
    MANAGES = "manages"

    # Collaboration & Social
    WORKS_WITH = "works_with"
    COLLABORATES_WITH = "collaborates_with"
    REPORTS_TO = "reports_to"
    MENTORS = "mentors"
    KNOWS = "knows"
    FRIENDS_WITH = "friends_with"
    MARRIED_TO = "married_to"
    PARTNERS_WITH = "partners_with"

    # Functional & Implementation
    IMPLEMENTS = "implements"
    USES = "uses"
    AFFECTS = "affects"
    MODIFIES = "modifies"
    PRODUCES = "produces"

    # Temporal & Causation
    TRIGGERED_BY = "triggered_by"
    CAUSED_BY = "caused_by"
    RESULTED_IN = "resulted_in"
    PRECEDED_BY = "preceded_by"
    FOLLOWED_BY = "followed_by"

    # Semantic & Knowledge
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    VALIDATES = "validates"
    DEMONSTRATES = "demonstrates"
    EXEMPLIFIES = "exemplifies"
    EXPERT_IN = "expert_in"
    LEARNING = "learning"
    TEACHES = "teaches"

    # Task & Project
    SUBTASK_OF = "subtask_of"
    MILESTONE_FOR = "milestone_for"
    DELIVERABLE_OF = "deliverable_of"

    # Additional useful relationships
    WORKS_ON = "works_on"
    INTEGRATES_WITH = "integrates_with"
    BASED_ON = "based_on"
    REQUIRES = "requires"
    INVOLVES = "involves"
    INTRODUCED = "introduced"


# Common relationship patterns by node type combination
COMMON_PATTERNS: Dict[str, List[str]] = {
    # Person → Person
    "Person→Person": [
        RelationshipType.KNOWS,
        RelationshipType.FRIENDS_WITH,
        RelationshipType.MARRIED_TO,
        RelationshipType.WORKS_WITH,
        RelationshipType.REPORTS_TO,
        RelationshipType.MENTORS,
        RelationshipType.COLLABORATES_WITH,
        RelationshipType.PARTNERS_WITH,
    ],
    # Person → Task
    "Person→Task": [
        RelationshipType.ASSIGNED_TO,
        RelationshipType.RESPONSIBLE_FOR,
        RelationshipType.OWNS,
        RelationshipType.CREATED_BY,
    ],
    # Person → Entity
    "Person→Entity": [
        RelationshipType.WORKS_ON,
        RelationshipType.OWNS,
        RelationshipType.MANAGES,
        RelationshipType.CREATED_BY,
    ],
    # Person → Concept
    "Person→Concept": [
        RelationshipType.EXPERT_IN,
        RelationshipType.LEARNING,
        RelationshipType.TEACHES,
    ],
    # Task → Task
    "Task→Task": [
        RelationshipType.DEPENDS_ON,
        RelationshipType.BLOCKS,
        RelationshipType.SUBTASK_OF,
        RelationshipType.RELATED_TO,
        RelationshipType.PREREQUISITE_FOR,
        RelationshipType.LEADS_TO,
    ],
    # Task → Entity
    "Task→Entity": [
        RelationshipType.USES,
        RelationshipType.MODIFIES,
        RelationshipType.AFFECTS,
        RelationshipType.IMPLEMENTS,
    ],
    # Task → Concept
    "Task→Concept": [
        RelationshipType.IMPLEMENTS,
        RelationshipType.DEMONSTRATES,
        RelationshipType.REQUIRES,
    ],
    # Entity → Entity
    "Entity→Entity": [
        RelationshipType.DEPENDS_ON,
        RelationshipType.USES,
        RelationshipType.INTEGRATES_WITH,
        RelationshipType.PART_OF,
        RelationshipType.CONTAINS,
    ],
    # Entity → Concept
    "Entity→Concept": [
        RelationshipType.IMPLEMENTS,
        RelationshipType.BASED_ON,
        RelationshipType.USES,
        RelationshipType.DEMONSTRATES,
    ],
    # Concept → Concept
    "Concept→Concept": [
        RelationshipType.PREREQUISITE_FOR,
        RelationshipType.RELATED_TO,
        RelationshipType.CONTRADICTS,
        RelationshipType.PART_OF,
        RelationshipType.SUPPORTS,
        RelationshipType.ENABLES,
    ],
    # Concept → Entity (inverse patterns)
    "Concept→Entity": [
        RelationshipType.EXEMPLIFIES,  # Concept exemplified by entity
        RelationshipType.IMPLEMENTS,  # Concept implemented by entity (inverse)
    ],
    # Event → Any
    "Event→Person": [
        RelationshipType.INVOLVES,
    ],
    "Event→Entity": [
        RelationshipType.TRIGGERED_BY,
        RelationshipType.RESULTED_IN,
        RelationshipType.INVOLVES,
        RelationshipType.INTRODUCED,
    ],
    "Event→Concept": [
        RelationshipType.DEMONSTRATES,
        RelationshipType.INTRODUCED,
    ],
    "Event→Task": [
        RelationshipType.RESULTED_IN,
        RelationshipType.TRIGGERED_BY,
    ],
}


# Relationship evolution rules: which relationships can evolve into others
EVOLUTION_RULES: Dict[str, List[str]] = {
    # Social relationships can evolve
    RelationshipType.KNOWS: [
        RelationshipType.FRIENDS_WITH,
        RelationshipType.WORKS_WITH,
        RelationshipType.COLLABORATES_WITH,
    ],
    RelationshipType.FRIENDS_WITH: [
        RelationshipType.MARRIED_TO,
        RelationshipType.PARTNERS_WITH,
    ],
    # Work relationships can evolve
    RelationshipType.WORKS_WITH: [
        RelationshipType.COLLABORATES_WITH,
        RelationshipType.REPORTS_TO,
        RelationshipType.MENTORS,
    ],
    RelationshipType.LEARNING: [
        RelationshipType.EXPERT_IN,
    ],
    # Task relationships can evolve
    RelationshipType.RELATED_TO: [
        RelationshipType.DEPENDS_ON,
        RelationshipType.BLOCKS,
        RelationshipType.PREREQUISITE_FOR,
    ],
}


# Bidirectional relationships (automatically create inverse)
BIDIRECTIONAL_TYPES: Set[str] = {
    RelationshipType.WORKS_WITH,
    RelationshipType.COLLABORATES_WITH,
    RelationshipType.FRIENDS_WITH,
    RelationshipType.MARRIED_TO,
    RelationshipType.PARTNERS_WITH,
    RelationshipType.KNOWS,  # Often bidirectional in practice
    RelationshipType.RELATED_TO,
}


# Inverse relationship mappings (for unidirectional relationships)
INVERSE_MAPPINGS: Dict[str, str] = {
    RelationshipType.CREATED_BY: RelationshipType.OWNS,
    RelationshipType.OWNS: RelationshipType.CREATED_BY,
    RelationshipType.MANAGES: "managed_by",
    RelationshipType.REPORTS_TO: "has_report",
    RelationshipType.MENTORS: "mentored_by",
    RelationshipType.TEACHES: RelationshipType.LEARNING,
    RelationshipType.LEARNING: RelationshipType.TEACHES,
    RelationshipType.DEPENDS_ON: "depended_on_by",
    RelationshipType.BLOCKS: "blocked_by",
    RelationshipType.PREREQUISITE_FOR: "has_prerequisite",
    RelationshipType.CONTAINS: RelationshipType.PART_OF,
    RelationshipType.PART_OF: RelationshipType.CONTAINS,
    RelationshipType.IMPLEMENTS: "implemented_by",
    RelationshipType.USES: "used_by",
    RelationshipType.DEMONSTRATES: "demonstrated_by",
}


def get_expected_relationships(source_label: str, target_label: str) -> List[str]:
    """
    Get expected relationship types between two node labels

    Args:
        source_label: Source node label (Person, Task, Entity, Concept, Event)
        target_label: Target node label

    Returns:
        List of expected relationship types for this node combination
    """
    pattern_key = f"{source_label}→{target_label}"
    return COMMON_PATTERNS.get(pattern_key, [])


def can_evolve(current_type: str, new_type: str) -> bool:
    """
    Check if a relationship can evolve from current_type to new_type

    Args:
        current_type: Current relationship type
        new_type: Proposed new relationship type

    Returns:
        True if evolution is allowed, False otherwise
    """
    allowed_evolutions = EVOLUTION_RULES.get(current_type, [])
    return new_type in allowed_evolutions


def is_bidirectional(relationship_type: str) -> bool:
    """
    Check if a relationship type is bidirectional

    Args:
        relationship_type: The relationship type to check

    Returns:
        True if bidirectional, False otherwise
    """
    return relationship_type in BIDIRECTIONAL_TYPES


def get_inverse_type(relationship_type: str) -> str:
    """
    Get the inverse relationship type

    Args:
        relationship_type: The relationship type

    Returns:
        Inverse relationship type, or None if bidirectional
    """
    return INVERSE_MAPPINGS.get(relationship_type)
