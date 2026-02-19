"""
Multi-Hop Query Decomposition Workflow

Handles complex questions that require breaking down into sub-questions,
answering each independently, and synthesizing the final answer.

This workflow significantly improves performance on:
- Comparison questions ("Were X and Y both Z?")
- Multi-hop questions ("What position was held by the person who did X?")
- Chained relationship questions
"""

import time
from app.core.log import get_logger
from app.services.llm import llm_service
from app.services.retrieval import retrieval_service

logger = get_logger("QueryDecomposition")


async def answer_with_decomposition(
    query: str, use_isolated_contexts: bool = True, verbose: bool = False
) -> dict:
    """
    Answer a complex question using query decomposition and multi-step reasoning.

    Flow:
    1. Decompose query into sub-questions
    2. Answer each sub-question independently using retrieval
    3. Synthesize final answer from sub-answers

    Args:
        query: The user's question
        use_isolated_contexts: Whether to use isolated contexts for retrieval
        verbose: Whether to log detailed information

    Returns:
        dict with:
            - answer: str (final answer)
            - decomposition: dict (decomposition details)
            - sub_answers: list (answers to sub-questions)
            - retrieval_docs: list (all retrieved documents)
            - timing: dict (timing information)
    """
    t_start = time.perf_counter()
    logger.info(f"Starting multi-hop query decomposition for: '{query}'")

    # Step 1: Decompose the query
    t_decompose_start = time.perf_counter()
    decomposition = llm_service.decompose_query(query)
    t_decompose = time.perf_counter() - t_decompose_start

    if verbose:
        logger.info(f"  [Decomposition] Type: {decomposition['question_type']}")
        logger.info(
            f"  [Decomposition] Requires Multi-Hop: {decomposition['requires_decomposition']}"
        )
        if decomposition["sub_questions"]:
            for i, sub_q in enumerate(decomposition["sub_questions"], 1):
                logger.info(f"  [Decomposition] Sub-Q{i}: {sub_q['text']}")

    # If no decomposition needed, fall back to regular retrieval
    if not decomposition["requires_decomposition"]:
        logger.info("  [Decomposition] Single-hop question - using standard retrieval")
        return await _answer_single_hop(query, use_isolated_contexts, t_start)

    # Step 2: Answer each sub-question independently
    t_sub_answers_start = time.perf_counter()
    sub_answers = []
    all_retrieval_docs = []

    for i, sub_q in enumerate(decomposition["sub_questions"], 1):
        sub_question = sub_q["text"]
        logger.info(f"  [Sub-Question {i}] Answering: '{sub_question}'")

        # Retrieve relevant context for this sub-question
        t_retrieval_start = time.perf_counter()
        retrieved_docs = await retrieval_service.hybrid_search(
            sub_question, top_k=12  # Smaller top_k for sub-questions
        )
        t_retrieval = time.perf_counter() - t_retrieval_start

        if verbose:
            logger.info(
                f"    Retrieved {len(retrieved_docs)} documents in {t_retrieval:.2f}s"
            )

        # Generate answer for this sub-question
        t_gen_start = time.perf_counter()
        sub_answer = llm_service.generate_answer(
            question=sub_question,
            context_docs=retrieved_docs,
            max_length=100,  # Short answers for sub-questions
        )
        t_gen = time.perf_counter() - t_gen_start

        if verbose:
            logger.info(f"    Answer: '{sub_answer}' (generated in {t_gen:.2f}s)")

        sub_answers.append(
            {
                "question": sub_question,
                "answer": sub_answer,
                "num_docs": len(retrieved_docs),
                "retrieval_time": t_retrieval,
                "generation_time": t_gen,
            }
        )

        all_retrieval_docs.extend(retrieved_docs)

    t_sub_answers = time.perf_counter() - t_sub_answers_start

    # Step 3: Synthesize final answer from sub-answers
    t_synthesis_start = time.perf_counter()
    final_answer = llm_service.synthesize_multi_hop_answer(
        original_question=query,
        sub_answers=sub_answers,
        synthesis_strategy=decomposition["synthesis_strategy"],
    )
    t_synthesis = time.perf_counter() - t_synthesis_start

    t_total = time.perf_counter() - t_start

    logger.info(f"  [Multi-Hop] Final Answer: '{final_answer}'")
    logger.info(
        f"  [Multi-Hop] Total Time: {t_total:.2f}s "
        f"(decompose: {t_decompose:.2f}s, sub-answers: {t_sub_answers:.2f}s, "
        f"synthesis: {t_synthesis:.2f}s)"
    )

    return {
        "answer": final_answer,
        "decomposition": decomposition,
        "sub_answers": sub_answers,
        "retrieval_docs": all_retrieval_docs,
        "timing": {
            "total": t_total,
            "decomposition": t_decompose,
            "sub_answers": t_sub_answers,
            "synthesis": t_synthesis,
        },
    }


async def _answer_single_hop(
    query: str, use_isolated_contexts: bool, t_start: float
) -> dict:
    """
    Answer a single-hop question using standard retrieval (no decomposition).

    Args:
        query: The user's question
        use_isolated_contexts: Whether to use isolated contexts
        t_start: Start time for timing

    Returns:
        dict with answer and metadata
    """
    # Retrieve relevant context
    t_retrieval_start = time.perf_counter()
    retrieved_docs = await retrieval_service.hybrid_search(query, top_k=20)
    t_retrieval = time.perf_counter() - t_retrieval_start

    # Generate answer
    t_gen_start = time.perf_counter()
    answer = llm_service.generate_answer(question=query, context_docs=retrieved_docs)
    t_gen = time.perf_counter() - t_gen_start

    t_total = time.perf_counter() - t_start

    return {
        "answer": answer,
        "decomposition": {
            "requires_decomposition": False,
            "question_type": "single_hop",
        },
        "sub_answers": [],
        "retrieval_docs": retrieved_docs,
        "timing": {"total": t_total, "retrieval": t_retrieval, "generation": t_gen},
    }


def should_use_decomposition(query: str) -> bool:
    """
    Quick check if a query might benefit from decomposition.

    This is a fast heuristic check before running full decomposition.
    Checks for comparison keywords and multi-hop patterns.

    Args:
        query: The user's question

    Returns:
        bool indicating if decomposition should be attempted
    """
    query_lower = query.lower()

    # Comparison indicators
    comparison_keywords = [
        "same",
        "both",
        "either",
        "neither",
        "compare",
        "similar",
        "different",
        "versus",
        "vs",
        "between",
    ]

    # Multi-hop indicators
    multihop_keywords = [
        "who portrayed",
        "who played",
        "who directed",
        "the person who",
        "the woman who",
        "the man who",
        "the actor who",
        "the actress who",
        "the director who",
        "the author of",
        "the creator of",
        "the founder of",
    ]

    # Check for comparison patterns
    has_comparison = any(kw in query_lower for kw in comparison_keywords)

    # Check for multi-hop patterns
    has_multihop = any(kw in query_lower for kw in multihop_keywords)

    # Check for multiple named entities (suggests comparison)
    # This is a rough heuristic - proper extraction happens in decompose_query
    words = query.split()
    capitalized_sequences = 0
    in_sequence = False
    for word in words:
        if word and word[0].isupper():
            if not in_sequence:
                capitalized_sequences += 1
                in_sequence = True
        else:
            in_sequence = False

    has_multiple_entities = capitalized_sequences >= 2

    return (has_comparison and has_multiple_entities) or has_multihop


# Export main functions
__all__ = ["answer_with_decomposition", "should_use_decomposition"]
