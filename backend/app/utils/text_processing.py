import re

# NOTE: Entity context isolation is now handled by the LLM during extraction.
# The LLM provides an `isolated_context` field for each entity/concept.
# This function is kept as a fallback for edge cases where isolated_context is empty.


def get_entity_context(
    text: str,
    entity_name: str,
    other_entities: list[str] | None = None,
    window: int = 2,
) -> str:
    """
    FALLBACK ONLY: Extracts paragraphs containing the entity_name.

    Primary isolation should come from the LLM's `isolated_context` field.
    This function is only called when isolated_context is empty/missing.

    Args:
        text: The full note text
        entity_name: The entity we're extracting context for
        other_entities: Unused (kept for backward compatibility)
        window: Unused (kept for backward compatibility)
    """
    # Split by paragraph
    paragraphs = re.split(r"\n\s*\n", text.strip())

    entity_lower = entity_name.lower()

    # Include any paragraph that mentions the entity
    relevant = [p.strip() for p in paragraphs if entity_lower in p.lower()]

    if not relevant:
        # Entity not found - return full text for LLM to handle
        return text

    return "\n\n".join(relevant)
