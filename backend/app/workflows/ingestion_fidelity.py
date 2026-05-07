import re


def normalize_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def is_verbatim_span_in_any_context(candidate: str, contexts: list[str]) -> bool:
    candidate_norm = normalize_whitespace(candidate)
    if not candidate_norm:
        return False
    return any(
        candidate_norm in normalize_whitespace(context)
        for context in contexts
        if context and context.strip()
    )


def filter_verbatim_candidates(
    candidates: list[str] | set[str], contexts: list[str]
) -> list[str]:
    filtered: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_text = str(candidate).strip()
        candidate_key = normalize_whitespace(candidate_text).lower()
        if not candidate_key or candidate_key in seen:
            continue
        if not is_verbatim_span_in_any_context(candidate_text, contexts):
            continue
        seen.add(candidate_key)
        filtered.append(candidate_text)
    return filtered


def derive_verbatim_spans_from_contexts(contexts: list[str]) -> list[str]:
    spans: list[str] = []
    seen: set[str] = set()
    for context in contexts:
        for part in re.split(r"(?<=[.!?])\s+|\n+", context or ""):
            span = part.strip()
            key = normalize_whitespace(span).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            spans.append(span)
    return spans


def fallback_description_from_contexts(contexts: list[str], name: str) -> str:
    verbatim_contexts = [
        context.strip() for context in contexts if context and context.strip()
    ]
    if verbatim_contexts:
        return max(
            verbatim_contexts, key=lambda context: len(normalize_whitespace(context))
        )
    return f"Information about {name}."
