"""Yandex embeddings work without the SDK that conflicts with HA's protobuf."""

import json
from unittest.mock import patch

import httpx
import pytest

from custom_components.smartchain.tools.memory.embeddings_yandex import YandexEmbeddingsAdapter


@pytest.fixture
def rest_client():
    """Exercise real HTTP serialization without opening a network connection."""
    requests = []
    clients = []
    responses = []
    original_client = httpx.Client

    def respond(request):
        requests.append(request)
        return (
            responses.pop(0)
            if responses
            else httpx.Response(200, json={"embedding": ["0.25", "-0.5"]})
        )

    def build_client(**kwargs):
        client = original_client(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    with patch("httpx.Client", side_effect=build_client):
        yield requests, clients, responses


@pytest.mark.parametrize(
    ("model", "uri"),
    [
        ("text-search-doc", "emb://folder/text-search-doc/latest"),
        ("text-search-query", "emb://folder/text-search-query/latest"),
        ("emb://other/text-search-doc/1", "emb://other/text-search-doc/1"),
        ("gpt://other/text-embeddings/latest@tuned", "gpt://other/text-embeddings/latest@tuned"),
    ],
)
def test_query_uses_rest_without_yandex_sdk(rest_client, model, uri):
    requests, clients, _ = rest_client
    with patch.dict("sys.modules", {"yandex_cloud_ml_sdk": None}):
        adapter = YandexEmbeddingsAdapter(api_key="test-key", model=model, folder_id="folder")
        assert adapter.embed_query("hello") == [0.25, -0.5]

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://ai.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
    assert request.headers["authorization"] == "Api-Key test-key"
    assert json.loads(request.content) == {"modelUri": uri, "text": "hello"}
    assert clients[0].is_closed
    assert clients[0].timeout.read == 30


def test_documents_preserve_order_and_close_the_client(rest_client):
    requests, clients, responses = rest_client
    responses.extend(
        [
            httpx.Response(200, json={"embedding": ["1"]}),
            httpx.Response(200, json={"embedding": ["2"]}),
        ]
    )
    adapter = YandexEmbeddingsAdapter(
        api_key="test-key", model="text-search-doc", folder_id="folder"
    )

    assert adapter.embed_documents(["first", "second"]) == [[1.0], [2.0]]
    assert [json.loads(request.content)["text"] for request in requests] == ["first", "second"]
    assert len(clients) == 1
    assert clients[0].is_closed


def test_api_error_propagates_and_closes_the_client(rest_client):
    _, clients, responses = rest_client
    responses.append(httpx.Response(403, json={"message": "Permission denied"}))
    adapter = YandexEmbeddingsAdapter(
        api_key="test-key", model="text-search-doc", folder_id="folder"
    )

    with pytest.raises(httpx.HTTPStatusError) as error:
        adapter.embed_query("hello")

    assert error.value.response.status_code == 403
    assert clients[0].is_closed


def test_empty_documents_do_not_open_a_client(rest_client):
    requests, clients, _ = rest_client
    adapter = YandexEmbeddingsAdapter(
        api_key="test-key", model="text-search-doc", folder_id="folder"
    )

    assert adapter.embed_documents([]) == []
    assert requests == []
    assert clients == []
