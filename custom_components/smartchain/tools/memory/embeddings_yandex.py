"""Thin adapter mapping Yandex Foundation Models embeddings to the LangChain shape."""

from typing import Any


class YandexEmbeddingsAdapter:
    """Synchronous wrapper exposing `embed_query` / `embed_documents`."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model or "general"
        self._client = self._build_client()

    def _build_client(self) -> Any:
        from yandex_cloud_ml_sdk import YCloudML  # type: ignore[import-not-found]

        return YCloudML(folder_id="", auth=self._api_key)

    def embed_query(self, text: str) -> list[float]:
        result = self._client.models.text_embeddings(self._model).run(text)
        return list(result.embedding)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]
