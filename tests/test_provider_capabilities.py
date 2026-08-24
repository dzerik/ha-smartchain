"""The capability matrix decides which providers can host embeddings."""

from custom_components.smartchain.client_util import PROVIDER_CAPABILITIES, supports
from custom_components.smartchain.const import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDINGS,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
)


def test_every_provider_supports_chat() -> None:
    for engine in (ID_GIGACHAT, ID_YANDEX_GPT, ID_OPENAI, ID_OLLAMA, ID_DEEPSEEK, ID_ANTHROPIC):
        assert supports(engine, CAPABILITY_CHAT) is True


def test_four_providers_support_embeddings() -> None:
    for engine in (ID_GIGACHAT, ID_YANDEX_GPT, ID_OPENAI, ID_OLLAMA):
        assert supports(engine, CAPABILITY_EMBEDDINGS) is True


def test_deepseek_and_anthropic_have_no_embeddings() -> None:
    assert supports(ID_DEEPSEEK, CAPABILITY_EMBEDDINGS) is False
    assert supports(ID_ANTHROPIC, CAPABILITY_EMBEDDINGS) is False


def test_unknown_engine_supports_nothing() -> None:
    assert supports("mistral", CAPABILITY_CHAT) is False
    assert supports("mistral", CAPABILITY_EMBEDDINGS) is False


def test_matrix_covers_every_known_provider() -> None:
    known = {ID_GIGACHAT, ID_YANDEX_GPT, ID_OPENAI, ID_OLLAMA, ID_DEEPSEEK, ID_ANTHROPIC}
    # PROVIDER_CAPABILITIES now includes all OpenAI-compatible providers from the table,
    # so it's a superset of the known ones, not an exact match.
    assert known <= set(PROVIDER_CAPABILITIES)
