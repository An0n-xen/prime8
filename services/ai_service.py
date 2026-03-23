"""AI layer: embeddings, ChromaDB vector store, and HF Inference summaries."""

from __future__ import annotations

import asyncio

import chromadb
from sentence_transformers import SentenceTransformer

from config import settings as config
from utils.logger import get_logger

logger = get_logger(__name__)

EMBEDDING_MODEL = "intfloat/e5-small-v2"
QUERY_PREFIX = "query: "


class AIService:
    def __init__(self):
        self._embed_model: SentenceTransformer | None = None
        self._chroma_client: chromadb.PersistentClient | None = None
        self._collection: chromadb.Collection | None = None
        self._available = False

    async def initialize(self):
        try:
            logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
            self._embed_model = await asyncio.to_thread(
                SentenceTransformer, EMBEDDING_MODEL
            )
            self._chroma_client = chromadb.PersistentClient(path="./data/chroma_db")
            self._collection = self._chroma_client.get_or_create_collection(
                name="github_repos",
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
            logger.info("AI service initialized (embedding model + ChromaDB)")
        except Exception as e:
            logger.warning(f"AI service unavailable: {e}")
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def embed_document(self, text: str) -> list[float]:
        """Embed a document with passage prefix (e5 format)."""
        embedding = await asyncio.to_thread(self._embed_model.encode, f"passage: {text}")
        return embedding.tolist()

    async def embed_query(self, text: str) -> list[float]:
        """Embed a query (with prefix for asymmetric retrieval)."""
        embedding = await asyncio.to_thread(
            self._embed_model.encode, f"{QUERY_PREFIX}{text}"
        )
        return embedding.tolist()

    async def index_repo(
        self,
        repo_name: str,
        description: str,
        readme: str = "",
        stars: int = 0,
        language: str = "",
        topics: str = "",
        health_score: int = 0,
    ):
        if not self.available:
            return

        doc_text = f"{description or ''}\n\n{readme or ''}"
        doc_text = doc_text[:2000]  # e5-small-v2 has ~512 token context

        embedding = await self.embed_document(doc_text)

        metadata = {
            "stars": stars,
            "language": language or "unknown",
            "topics": topics,
            "health_score": health_score,
        }

        await asyncio.to_thread(
            self._collection.upsert,
            ids=[repo_name],
            embeddings=[embedding],
            documents=[doc_text[:5000]],
            metadatas=[metadata],
        )

    async def search(
        self,
        query: str,
        n_results: int = 10,
        language: str | None = None,
    ) -> list[dict]:
        if not self.available:
            return []

        embedding = await self.embed_query(query)

        where = {"language": language} if language else None

        results = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=[embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        repos = []
        if results and results["ids"]:
            for i, repo_id in enumerate(results["ids"][0]):
                repos.append({
                    "repo_name": repo_id,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "similarity": 1 - results["distances"][0][i] if results["distances"] else 0,
                })
        return repos

    async def generate_summary(self, text: str, max_length: int = 200) -> str | None:
        """Generate a summary using HF Inference API."""
        if not config.HF_API_TOKEN:
            return None

        try:
            from huggingface_hub import AsyncInferenceClient

            client = AsyncInferenceClient(token=config.HF_API_TOKEN)
            result = await client.text_generation(
                prompt=f"Summarize the following GitHub trending data concisely:\n\n{text}\n\nSummary:",
                model="mistralai/Mistral-7B-Instruct-v0.3",
                max_new_tokens=max_length,
            )
            return result.strip() if isinstance(result, str) else str(result).strip()
        except Exception as e:
            logger.warning(f"HF summary generation failed: {e}")
            return None

    async def close(self):
        self._embed_model = None
        self._collection = None
        self._chroma_client = None


# Module-level singleton
ai_service = AIService()
