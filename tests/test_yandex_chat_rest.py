"""Removing the conflicting SDK must preserve Yandex conversations too."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from custom_components.smartchain.client_util import get_client, validate_client


@pytest.fixture
def chat_rest_client():
    requests = []
    clients = []
    original_sync = httpx.Client
    original_async = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200, json={"result": {"alternatives": [{"message": {"text": "answer"}}]}}
        )

    def sync_client(**kwargs):
        client = original_sync(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    def async_client(**kwargs):
        client = original_async(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    with (
        patch("httpx.Client", side_effect=sync_client),
        patch("httpx.AsyncClient", side_effect=async_client),
        patch.dict("sys.modules", {"yandex": None, "yandex_cloud_ml_sdk": None}),
    ):
        yield requests, clients


async def test_yandex_conversation_without_sdk(hass, chat_rest_client):
    requests, clients = chat_rest_client
    entry = SimpleNamespace(data={"api_key": "test-key", "folder_id": "folder"})
    client = await get_client(
        hass, "yandexgpt", entry, {"model": None, "temperature": 0.2, "max_tokens": 40}
    )
    result = await client.ainvoke(
        [
            SystemMessage("system"),
            HumanMessage("hello"),
            AIMessage("previous"),
            HumanMessage("again"),
        ]
    )

    assert result.content == "answer"
    request = requests[0]
    assert str(request.url) == "https://ai.api.cloud.yandex.net/foundationModels/v1/completion"
    assert request.headers["authorization"] == "Api-Key test-key"
    body = json.loads(request.content)
    assert body["modelUri"] == "gpt://folder/yandexgpt-lite/latest"
    assert body["completionOptions"] == {"stream": False, "temperature": 0.2, "maxTokens": "40"}
    assert body["messages"] == [
        {"role": "system", "text": "system"},
        {"role": "user", "text": "hello"},
        {"role": "assistant", "text": "previous"},
        {"role": "user", "text": "again"},
    ]
    assert clients[0].is_closed


async def test_yandex_validation_uses_rest_without_sdk(hass, chat_rest_client):
    requests, clients = chat_rest_client
    await validate_client(
        hass, {"engine": "yandexgpt", "api_key": "test-key", "folder_id": "folder"}
    )

    assert json.loads(requests[0].content)["completionOptions"]["maxTokens"] == "10"
    assert clients[0].is_closed


async def test_yandex_astream_keeps_the_langchain_message_contract(hass, chat_rest_client):
    _, clients = chat_rest_client
    entry = SimpleNamespace(data={"api_key": "test-key", "folder_id": "folder"})
    client = await get_client(hass, "yandexgpt", entry, {"model": None})

    assert [chunk.content async for chunk in client.astream([HumanMessage("hello")])] == ["answer"]
    assert clients[0].is_closed
