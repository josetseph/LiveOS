"""
Reranking service using HuggingFace cross-encoder model.
Used for semantic refinement of retrieval candidates.
"""

from typing import List, Tuple, Optional
import logging
from sentence_transformers import CrossEncoder
from app.core.config import settings

logger = logging.getLogger(__name__)


class RerankService:
    def __init__(self):
        """
        Initialize the reranker with a cross-encoder model.
        Uses local model path if available, otherwise downloads from HuggingFace.
        """
        try:
            # Try loading from local models directory first
            model_path = f"models/{settings.MODEL_RERANKING_LOCAL}"
            logger.info(f"Loading reranker from local path: {model_path}")
            self.model = CrossEncoder(model_path)
            logger.info(f"✅ Reranker loaded successfully from local: {model_path}")
        except Exception as e:
            # Fallback to HuggingFace download
            logger.warning(f"Local model not found ({e}), downloading from HuggingFace...")
            try:
                self.model = CrossEncoder(settings.MODEL_RERANKER_HF)
                logger.info(f"✅ Reranker loaded from HuggingFace: {settings.MODEL_RERANKER_HF}")
            except Exception as e2:
                logger.error(f"❌ Failed to load reranker: {e2}")
                raise

    def rerank(
        self, 
        query: str, 
        documents: List[str], 
        top_k: Optional[int] = None
    ) -> List[Tuple[int, float]]:
        """
        Rerank documents based on relevance to query.
        
        Args:
            query: The search query
            documents: List of document texts to rerank
            top_k: Return only top K results (optional)
            
        Returns:
            List of (index, score) tuples sorted by relevance (highest first)
        """
        if not documents:
            return []
        
        # Create query-document pairs
        pairs = [[query, doc] for doc in documents]
        
        # Get relevance scores from cross-encoder
        scores = self.model.predict(pairs)
        
        # Create (index, score) tuples and sort by score
        ranked = [(i, float(score)) for i, score in enumerate(scores)]
        ranked.sort(key=lambda x: x[1], reverse=True)
        
        # Return top_k if specified
        if top_k:
            ranked = ranked[:top_k]
            
        return ranked

    def get_scores(self, query: str, documents: List[str]) -> List[float]:
        """
        Get relevance scores for documents without reordering.
        
        Args:
            query: The search query
            documents: List of document texts to score
            
        Returns:
            List of scores in same order as input documents
        """
        if not documents:
            return []
        
        pairs = [[query, doc] for doc in documents]
        scores = self.model.predict(pairs)
        
        return [float(score) for score in scores]


# Singleton instance
rerank_service = RerankService()
