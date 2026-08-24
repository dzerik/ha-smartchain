"""The OpenAI-compatible provider table and the dicts derived from it."""

from custom_components.smartchain.client_util import is_embedding_model, supports
from custom_components.smartchain.const import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDINGS,
    CONF_ENGINE_OPTIONS,
    DEFAULT_MODEL,
    EMBEDDING_RULE_HEURISTIC,
    EMBEDDING_RULE_NONE,
    EMBEDDING_RULE_OPENAI_PREFIX,
    ENGINE_MODELS,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_GROQ,
    ID_LLAMACPP,
    ID_LMSTUDIO,
    ID_OPENAI,
    ID_OPENROUTER,
    ID_TOGETHER,
    OPENAI_COMPATIBLE,
    UNIQUE_ID,
)

VALID_RULES = {
    EMBEDDING_RULE_OPENAI_PREFIX,
    EMBEDDING_RULE_HEURISTIC,
    EMBEDDING_RULE_NONE,
}


def test_table_covers_the_seven_expected_providers():
    assert set(OPENAI_COMPATIBLE) == {
        ID_OPENAI,
        ID_DEEPSEEK,
        ID_OPENROUTER,
        ID_GROQ,
        ID_TOGETHER,
        ID_LMSTUDIO,
        ID_LLAMACPP,
    }


def test_every_row_is_well_formed():
    for engine, row in OPENAI_COMPATIBLE.items():
        assert row.label, engine
        assert row.default_base_url.startswith("http"), engine
        assert row.embedding_rule in VALID_RULES, engine
        assert row.static_models and row.static_models[0] == "", engine


def test_labels_are_unique():
    labels = [row.label for row in OPENAI_COMPATIBLE.values()]
    assert len(labels) == len(set(labels))


def test_local_providers_need_no_api_key():
    assert OPENAI_COMPATIBLE[ID_LMSTUDIO].requires_api_key is False
    assert OPENAI_COMPATIBLE[ID_LLAMACPP].requires_api_key is False


def test_hosted_providers_need_an_api_key():
    for engine in (ID_OPENAI, ID_DEEPSEEK, ID_OPENROUTER, ID_GROQ, ID_TOGETHER):
        assert OPENAI_COMPATIBLE[engine].requires_api_key is True, engine


def test_openai_is_the_only_prefix_rule():
    prefixed = [
        engine
        for engine, row in OPENAI_COMPATIBLE.items()
        if row.embedding_rule == EMBEDDING_RULE_OPENAI_PREFIX
    ]
    assert prefixed == [ID_OPENAI]


def test_deepseek_keeps_the_none_rule():
    # It falls through to `return False` today; the heuristic would change that.
    assert OPENAI_COMPATIBLE[ID_DEEPSEEK].embedding_rule == EMBEDDING_RULE_NONE


def test_new_rows_carry_no_default_model():
    for engine in (ID_OPENROUTER, ID_GROQ, ID_TOGETHER, ID_LMSTUDIO, ID_LLAMACPP):
        assert OPENAI_COMPATIBLE[engine].default_model is None, engine


def test_existing_rows_keep_their_default_model():
    assert OPENAI_COMPATIBLE[ID_OPENAI].default_model == "gpt-4.1-mini"
    assert OPENAI_COMPATIBLE[ID_DEEPSEEK].default_model == "deepseek-chat"


def test_derived_dicts_gained_every_row():
    for engine, row in OPENAI_COMPATIBLE.items():
        assert UNIQUE_ID[engine] == row.label, engine
        assert ENGINE_MODELS[row.label] == row.static_models, engine
        assert DEFAULT_MODEL[engine] == row.default_model, engine


def test_picker_offers_every_row():
    values = {option["value"] for option in CONF_ENGINE_OPTIONS}
    assert set(OPENAI_COMPATIBLE) <= values


def test_picker_has_no_duplicates():
    values = [option["value"] for option in CONF_ENGINE_OPTIONS]
    assert len(values) == len(set(values))


def test_every_row_supports_chat():
    for engine in OPENAI_COMPATIBLE:
        assert supports(engine, CAPABILITY_CHAT), engine


def test_embeddings_capability_follows_the_row():
    for engine, row in OPENAI_COMPATIBLE.items():
        assert supports(engine, CAPABILITY_EMBEDDINGS) is row.serves_embeddings, engine


def test_hand_written_providers_keep_their_capabilities():
    assert supports(ID_GIGACHAT, CAPABILITY_EMBEDDINGS) is True
    assert supports(ID_GIGACHAT, CAPABILITY_CHAT) is True


def test_unknown_engine_supports_nothing():
    assert supports("nope", CAPABILITY_CHAT) is False


def test_openai_still_uses_the_prefix_rule():
    assert is_embedding_model(ID_OPENAI, "text-embedding-3-small") is True
    assert is_embedding_model(ID_OPENAI, "gpt-4.1-mini") is False
    # The heuristic would match this; the prefix rule must not.
    assert is_embedding_model(ID_OPENAI, "some-bge-model") is False


def test_deepseek_calls_every_name_a_chat_name():
    assert is_embedding_model(ID_DEEPSEEK, "deepseek-chat") is False
    assert is_embedding_model(ID_DEEPSEEK, "deepseek-embed") is False


def test_heuristic_rule_matches_the_embedding_families():
    for name in ("nomic-embed-text", "bge-m3", "gte-large", "e5-base", "all-minilm"):
        assert is_embedding_model(ID_LMSTUDIO, name) is True, name


def test_heuristic_rule_passes_chat_names_through():
    for name in ("llama-3.3-70b", "qwen2.5-coder", "mistral-small"):
        assert is_embedding_model(ID_OPENROUTER, name) is False, name
