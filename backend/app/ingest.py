import asyncio
from .config import settings
from .rag import KnowledgeBase, OllamaClient


async def main() -> None:
    ollama = OllamaClient(settings.ollama_url, settings.ollama_chat_model, settings.ollama_embedding_model)
    knowledge = KnowledgeBase(settings.chroma_path, ollama)
    count = await knowledge.index_directory(settings.knowledge_path)
    print(f"Indexed {count} knowledge chunks")


if __name__ == "__main__":
    asyncio.run(main())

