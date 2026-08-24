"""The OpenAI-compatible provider table and the dicts derived from it."""

from custom_components.smartchain.const import (
    CONF_ENGINE_OPTIONS,
    DEFAULT_MODEL,
    EMBEDDING_RULE_HEURISTIC,
    EMBEDDING_RULE_NONE,
    EMBEDDING_RULE_OPENAI_PREFIX,
    ENGINE_MODELS,
    ID_DEEPSEEK,
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
