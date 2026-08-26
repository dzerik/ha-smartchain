"""A hub whose credential changed must be repairable without being deleted.

Until v5.4.18 `ConfigFlow` had `async_step_user` and nothing else: no
`async_step_reauth`, no `async_step_reconfigure`, and no path anywhere in the
integration that wrote `entry.data` after creation (`ws_settings_save` writes
strictly `options=`). Rotating an OpenAI key or moving Ollama to another host
therefore meant deleting the entry — and deleting an entry takes its subentries
with it: every agent, every custom tool, and every memory store, whose `dsn`
and `api_key` are stored nowhere else.

These tests pin the repair, and pin it end to end rather than at the schema:
the subentries survive a key rotation, a new `base_url` reaches the client that
is actually constructed, a rejected credential is not written, and a field the
user did not touch comes out the other side unchanged.
"""

from unittest.mock import AsyncMock, patch

import pytest
from gigachat.exceptions import ResponseError
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.config_flow import (
    ENTRY_SECRET_FIELDS,
    credentials_schema,
    is_auth_error,
)
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_FOLDER_ID,
    CONF_SKIP_VALIDATION,
    DOMAIN,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_MEMORY_STORE,
    SUBENTRY_TYPE_TOOL,
    UNIQUE_ID_OLLAMA,
    UNIQUE_ID_OPENAI,
    UNIQUE_ID_YANDEX_GPT,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


class _Status(Exception):
    """The shape every provider SDK an auth failure arrives in has in common."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _openai_entry(hass: HomeAssistant) -> MockConfigEntry:
    """An OpenAI hub carrying one of each subentry type that has to survive.

    The memory store is the expensive one: its `dsn` is a database password
    that the user typed into this dialog once and that lives in `.storage` and
    nowhere else.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ENGINE: ID_OPENAI,
            CONF_API_KEY: "sk-old",
            CONF_BASE_URL: "https://api.openai.com/v1",
            CONF_SKIP_VALIDATION: False,
        },
        unique_id=UNIQUE_ID_OPENAI,
        title="OpenAI",
        minor_version=4,
        subentries_data=[
            {
                "data": {CONF_CHAT_MODEL: "gpt-4o", "prompt": "be brief"},
                "subentry_type": SUBENTRY_TYPE_CONVERSATION,
                "title": "Agent",
                "unique_id": None,
            },
            {
                "data": {"name": "ping", "action_type": "service", "service": "light.turn_on"},
                "subentry_type": SUBENTRY_TYPE_TOOL,
                "title": "ping",
                "unique_id": None,
            },
            {
                "data": {
                    "name": "notes",
                    "backend_type": "pgvector",
                    "dsn": "postgresql://user:hunter2@db/notes",
                    "embeddings": "Emb",
                },
                "subentry_type": SUBENTRY_TYPE_MEMORY_STORE,
                "title": "notes",
                "unique_id": None,
            },
        ],
    )
    entry.add_to_hass(hass)
    return entry


def _ollama_entry(hass: HomeAssistant) -> MockConfigEntry:
    """An Ollama hub whose owner turned the connection probe off.

    `skip_validation` is stored `True` and is *not* resubmitted by any test
    below: it is the field nobody touches, and it is the one that proves the
    repair merges rather than replaces. It is also load-bearing — losing it
    turns the probe back on against a server the user said not to probe.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ENGINE: ID_OLLAMA,
            CONF_BASE_URL: "http://old-host:11434",
            CONF_SKIP_VALIDATION: True,
        },
        unique_id=UNIQUE_ID_OLLAMA,
        title="Ollama",
        minor_version=4,
        subentries_data=[
            {
                "data": {CONF_CHAT_MODEL: "llama3"},
                "subentry_type": SUBENTRY_TYPE_CONVERSATION,
                "title": "Agent",
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    return entry


# -- the classifier ------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_an_unauthorised_status_is_an_auth_error(status: int) -> None:
    assert is_auth_error(_Status(status)) is True


@pytest.mark.parametrize("status", [400, 404, 429, 500, 502])
def test_every_other_status_is_not_an_auth_error(status: int) -> None:
    """A rate limit or a dead server must not send the user to a reauth form;
    the key is fine and retyping it fixes nothing."""
    assert is_auth_error(_Status(status)) is False


def test_a_gigachat_response_error_is_classified_by_its_status() -> None:
    """`ResponseError` carries the status positionally, and the two that mean
    "your credential is wrong" have to be told from the rest of it."""
    assert is_auth_error(ResponseError("http://x", 401, b"", None)) is True
    assert is_auth_error(ResponseError("http://x", 500, b"", None)) is False


def test_an_error_with_no_status_at_all_is_not_an_auth_error() -> None:
    assert is_auth_error(RuntimeError("boom")) is False


# -- the form ------------------------------------------------------------


def test_the_credential_never_travels_back_to_the_browser() -> None:
    """The stored key must not be a suggested value on any repair form: the
    subentry flows redact their secrets for exactly this reason."""
    schema = credentials_schema(ID_OPENAI, {CONF_API_KEY: "sk-old", CONF_BASE_URL: "https://x/v1"})
    for marker in schema.schema:
        suggested = (marker.description or {}).get("suggested_value")
        if str(marker.schema) in ENTRY_SECRET_FIELDS:
            assert suggested is None
        assert suggested != "sk-old"


def test_a_non_secret_field_is_prefilled_from_what_is_stored() -> None:
    """Nothing else may be blanked — a user opening the form to change the key
    must not have to retype the endpoint from memory."""
    schema = credentials_schema(ID_OLLAMA, {CONF_BASE_URL: "http://old-host:11434"})
    suggested = {
        str(marker.schema): (marker.description or {}).get("suggested_value")
        for marker in schema.schema
    }
    assert suggested[CONF_BASE_URL] == "http://old-host:11434"


def test_the_credential_is_optional_on_a_repair_form() -> None:
    """Leaving it blank has to be submittable, because blank means "keep"."""
    schema = credentials_schema(ID_OPENAI, {CONF_API_KEY: "sk-old"})
    assert schema({CONF_BASE_URL: "https://api.openai.com/v1"}) is not None


# -- reauth --------------------------------------------------------------


async def test_reauth_rotates_the_key_and_keeps_every_subentry(
    hass: HomeAssistant, mock_validate_client: AsyncMock
) -> None:
    entry = _openai_entry(hass)
    before = {sub_id: dict(sub.data) for sub_id, sub in entry.subentries.items()}

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch("custom_components.smartchain.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "sk-new", CONF_BASE_URL: "https://api.openai.com/v1"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "sk-new"

    after = {sub_id: dict(sub.data) for sub_id, sub in entry.subentries.items()}
    assert after == before
    assert any(sub.get("dsn") == "postgresql://user:hunter2@db/notes" for sub in after.values())


async def test_a_rejected_credential_is_not_written(hass: HomeAssistant) -> None:
    entry = _openai_entry(hass)

    result = await entry.start_reauth_flow(hass)
    with patch(
        "custom_components.smartchain.config_flow.validate_client",
        new_callable=AsyncMock,
        side_effect=_Status(401),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "sk-wrong", CONF_BASE_URL: "https://api.openai.com/v1"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_API_KEY] == "sk-old"


async def test_a_blank_credential_keeps_the_stored_one(
    hass: HomeAssistant, mock_validate_client: AsyncMock
) -> None:
    """The form cannot show the key, so an untouched field comes back empty.
    Treating that as "clear it" would break the hub on an unrelated edit."""
    entry = _openai_entry(hass)

    result = await entry.start_reauth_flow(hass)
    with patch("custom_components.smartchain.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "", CONF_BASE_URL: "https://mirror/v1"}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "sk-old"
    assert entry.data[CONF_BASE_URL] == "https://mirror/v1"


async def test_the_probe_sees_the_whole_connection_not_just_the_form(
    hass: HomeAssistant, mock_validate_client: AsyncMock
) -> None:
    """`validate_client` is handed the merged connection, not the submitted keys.

    `skip_validation` is the field that makes this checkable rather than
    decorative: it is stored `True`, the form does not resubmit it, and it is
    the first thing `validate_client` reads. Probing only what the form sent
    would open a live connection to a server whose owner switched the probe
    off — a check that is quietly *more* eager than the user asked for.
    """
    entry = _ollama_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    with patch("custom_components.smartchain.async_setup_entry", return_value=True):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BASE_URL: "http://new-host:11434"}
        )
        await hass.async_block_till_done()

    probed = mock_validate_client.call_args.args[1]
    assert probed[CONF_SKIP_VALIDATION] is True
    assert probed[CONF_BASE_URL] == "http://new-host:11434"
    assert probed[CONF_ENGINE] == ID_OLLAMA


async def test_reauth_probes_the_new_key_against_the_stored_endpoint(
    hass: HomeAssistant, mock_validate_client: AsyncMock
) -> None:
    """A key checked against a default endpoint proves nothing about the mirror
    this hub actually talks to."""
    entry = _openai_entry(hass)

    result = await entry.start_reauth_flow(hass)
    with patch("custom_components.smartchain.async_setup_entry", return_value=True):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "sk-new", CONF_BASE_URL: "https://api.openai.com/v1"},
        )
        await hass.async_block_till_done()

    probed = mock_validate_client.call_args.args[1]
    assert probed[CONF_API_KEY] == "sk-new"
    assert probed[CONF_BASE_URL] == "https://api.openai.com/v1"
    assert probed[CONF_ENGINE] == ID_OPENAI


# -- reconfigure ---------------------------------------------------------


async def test_reconfigure_moves_ollama_and_the_live_client_follows(
    hass: HomeAssistant, mock_validate_client: AsyncMock
) -> None:
    """`entry.data` changing is not the guarantee; the client the entry runs on
    being rebuilt from it is."""
    entry = _ollama_entry(hass)

    with patch("langchain_ollama.ChatOllama") as chat:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert chat.call_args.kwargs["base_url"] == "http://old-host:11434"

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BASE_URL: "http://new-host:11434"}
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_BASE_URL] == "http://new-host:11434"
        assert chat.call_args.kwargs["base_url"] == "http://new-host:11434"
        # The one field the form did not carry. Writing the submitted keys as
        # the whole of `entry.data` — or keeping the creation schema's
        # `default=`, which voluptuous injects into every absent field —
        # silently turns the probe back on.
        assert entry.data[CONF_SKIP_VALIDATION] is True
        assert entry.data[CONF_ENGINE] == ID_OLLAMA


async def test_reconfigure_leaves_a_field_the_user_did_not_touch(
    hass: HomeAssistant, mock_validate_client: AsyncMock
) -> None:
    """YandexGPT asks for a folder as well as a key. Changing the key must not
    take the folder with it, and the engine must survive both."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ENGINE: ID_YANDEX_GPT,
            CONF_API_KEY: "old-key",
            CONF_FOLDER_ID: "folder-abc",
        },
        unique_id=UNIQUE_ID_YANDEX_GPT,
        title="YandexGPT",
        minor_version=4,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    with patch("custom_components.smartchain.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "new-key", CONF_FOLDER_ID: "folder-abc"},
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_FOLDER_ID] == "folder-abc"
    assert entry.data[CONF_API_KEY] == "new-key"
    assert entry.data[CONF_ENGINE] == ID_YANDEX_GPT


async def test_reconfigure_keeps_the_unique_id_so_the_entry_is_updated_not_cloned(
    hass: HomeAssistant, mock_validate_client: AsyncMock
) -> None:
    """`UNIQUE_ID[engine]` is fixed per provider, so a reconfigure that re-ran
    `_abort_if_unique_id_configured` would abort on the entry it is editing."""
    entry = _ollama_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    with patch("custom_components.smartchain.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BASE_URL: "http://new-host:11434"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert entry.unique_id == UNIQUE_ID_OLLAMA


# -- setup raises so Home Assistant asks -------------------------------------


async def test_a_401_at_setup_starts_a_reauth_flow(hass: HomeAssistant) -> None:
    """Nothing raised `ConfigEntryAuthFailed`, so a revoked key produced a
    broken entry and no notification telling the user why."""
    entry = _openai_entry(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        side_effect=_Status(401),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    flows = [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["handler"] == DOMAIN and flow["context"].get("source") == SOURCE_REAUTH
    ]
    assert len(flows) == 1


async def test_a_500_at_setup_does_not_ask_for_the_key_again(hass: HomeAssistant) -> None:
    """A provider outage is not an authentication problem, and telling the user
    to retype a working key is the silent-failure shape this audit is about."""
    entry = _openai_entry(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        side_effect=_Status(500),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert not [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["handler"] == DOMAIN and flow["context"].get("source") == SOURCE_REAUTH
    ]
