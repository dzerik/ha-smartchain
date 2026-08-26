"""Tests for dynamic model fetching."""

import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.client_util import (
    MODEL_FETCH_TIMEOUT,
    ModelFetchError,
    async_fetch_models,
    connection_data,
    is_embedding_model,
    static_models,
)
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_VERIFY_SSL,
    DOMAIN,
    EMBEDDING_MODELS_GIGACHAT,
    ENGINE_MODELS,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
    MODELS_GIGACHAT,
    UNIQUE_ID_GIGACHAT,
    UNIQUE_ID_YANDEX_GPT,
)

PATCH_SESSION = "homeassistant.helpers.aiohttp_client.async_get_clientsession"


@pytest.fixture
def mock_session():
    """Create a mock aiohttp session."""
    session = MagicMock()
    response = AsyncMock()
    response.raise_for_status = MagicMock()
    session.get = AsyncMock(return_value=response)
    return session, response


async def test_fetch_ollama_models(hass: HomeAssistant, mock_session):
    """Test fetching models from Ollama."""
    session, response = mock_session
    response.json = AsyncMock(
        return_value={
            "models": [
                {"name": "llama3.3"},
                {"name": "gemma3"},
                {"name": "qwen3"},
            ]
        }
    )

    with patch(PATCH_SESSION, return_value=session):
        models = await async_fetch_models(
            hass, ID_OLLAMA, {CONF_BASE_URL: "http://localhost:11434"}
        )

    assert models[0] == ""
    assert "gemma3" in models
    assert "llama3.3" in models
    assert "qwen3" in models


async def test_fetch_openai_models(hass: HomeAssistant, mock_session):
    """Test fetching models from OpenAI."""
    session, response = mock_session
    response.json = AsyncMock(
        return_value={
            "data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4.1-mini"},
                {"id": "o3"},
            ]
        }
    )

    with patch(PATCH_SESSION, return_value=session):
        models = await async_fetch_models(hass, ID_OPENAI, {CONF_API_KEY: "test-key"})

    assert models[0] == ""
    assert "gpt-4o" in models
    assert "gpt-4.1-mini" in models


async def test_fetch_deepseek_models(hass: HomeAssistant, mock_session):
    """Test fetching models from DeepSeek."""
    session, response = mock_session
    response.json = AsyncMock(
        return_value={
            "data": [
                {"id": "deepseek-chat"},
                {"id": "deepseek-reasoner"},
            ]
        }
    )

    with patch(PATCH_SESSION, return_value=session):
        models = await async_fetch_models(hass, ID_DEEPSEEK, {CONF_API_KEY: "test-key"})

    assert models[0] == ""
    assert "deepseek-chat" in models
    assert "deepseek-reasoner" in models


async def test_fetch_anthropic_models(hass: HomeAssistant, mock_session):
    """Test fetching models from Anthropic."""
    session, response = mock_session
    response.json = AsyncMock(
        return_value={
            "data": [
                {"id": "claude-sonnet-4-6"},
                {"id": "claude-haiku-4-5"},
            ]
        }
    )

    with patch(PATCH_SESSION, return_value=session):
        models = await async_fetch_models(hass, ID_ANTHROPIC, {CONF_API_KEY: "test-key"})

    assert models[0] == ""
    assert "claude-haiku-4-5" in models
    assert "claude-sonnet-4-6" in models


async def test_fetch_gigachat_models(hass: HomeAssistant):
    """Test fetching models from GigaChat."""
    mock_model_1 = MagicMock()
    mock_model_1.id_ = "GigaChat"
    mock_model_2 = MagicMock()
    mock_model_2.id_ = "GigaChat-Pro"
    mock_result = MagicMock()
    mock_result.data = [mock_model_1, mock_model_2]

    with patch("custom_components.smartchain.client_util.GigaChat") as mock_giga_cls:
        mock_client = MagicMock()
        mock_client.get_models.return_value = mock_result
        mock_giga_cls.return_value = mock_client
        hass.async_add_executor_job = AsyncMock(return_value=mock_result)

        models = await async_fetch_models(hass, ID_GIGACHAT, {CONF_API_KEY: "test-creds"})

    assert models[0] == ""
    assert "GigaChat" in models
    assert "GigaChat-Pro" in models


async def test_fetch_yandex_returns_static(hass: HomeAssistant):
    """Test YandexGPT returns static list (no dynamic API)."""
    models = await async_fetch_models(hass, ID_YANDEX_GPT, {CONF_API_KEY: "test-key"})
    assert models == ENGINE_MODELS[UNIQUE_ID_YANDEX_GPT]


async def test_fetch_models_fallback_on_error(hass: HomeAssistant):
    """Test fallback to static list on network error."""
    with patch(PATCH_SESSION, side_effect=Exception("Network error")):
        models = await async_fetch_models(
            hass, ID_OLLAMA, {CONF_BASE_URL: "http://localhost:11434"}
        )

    # Should return static fallback
    assert "" in models
    assert len(models) > 1


async def test_strict_fetch_raises_instead_of_substituting(hass: HomeAssistant):
    """`strict=True` refuses to pass a fallback off as the provider's answer.

    The default is unchanged — a config-flow dialog still degrades to the
    static list. But a caller that is going to *cache* the result has to be
    able to tell "these are the models" from "we could not ask".
    """
    with patch(PATCH_SESSION, side_effect=Exception("Network error")):
        with pytest.raises(ModelFetchError):
            await async_fetch_models(
                hass,
                ID_OLLAMA,
                {CONF_BASE_URL: "http://localhost:11434"},
                strict=True,
            )


async def test_static_models_is_a_copy(hass: HomeAssistant):
    """Callers extend the list they are given; the constant must not move."""
    first = static_models(ID_GIGACHAT)
    first.append("GigaChat-99-Nonsense")
    assert "GigaChat-99-Nonsense" not in static_models(ID_GIGACHAT)
    assert "GigaChat-99-Nonsense" not in ENGINE_MODELS[UNIQUE_ID_GIGACHAT]


@pytest.mark.parametrize("verify_ssl", [True, False])
async def test_gigachat_fetch_honours_verify_ssl(hass: HomeAssistant, verify_ssl):
    """The hub's Verify SSL switch reaches the model listing too.

    It reached the chat client in v5.4.7 and stopped there: this one fetch
    stayed pinned to `verify_ssl_certs=False`, so the switch was a placebo for
    anyone on a network that requires certificates to be checked.
    """
    result = MagicMock()
    result.data = [MagicMock(id_="GigaChat-2-Max")]

    with patch("custom_components.smartchain.client_util.GigaChat") as giga_cls:
        giga_cls.return_value.get_models.return_value = result
        await async_fetch_models(
            hass,
            ID_GIGACHAT,
            {CONF_API_KEY: "creds", CONF_VERIFY_SSL: verify_ssl},
        )

    assert giga_cls.call_args.kwargs["verify_ssl_certs"] is verify_ssl


async def test_gigachat_fetch_caller_is_bounded_by_a_timeout(hass: HomeAssistant):
    """A provider that accepts the connection and never answers must not hang.

    This used to stand the executor hop in with `await asyncio.sleep(30)`,
    which made the test prove nothing about the code it names. An
    `asyncio.sleep` is cancellable; the `run_in_executor` future it replaced is
    not, and the whole question here is what `asyncio.timeout` can do to a
    thread that has already started. The substitution answered "yes" to a
    question the real path answers differently, so the test would have stayed
    green through any regression in either direction.

    So the hop is real: `hass.async_add_executor_job` runs a genuinely blocking
    wait on a genuinely separate thread, exactly as `get_models` does. The
    thread is released at the end rather than left to expire on its own — a
    `time.sleep` long enough to be meaningful is a worker thread this test
    leaks into the rest of the run.
    """
    entered = threading.Event()
    release = threading.Event()

    def blocks_a_worker_thread():
        entered.set()
        # Uncancellable from the event loop, like any blocking SDK call.
        assert release.wait(timeout=30), "test never released the worker thread"
        raise AssertionError("should have been abandoned long before this")

    client = MagicMock()
    client.get_models = blocks_a_worker_thread

    started = time.monotonic()
    try:
        with (
            patch("custom_components.smartchain.client_util.GigaChat", return_value=client),
            patch("custom_components.smartchain.client_util.MODEL_FETCH_TIMEOUT", 0.05),
            pytest.raises(ModelFetchError),
        ):
            await async_fetch_models(hass, ID_GIGACHAT, {CONF_API_KEY: "creds"}, strict=True)
        waited = time.monotonic() - started
    finally:
        release.set()

    assert entered.is_set(), "the blocking call never ran — nothing was bounded"
    # The elapsed time is the assertion that matters. Every way this call can
    # end raises something `async_fetch_models` turns into a ModelFetchError,
    # so `pytest.raises` alone would pass just as happily on a bound of an
    # hour as on one of 50ms.
    assert waited < 5, f"waited {waited:.1f}s — the fetch is not bounded"


async def test_gigachat_fetch_bounds_the_worker_thread_too(hass: HomeAssistant):
    """The bound the caller cannot provide for itself.

    `asyncio.timeout` returns the *caller* on schedule and stops there: the
    executor thread runs `get_models` to completion regardless, because an
    asyncio cancellation cannot reach a `concurrent.futures` future that is
    already running. Measured before the fix, a 10 s bound reported failure at
    10.0 s and the thread stayed blocked for the provider's full 40 s.

    The only thing that ends the call itself is the SDK's own request timeout,
    so that is asserted here directly — on the constructor arguments, because
    the alternative is a test that has to wait out a real socket to observe it.
    langchain-gigachat threads `timeout` into `Settings.timeout` and on into
    `httpx.Timeout`; `test_gigachat_timeout_reaches_the_http_layer` pins that
    end of the contract so this one can stay cheap.
    """
    giga = MagicMock()
    giga.return_value.get_models.return_value = MagicMock(data=[])
    with (
        patch("custom_components.smartchain.client_util.GigaChat", giga),
        patch("custom_components.smartchain.client_util.MODEL_FETCH_TIMEOUT", 7),
    ):
        await async_fetch_models(hass, ID_GIGACHAT, {CONF_API_KEY: "creds"})

    assert giga.call_args.kwargs["timeout"] == 7, (
        "the SDK call is unbounded — the worker thread outlives the caller's timeout"
    )


def test_gigachat_timeout_reaches_the_http_layer():
    """`timeout=` is only worth passing if the SDK honours it.

    Guards the assumption the test above rests on, against the installed
    langchain-gigachat rather than against a mock: the value must survive the
    hop into the vendored SDK's settings, which is where it becomes the
    request timeout that actually unblocks the thread.
    """
    from langchain_gigachat.chat_models.gigachat import GigaChat as RealGigaChat

    client = RealGigaChat(credentials="creds", timeout=MODEL_FETCH_TIMEOUT)
    assert client._client._settings.timeout == MODEL_FETCH_TIMEOUT


async def test_connection_data_carries_the_hub_switches(hass: HomeAssistant):
    """Verify SSL lives in `entry.options`; a fetch reading only `entry.data`
    could never see it. Agent-shaped leftovers stay out."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "creds"},
        options={CONF_VERIFY_SSL: True, "prompt": "a legacy leftover"},
        unique_id=UNIQUE_ID_GIGACHAT,
    )
    entry.add_to_hass(hass)

    merged = connection_data(entry)
    assert merged[CONF_API_KEY] == "creds"
    assert merged[CONF_VERIFY_SSL] is True
    assert "prompt" not in merged


def test_gigachat_default_endpoint_serves_the_current_models():
    """The reachability claim behind `MODELS_GIGACHAT[1]`, pinned.

    `GigaChat-3-Ultra` sits at the head of the model dropdown and the GigaChat
    connection form offers no base-URL field, so the model is reachable only
    because the vendored SDK's default endpoint happens to be the one Sber
    serves it from. That is a dependency default, and dependency defaults move:
    gigachat 0.2.0 and 0.2.1 default to the legacy
    `gigachat.devices.sberbank.ru` address, on which the first entry in our own
    list would fail every message.

    So the floor in `manifest.json` is load-bearing, and this asserts what the
    floor was chosen to guarantee — against the resolved install rather than
    against the version string, because a range is not a promise until
    something checks what it resolved to.
    """
    from langchain_gigachat.chat_models.gigachat import GigaChat as RealGigaChat

    base_url = RealGigaChat(credentials="creds")._client._settings.base_url
    assert base_url.startswith("https://api.giga.chat"), (
        f"GigaChat SDK defaults to {base_url!r}; the models at the top of "
        "MODELS_GIGACHAT are not served there"
    )
    # The head of the list is the one a user lands on by accident, so it is the
    # one whose reachability has to be true rather than assumed.
    assert MODELS_GIGACHAT[1] == "GigaChat-3-Ultra"


def test_gigachat_embedding_list_matches_sbers_catalogue():
    """The static list is what a user picks from whenever the provider cannot
    be reached, and it had fallen behind Sber's catalogue — which is how a
    Custom Model name became the ordinary way to configure embeddings, and so
    how the missing union in `embeddings_subentry_schema` became reachable.

    Only the names Sber currently documents are asserted as required.
    `GigaEmbedding` is deliberately still offered and deliberately not asserted
    here: these lists never drop a name somebody may have stored.
    """
    for name in ("Embeddings", "EmbeddingsGigaR", "Embeddings-2", "Embeddings-3B-2025-09"):
        assert name in EMBEDDING_MODELS_GIGACHAT, f"{name} is documented by Sber and not offered"

    # Every offered name must also survive the chat/embeddings split, or it is
    # in the list and still unreachable from the embeddings form.
    for name in EMBEDDING_MODELS_GIGACHAT:
        if name:
            assert is_embedding_model(ID_GIGACHAT, name), f"{name} is filtered out as a chat model"
