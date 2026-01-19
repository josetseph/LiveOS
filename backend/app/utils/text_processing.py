import re


def get_entity_context(text: str, entity_name: str, window: int = 1) -> str:
    """
    Extracts sentences containing the entity_name + surrounding window.
    """
    # Simple sentence splitting by punctuation
    sentences = re.split(r"(?<=[.!?])\s+", text)

    # Identify indices
    relevant_indices = [
        i for i, s in enumerate(sentences) if entity_name.lower() in s.lower()
    ]

    if not relevant_indices:
        # Fallback: If entity not found (e.g. slight mismatch), return full text
        # Or maybe return nothing? Better to return full text to be safe,
        # but the request was "Context Windowing".
        # Let's try to match by parts?
        # For now, return empty string if not found to avoid noise?
        # No, if not found, it implies the Extraction phase found it but Exact match failed.
        # Let's return the whole text as fallback, but rely on the LLM Prompt to filter.
        return text

    context = []
    for idx in relevant_indices:
        start = max(0, idx - window)
        end = min(len(sentences), idx + window + 1)
        context.extend(sentences[start:end])

    # Deduplicate and join
    unique_sentences = list(dict.fromkeys(context))
    return " ".join(unique_sentences)
