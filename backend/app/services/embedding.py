from langchain_ollama import OllamaEmbeddings
from app.core.config import settings


class EmbeddingService:
    def __init__(self):
        # Option A: Use Ollama but keep it loaded (Safe for 16GB RAM)
        # keep_alive=-1 tells Ollama to never unload this model from VRAM
        self.embeddings = OllamaEmbeddings(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.MODEL_EMBEDDING,
            keep_alive="-1",
        )

    def embed_query(self, text: str) -> list[float]:
        return self.embeddings.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embeddings.embed_documents(texts)

    def get_dimension(self) -> int:
        """
        Returns the dimension of the embedding model.
        """
        # Cache this?
        dummy_vec = self.embed_query("test")
        return len(dummy_vec)


embedding_service = EmbeddingService()
