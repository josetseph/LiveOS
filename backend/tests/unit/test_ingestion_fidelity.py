from app.workflows.ingestion_fidelity import (
    derive_verbatim_spans_from_contexts,
    filter_verbatim_candidates,
    is_verbatim_span_in_any_context,
)


class TestPerContextVerbatimMatching:
    def test_rejects_stitched_span_across_multiple_contexts(self):
        contexts = [
            "Shirley Temple portrayed Corliss Archer in Kiss and Tell.",
            "She later served as Chief of Protocol of the United States.",
        ]

        assert not is_verbatim_span_in_any_context(
            "Corliss Archer in Kiss and Tell. She later served as Chief of Protocol",
            contexts,
        )

    def test_keeps_only_existing_facts_that_remain_verbatim(self):
        contexts = [
            "Shirley Temple portrayed Corliss Archer in Kiss and Tell.",
            "She later served as Chief of Protocol of the United States.",
        ]
        existing_facts = {
            "Shirley Temple portrayed Corliss Archer in Kiss and Tell.",
            "Shirley Temple was an American diplomat and actress.",
        }

        assert filter_verbatim_candidates(existing_facts, contexts) == [
            "Shirley Temple portrayed Corliss Archer in Kiss and Tell."
        ]


class TestVerbatimFactFallback:
    def test_derives_facts_from_individual_context_spans(self):
        contexts = [
            "Shirley Temple portrayed Corliss Archer in Kiss and Tell. She was a child star.",
            "She later served as Chief of Protocol of the United States.",
        ]

        assert derive_verbatim_spans_from_contexts(contexts) == [
            "Shirley Temple portrayed Corliss Archer in Kiss and Tell.",
            "She was a child star.",
            "She later served as Chief of Protocol of the United States.",
        ]
