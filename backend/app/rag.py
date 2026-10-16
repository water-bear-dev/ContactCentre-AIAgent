import hashlib
from pathlib import Path

import chromadb
import httpx


class AssistantUnavailableError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, chat_model: str, embedding_model: str):
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embedding_model = embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.embedding_model, "input": texts},
                )
                response.raise_for_status()
                return response.json()["embeddings"]
        except (httpx.HTTPError, KeyError) as exc:
            raise AssistantUnavailableError("Ollama embedding service is unavailable. Start Ollama and pull nomic-embed-text.") from exc

    async def coach(self, transcript: str, sources: list[dict[str, str]]) -> str:
        context = "\n\n".join(f"[{source['source']}] {source['text']}" for source in sources)
        prompt = (
            "You are a concise contact-centre coach. Use only the playbook excerpts below. "
            "Suggest the next thing the agent should say in one or two sentences. "
            "If the excerpts do not support an answer, say what the agent should clarify.\n\n"
            f"Customer/agent transcript:\n{transcript}\n\nPlaybook excerpts:\n{context}"
        )
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={"model": self.chat_model, "stream": False, "messages": [{"role": "user", "content": prompt}]},
                )
                response.raise_for_status()
                return response.json()["message"]["content"].strip()
        except (httpx.HTTPError, KeyError) as exc:
            raise AssistantUnavailableError("Ollama chat service is unavailable. Start Ollama and pull llama3.2:3b.") from exc


class KnowledgeBase:
    def __init__(self, persist_path: Path, ollama: OllamaClient):
        self._client = chromadb.PersistentClient(path=str(persist_path))
        self._collection = self._client.get_or_create_collection(name="contact_centre_playbook", metadata={"hnsw:space": "cosine"})
        self._ollama = ollama

    async def index_directory(self, directory: Path) -> int:
        paths = sorted(path for path in directory.glob("**/*") if path.suffix.lower() in {".md", ".txt"})
        if not paths:
            return 0
        documents: list[str] = []
        ids: list[str] = []
        metadata: list[dict[str, str]] = []
        for path in paths:
            for index, chunk in enumerate(self._chunks(path.read_text(encoding="utf-8"))):
                documents.append(chunk)
                ids.append(hashlib.sha256(f"{path}:{index}:{chunk}".encode()).hexdigest())
                metadata.append({"source": path.name})
        embeddings = await self._ollama.embed(documents)
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadata, embeddings=embeddings)
        return len(documents)

    async def search(self, query: str, count: int = 3) -> list[dict[str, str]]:
        if not query.strip():
            return []
        embeddings = await self._ollama.embed([query])
        result = self._collection.query(query_embeddings=embeddings, n_results=min(count, max(self._collection.count(), 1)), include=["documents", "metadatas"])
        documents = result.get("documents", [[]])[0] or []
        metadatas = result.get("metadatas", [[]])[0] or []
        return [{"text": text, "source": data.get("source", "playbook")} for text, data in zip(documents, metadatas)]

    @staticmethod
    def _chunks(text: str, size: int = 700) -> list[str]:
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 2 > size:
                chunks.append(current)
                current = paragraph
            else:
                current = f"{current}\n\n{paragraph}".strip()
        if current:
            chunks.append(current)
        return chunks


class Coach:
    def __init__(self, knowledge_base: KnowledgeBase, ollama: OllamaClient):
        self._knowledge_base = knowledge_base
        self._ollama = ollama

    async def suggest(self, transcript: str) -> dict[str, object]:
        sources = await self._knowledge_base.search(transcript)
        if not sources:
            return {"text": "Could you clarify the customer’s goal before choosing the next action?", "sources": []}
        return {"text": await self._ollama.coach(transcript, sources), "sources": sources}

