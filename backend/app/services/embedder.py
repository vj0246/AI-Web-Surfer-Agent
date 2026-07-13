import ollama

from app.core.config import settings


async def embed(text: str) -> list[float]:
    """Embed text using nomic-embed-text running in Ollama."""
    client = ollama.AsyncClient(host=settings.ollama_host)
    response = await client.embeddings(model=settings.embed_model, prompt=text)
    return response["embedding"]
