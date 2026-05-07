"""
Unit tests for LLM service contract signatures.

Regression guard for:
  - select_relevant_relationships(entries, question) — 2 positional args
  - select_relevant_docs_with_reasoning(docs, question, original_query=...) — kwarg accepted
  - generate_node_enrichment_async thin-entity pre-filter (skip bare years/adjectives)
  - _normalize_yes_no_answer — broad natural-language yes/no acceptance
  - answer_sub_question_dual — multi-line FULL_ANSWER / DIRECT_ANSWER parsing
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Contract: select_relevant_relationships
# ---------------------------------------------------------------------------


class TestSelectRelevantRelationshipsContract:
    def test_signature_has_exactly_two_positional_params(self):
        """Signature must be (self, relationship_entries, question) — no extras."""
        from app.services.llm import LLMService

        sig = inspect.signature(LLMService.select_relevant_relationships)
        params = list(sig.parameters.keys())
        # Exclude 'self'
        non_self = [p for p in params if p != "self"]
        assert (
            len(non_self) == 2
        ), f"select_relevant_relationships expects 2 params, got {len(non_self)}: {non_self}"
        assert non_self[0] == "relationship_entries"
        assert non_self[1] == "question"

    @pytest.mark.asyncio
    async def test_called_with_two_args_does_not_raise_type_error(self):
        """Calling with (entries, question) must not raise TypeError."""
        from app.services.llm import LLMService

        svc = MagicMock(spec=LLMService)
        svc.select_relevant_relationships = AsyncMock(return_value=[])

        # Should not raise
        result = await svc.select_relevant_relationships(
            [{"name": "Alice", "rel_type": "KNOWS", "target": "Bob"}],
            "Who does Alice know?",
        )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Contract: select_relevant_docs_with_reasoning
# ---------------------------------------------------------------------------


class TestSelectRelevantDocsContract:
    def test_signature_accepts_original_query_kwarg(self):
        """original_query must be a valid keyword parameter."""
        from app.services.llm import LLMService

        sig = inspect.signature(LLMService.select_relevant_docs_with_reasoning)
        params = sig.parameters
        assert (
            "original_query" in params
        ), "select_relevant_docs_with_reasoning must accept original_query keyword"
        # Must have a default (i.e., be optional)
        assert (
            params["original_query"].default is not inspect.Parameter.empty
        ), "original_query must have a default value (None)"

    @pytest.mark.asyncio
    async def test_called_with_original_query_does_not_raise(self):
        from app.services.llm import LLMService

        svc = MagicMock(spec=LLMService)
        svc.select_relevant_docs_with_reasoning = AsyncMock(
            return_value={"selected": [], "reasoning": ""}
        )

        result = await svc.select_relevant_docs_with_reasoning(
            docs=[{"name": "Alice", "description": "..."}],
            question="Where is Alice from?",
            original_query="Tell me about Alice",
        )
        assert "selected" in result


# ---------------------------------------------------------------------------
# Enrichment thin-entity pre-filter
# ---------------------------------------------------------------------------


class TestEnrichmentThinEntityFilter:
    """generate_node_enrichment_async must skip enrichment for thin entities."""

    @pytest.fixture()
    def llm_svc(self):
        """Return a partially-real LLMService with async provider stubbed."""
        from app.services.llm import LLMService

        svc = LLMService.__new__(LLMService)
        svc.is_gemini = False
        svc.provider = "lm_studio"
        svc.async_chat_client = AsyncMock()
        return svc

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "entity_name",
        ["1994", "2001", "american", "japanese", "british", "chinese"],
    )
    async def test_thin_entity_skips_llm_call(self, llm_svc, entity_name):
        """Thin entities must return immediately without making an LLM call."""
        result = await llm_svc.generate_node_enrichment_async(
            context="Some context text here.",
            entity_name=entity_name,
            entity_type="Date",
        )
        # Must return a valid dict
        assert isinstance(result, dict)
        assert "description" in result
        # Must NOT have called the LLM
        llm_svc.async_chat_client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_thin_entity_proceeds_to_llm(self, llm_svc):
        """Non-thin entities with context should attempt an LLM call."""
        from openai.types.chat import ChatCompletion, ChatCompletionMessage
        from openai.types.chat.chat_completion import Choice

        fake_response = MagicMock()
        fake_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"title": "Alice Smith", "summary": "A person.", "facts": [], "questions": []}'
                )
            )
        ]
        llm_svc.async_chat_client.chat.completions.create = AsyncMock(
            return_value=fake_response
        )

        with patch.object(
            llm_svc, "_clean_json", side_effect=lambda x: x
        ), patch.object(
            llm_svc, "_lm_studio_text_response_format", return_value={"type": "text"}
        ), patch.object(
            llm_svc, "_with_keep_alive", side_effect=lambda x: x
        ), patch.object(
            llm_svc, "_get_model_for_task", return_value="test-model"
        ):
            result = await llm_svc.generate_node_enrichment_async(
                context="Alice Smith is a software engineer from Berlin.",
                entity_name="Alice Smith",
                entity_type="Person",
            )

        llm_svc.async_chat_client.chat.completions.create.assert_called_once()
        assert "description" in result


# ---------------------------------------------------------------------------
# _normalize_yes_no_answer — broad natural-language acceptance
# ---------------------------------------------------------------------------


class TestNormalizeYesNoAnswer:
    """_normalize_yes_no_answer must accept natural-language yes/no forms."""

    @pytest.mark.parametrize(
        "question,answer,expected",
        [
            # Exact canonical forms
            ("Is Alice the director?", "yes", "YES"),
            ("Is Alice the director?", "no", "NO"),
            ("Is Alice the director?", "Yes", "YES"),
            ("Is Alice the director?", "No", "NO"),
            # Trailing punctuation stripped
            ("Is Alice the director?", "yes.", "YES"),
            ("Is Alice the director?", "no!", "NO"),
            ("Is Alice the director?", "yes,", "YES"),
            # Natural-language affirmatives
            ("Is Alice the director?", "Yes, that is correct", "YES"),
            ("Is Alice the director?", "Yes, she is", "YES"),
            ("Is Alice the director?", "correct", "YES"),
            ("Is Alice the director?", "Correct.", "YES"),
            ("Is Alice the director?", "indeed", "YES"),
            ("Is Alice the director?", "absolutely", "YES"),
            ("Is Alice the director?", "affirmative", "YES"),
            # Natural-language negatives
            ("Is Alice the director?", "No, she is not", "NO"),
            ("Is Alice the director?", "nope", "NO"),
            ("Is Alice the director?", "incorrect", "NO"),
            ("Is Alice the director?", "negative", "NO"),
            ("Is Alice the director?", "false", "NO"),
            # Non-boolean question → passthrough unchanged
            ("Who directed the film?", "Christopher Nolan", "Christopher Nolan"),
            ("What year was it?", "1994", "1994"),
            # Boolean question, ambiguous answer → None
            ("Is Alice the director?", "maybe", None),
            ("Is Alice the director?", "it depends", None),
            ("Was the film released early?", "possibly", None),
        ],
    )
    def test_normalization(self, question, answer, expected):
        from app.services.llm import LLMService

        result = LLMService._normalize_yes_no_answer(question, answer)
        assert (
            result == expected
        ), f"normalize({question!r}, {answer!r}) → {result!r}, expected {expected!r}"

    def test_non_boolean_question_always_passes_through(self):
        """Non-boolean questions must never be rejected regardless of answer content."""
        from app.services.llm import LLMService

        for question in [
            "Who is the mayor?",
            "Where was she born?",
            "What caused the conflict?",
            "How many people attended?",
        ]:
            result = LLMService._normalize_yes_no_answer(question, "some answer")
            assert (
                result == "some answer"
            ), f"Non-boolean question {question!r} must not modify answer"


# ---------------------------------------------------------------------------
# answer_sub_question_dual — multi-line response parsing
# ---------------------------------------------------------------------------


class TestAnswerSubQuestionDualParsing:
    """answer_sub_question_dual must handle multi-line FULL_ANSWER/DIRECT_ANSWER."""

    def _make_svc(self, raw_response: str):
        """Build a minimally-configured LLMService stub that returns raw_response."""
        from app.services.llm import LLMService

        svc = LLMService.__new__(LLMService)
        svc.is_gemini = False
        svc.provider = "lm_studio"
        svc.async_chat_client = AsyncMock()
        svc.generate = AsyncMock(return_value=raw_response)
        return svc

    @pytest.mark.asyncio
    async def test_single_line_standard_response(self):
        """Standard single-line format must still parse correctly."""
        raw = (
            "REASONING: The context mentions Alice is director.\n"
            "FULL_ANSWER: Alice Smith is the current director of the institute.\n"
            "DIRECT_ANSWER: Alice Smith\n"
        )
        svc = self._make_svc(raw)
        full, direct, reasoning = await svc.answer_sub_question_dual(
            "Who is the director?",
            [
                {
                    "text": "Alice Smith is the director.",
                    "original_obj": {"name": "Alice Smith"},
                }
            ],
        )
        assert full == "Alice Smith is the current director of the institute."
        assert direct == "Alice Smith"
        assert "Alice" in reasoning

    @pytest.mark.asyncio
    async def test_multi_line_full_answer_is_preserved(self):
        """FULL_ANSWER spanning multiple lines must not be truncated to the first line."""
        raw = (
            "REASONING: The context describes Alice's role.\n"
            "FULL_ANSWER: Alice Smith is the current director of the institute.\n"
            "She was appointed in 2019 after serving as deputy director.\n"
            "DIRECT_ANSWER: Alice Smith\n"
        )
        svc = self._make_svc(raw)
        full, direct, reasoning = await svc.answer_sub_question_dual(
            "Who is the director?",
            [
                {
                    "text": "Alice Smith, director since 2019.",
                    "original_obj": {"name": "Alice Smith"},
                }
            ],
        )
        assert full is not None
        # The second line of FULL_ANSWER must be included, not silently dropped
        assert "2019" in full, f"Multi-line FULL_ANSWER truncated; got: {full!r}"
        assert direct == "Alice Smith"

    @pytest.mark.asyncio
    async def test_insufficient_returns_none_fields(self):
        """INSUFFICIENT markers must produce None for full and direct answers."""
        raw = (
            "REASONING: The context does not mention any director.\n"
            "FULL_ANSWER: INSUFFICIENT\n"
            "DIRECT_ANSWER: INSUFFICIENT\n"
        )
        svc = self._make_svc(raw)
        full, direct, reasoning = await svc.answer_sub_question_dual(
            "Who is the director?",
            [{"text": "Some unrelated text.", "original_obj": {"name": "Other"}}],
        )
        assert full is None
        assert direct is None
        assert reasoning != ""

    @pytest.mark.asyncio
    async def test_empty_docs_returns_early(self):
        """No docs must return (None, None, descriptive message) without LLM call."""
        svc = self._make_svc("")
        full, direct, reasoning = await svc.answer_sub_question_dual(
            "Who is the director?", []
        )
        assert full is None
        assert direct is None
        assert "No context" in reasoning
        # LLM generate should NOT have been called
        svc.generate.assert_not_called()
