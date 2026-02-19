from langchain_ollama import OllamaEmbeddings
from app.core.config import settings


def compute_cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine similarity score (0 to 1)
    """
    import math

    # Dot product
    dot_product = sum(a * b for a, b in zip(vec1, vec2))

    # Magnitudes
    mag1 = math.sqrt(sum(a * a for a in vec1))
    mag2 = math.sqrt(sum(b * b for b in vec2))

    # Avoid division by zero
    if mag1 == 0 or mag2 == 0:
        return 0.0

    return dot_product / (mag1 * mag2)


class EmbeddingService:
    def __init__(self):
        # Option A: Use Ollama but keep it loaded (Safe for 16GB RAM)
        # keep_alive=-1 tells Ollama to never unload this model from VRAM
        self.embeddings = OllamaEmbeddings(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.MODEL_EMBEDDING,
            keep_alive="-1",
        )
        
        # Qwen3-Embedding instruction prefix for QUERIES (not documents)
        # This is CRITICAL for Qwen3 series - without it, performance drops significantly
        # Tailored for Personal Knowledge Management (PKM) retrieval
        self.query_instruction = "Instruct: Given a question about personal knowledge, notes, or experiences, retrieve relevant information from the knowledge base that helps answer the question\nQuery: "
        
        # Check if current model is Qwen3 to apply instruction
        self.is_qwen3 = "qwen3" in settings.MODEL_EMBEDDING.lower()

    def embed_query(self, text: str, custom_instruction: str = None) -> list[float]:
        """
        Embed a search query with instruction prefix for Qwen3 models.
        
        For Qwen3-Embedding models, prepends instruction to align query representation
        with passage representation space. This is the "Instruction Paradox" fix.
        
        Args:
            text: The query text to embed
            custom_instruction: Optional LLM-generated instruction (overrides default)
        """
        if self.is_qwen3:
            instruction = custom_instruction if custom_instruction else self.query_instruction
            prefixed_text = instruction + text
            return self.embeddings.embed_query(prefixed_text)
        return self.embeddings.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed documents/passages WITHOUT instruction prefix.
        
        Only queries get the instruction prefix, not the documents being indexed.
        """
        return self.embeddings.embed_documents(texts)

    def get_dimension(self) -> int:
        """
        Returns the dimension of the embedding model.
        Note: Uses embed_documents (not embed_query) to avoid instruction prefix in dimension test.
        """
        dummy_vec = self.embeddings.embed_documents(["test"])[0]
        return len(dummy_vec)


embedding_service = EmbeddingService()
