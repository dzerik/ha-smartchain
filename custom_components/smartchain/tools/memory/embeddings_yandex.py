"""Yandex embeddings over REST, without the SDK's protobuf dependency."""

import httpx

from ...const import MEMORY_EMBED_TIMEOUT_SECONDS

EMBEDDINGS_URL = "https://ai.api.cloud.yandex.net/foundationModels/v1/textEmbedding"


class YandexEmbeddingsAdapter:
    """Synchronous wrapper exposing `embed_query` / `embed_documents`."""

    def __init__(self, api_key: str, model: str, folder_id: str = "") -> None:
        self._api_key = api_key
        model = model or "text-search-doc"
        self._model_uri = model if "://" in model else f"emb://{folder_id}/{model}/latest"

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(
            headers={"Authorization": f"Api-Key {self._api_key}"},
            timeout=MEMORY_EMBED_TIMEOUT_SECONDS,
        ) as client:
            embeddings = []
            for text in texts:
                response = client.post(
                    EMBEDDINGS_URL, json={"modelUri": self._model_uri, "text": text}
                )
                response.raise_for_status()
                embeddings.append([float(value) for value in response.json()["embedding"]])
            return embeddings
