"""Constants for the SmartChain integration."""

from homeassistant.helpers import selector

DOMAIN = "smartchain"
CONF_ENGINE = "engine"
CONF_CHAT_MODEL = "model"
CONF_CHAT_MODEL_USER = "model_user"
DEFAULT_CHAT_MODEL = ""
CONF_TEMPERATURE = "temperature"
DEFAULT_TEMPERATURE = 0.1
CONF_PROFANITY = "profanity"
DEFAULT_PROFANITY = False
CONF_VERIFY_SSL = "verify_ssl"
DEFAULT_VERIFY_SSL = False
CONF_MAX_TOKENS = "max_tokens"
CONF_SKIP_VALIDATION = "skip_validation"
DEFAULT_SKIP_VALIDATION = False
CONF_PROCESS_BUILTIN_SENTENCES = "process_builtin_sentences"
DEFAULT_PROCESS_BUILTIN_SENTENCES = True
CONF_CHAT_HISTORY = "chat_history"
DEFAULT_CHAT_HISTORY = True
CONF_PROMPT = "prompt"
DEFAULT_PROMPT = """You are a smart home voice assistant {{ ha_name }} powered by Home Assistant.
Answer truthfully and to the point. Answer in plain text, briefly and clearly.
Answer in the user's language."""

DEFAULT_DEVICES_PROMPT = """
The following rooms, devices and sensors are available in the home:
{%- for area in areas() %}
  {%- set area_info = namespace(printed=false) %}
  {%- for device in area_devices(area) -%}
    {%- if not device_attr(device, "disabled_by") and not device_attr(device, "entry_type") and device_attr(device, "name") %}
      {%- if not area_info.printed %}

{{ area_name(area) }}:
        {%- set area_info.printed = true %}
      {%- endif %}
- {{ device_attr(device, "name") }}{% if device_attr(device, "model") and (device_attr(device, "model") | string) not in (device_attr(device, "name") | string) %} ({{ device_attr(device, "model") }}){% endif %}

      {%- for entity_id in device_entities(device) %}
        {%- set entity_domain = entity_id.split('.')[0] %}
        {%- set dc = state_attr(entity_id, 'device_class') %}
        {%- set friendly = state_attr(entity_id, 'friendly_name') %}
        {%- set entity_state = states(entity_id) %}
        {%- if entity_state and entity_state != 'unavailable' %}
  - {{ entity_id }} ({{ entity_domain }}{% if dc %}, {{ dc }}{% endif %}): {{ entity_state }}{% if state_attr(entity_id, 'unit_of_measurement') %} {{ state_attr(entity_id, 'unit_of_measurement') }}{% endif %}

        {%- endif %}
      {%- endfor %}
    {%- endif %}
  {%- endfor %}
{%- endfor %}"""

ID_GIGACHAT = "gigachat"
ID_YANDEX_GPT = "yandexgpt"
ID_OPENAI = "openai"
ID_OLLAMA = "ollama"
ID_DEEPSEEK = "deepseek"
ID_ANTHROPIC = "anthropic"
UNIQUE_ID_GIGACHAT = "GigaChat"
UNIQUE_ID_YANDEX_GPT = "YandexGPT"
UNIQUE_ID_OPENAI = "OpenAI"
UNIQUE_ID_OLLAMA = "Ollama"
UNIQUE_ID_DEEPSEEK = "DeepSeek"
UNIQUE_ID_ANTHROPIC = "Anthropic"

UNIQUE_ID = {
    ID_GIGACHAT: UNIQUE_ID_GIGACHAT,
    ID_YANDEX_GPT: UNIQUE_ID_YANDEX_GPT,
    ID_OPENAI: UNIQUE_ID_OPENAI,
    ID_OLLAMA: UNIQUE_ID_OLLAMA,
    ID_DEEPSEEK: UNIQUE_ID_DEEPSEEK,
    ID_ANTHROPIC: UNIQUE_ID_ANTHROPIC,
}

CONF_ENGINE_OPTIONS = [
    selector.SelectOptionDict(value=ID_GIGACHAT, label=UNIQUE_ID_GIGACHAT),
    selector.SelectOptionDict(value=ID_YANDEX_GPT, label=UNIQUE_ID_YANDEX_GPT),
    selector.SelectOptionDict(value=ID_OPENAI, label=UNIQUE_ID_OPENAI),
    selector.SelectOptionDict(value=ID_OLLAMA, label=UNIQUE_ID_OLLAMA),
    selector.SelectOptionDict(value=ID_DEEPSEEK, label=UNIQUE_ID_DEEPSEEK),
    selector.SelectOptionDict(value=ID_ANTHROPIC, label=UNIQUE_ID_ANTHROPIC),
]
MODELS_GIGACHAT = [
    "",
    "GigaChat",
    "GigaChat:latest",
    "GigaChat-Plus",
    "GigaChat-Pro",
    "GigaChat-Max",
]
DEFAULT_MODELS_YANDEX_GPT = ["", "YandexGPT", "YandexGPT Lite", "Summary"]
MODELS_OPENAI = [
    "",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
    "o3",
    "o3-mini",
    "o4-mini",
]
MODELS_OLLAMA = [
    "",
    "llama3.3",
    "qwen3",
    "qwen3:4b",
    "gemma3",
    "gemma3:4b",
    "t-pro2",
    "t-lite",
    "deepseek-r1",
    "phi4",
    "home-3b-v3",
]
MODELS_DEEPSEEK = [
    "",
    "deepseek-chat",
    "deepseek-reasoner",
]
MODELS_ANTHROPIC = [
    "",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-opus-4-6",
]
ENGINE_MODELS = {
    UNIQUE_ID_GIGACHAT: MODELS_GIGACHAT,
    UNIQUE_ID_YANDEX_GPT: DEFAULT_MODELS_YANDEX_GPT,
    UNIQUE_ID_OPENAI: MODELS_OPENAI,
    UNIQUE_ID_OLLAMA: MODELS_OLLAMA,
    UNIQUE_ID_DEEPSEEK: MODELS_DEEPSEEK,
    UNIQUE_ID_ANTHROPIC: MODELS_ANTHROPIC,
}
DEFAULT_MODEL = {
    ID_GIGACHAT: None,
    ID_OPENAI: "gpt-4.1-mini",
    ID_YANDEX_GPT: None,
    ID_OLLAMA: "llama3.3",
    ID_DEEPSEEK: "deepseek-chat",
    ID_ANTHROPIC: "claude-sonnet-4-6",
}

CONF_BASE_URL = "base_url"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

CONF_LLM_HASS_API = "llm_hass_api"
CONF_API_KEY = "api_key"
CONF_FOLDER_ID = "folder_id"

MAX_TOOL_ITERATIONS = 10
SUBENTRY_TYPE_CONVERSATION = "conversation"

# Dispatcher signal: emitted by analyze_image, consumed by the Last Analysis sensor.
SIGNAL_NEW_ANALYSIS = f"{DOMAIN}_new_analysis"

CONF_ENABLE_HISTORY_TOOL = "enable_history_tool"
DEFAULT_ENABLE_HISTORY_TOOL = False
HISTORY_TOOL_NAME = "get_state_history"
HISTORY_TOOL_MAX_HOURS = 24
DELEGATE_TOOL_NAME = "ask_agent"

# Custom tools (v4.1.0)
# Relative to hass.config.config_dir
TOOLS_YAML_PATH = "smartchain/tools.yaml"
CONF_ALLOWED_TOOLS = "allowed_tools"
SERVICE_RELOAD_TOOLS = "reload_tools"
EVENT_TOOLS_RELOADED = f"{DOMAIN}_tools_reloaded"
TOOL_NAME_PATTERN = r"^[a-z_][a-z0-9_]*$"

# MCP client (v4.2.0)
MCP_RECONNECT_INITIAL_DELAY = 1.0  # seconds
MCP_RECONNECT_MAX_DELAY = 30.0  # seconds
MCP_CALL_TIMEOUT_DEFAULT = 30  # seconds
MCP_NAME_PATTERN = r"^[a-z_][a-z0-9_-]*$"

# Long-term memory / RAG (v4.3.0)
MEMORY_DEFAULT_RETENTION_DAYS = 90
MEMORY_MAX_TEXT_LEN = 4096
MEMORY_CHUNK_SIZE = 1024
MEMORY_CHUNK_OVERLAP = 100
MEMORY_TOOL_NAME = "search_memory"
SERVICE_CLEAR_MEMORY = "clear_memory"
EVENT_MEMORY_CLEARED = f"{DOMAIN}_memory_cleared"
# Relative to hass.config.config_dir/.storage
MEMORY_PERSIST_DIRNAME = "smartchain_memory"
MEMORY_LOGBOOK_POLL_MIN_MINUTES = 5
MEMORY_LOGBOOK_POLL_MAX_MINUTES = 1440
MEMORY_DEFAULT_LOGBOOK_POLL_MINUTES = 60
MEMORY_EMBED_TIMEOUT_SECONDS = 30

# Multi-agent orchestration (v4.4.0)
CONF_ENABLE_MULTI_AGENT_TOOLS = "enable_multi_agent_tools"
DEFAULT_ENABLE_MULTI_AGENT_TOOLS = False
DELEGATE_MANY_TOOL_NAME = "ask_agents"
CRITIQUE_TOOL_NAME = "critique_response"
MULTI_AGENT_MAX_PARALLEL = 5
MULTI_AGENT_PER_CALL_TIMEOUT_SECONDS = 60

# Vector backends (v5.0.0)
MEMORY_BACKEND_TYPES = ["sqlite_numpy", "sqlite_vec", "pgvector", "qdrant"]
MEMORY_DEFAULT_BACKEND = "sqlite_numpy"
MEMORY_BACKEND_TIMEOUT_SECONDS = 30
MEMORY_DIM_PROBE_TEXT = "smartchain dimension probe"
# \Z, not $: a store name becomes a filename component for the file-based
# backends, and $ would let a trailing newline through.
MEMORY_STORE_NAME_PATTERN = r"^[a-z_][a-z0-9_]*\Z"
# pgvector interpolates `table` straight into DDL/DML and qdrant puts
# `collection` into a REST URL path, so both are constrained to the same safe
# identifier shape. Same \Z reasoning as above.
MEMORY_IDENTIFIER_PATTERN = r"^[a-z_][a-z0-9_]*\Z"
MEMORY_SQLITE_SOFT_LIMIT = 50_000
MEMORY_DEFAULT_QDRANT_COLLECTION = "smartchain_memory"
MEMORY_DEFAULT_PG_TABLE = "smartchain_memory"

# Provider capabilities (v5.0.0)
CAPABILITY_CHAT = "chat"
CAPABILITY_EMBEDDINGS = "embeddings"
SUBENTRY_TYPE_EMBEDDINGS = "embeddings"

# Static fallback embedding-model lists, used when a provider's API is
# unreachable or has no list endpoint (YandexGPT).
EMBEDDING_MODELS_GIGACHAT = ["", "Embeddings", "EmbeddingsGigaR"]
EMBEDDING_MODELS_YANDEX_GPT = ["", "text-search-doc", "text-search-query"]
EMBEDDING_MODELS_OPENAI = ["", "text-embedding-3-small", "text-embedding-3-large"]
EMBEDDING_MODELS_OLLAMA = ["", "nomic-embed-text", "mxbai-embed-large", "bge-m3"]

ENGINE_EMBEDDING_MODELS = {
    UNIQUE_ID_GIGACHAT: EMBEDDING_MODELS_GIGACHAT,
    UNIQUE_ID_YANDEX_GPT: EMBEDDING_MODELS_YANDEX_GPT,
    UNIQUE_ID_OPENAI: EMBEDDING_MODELS_OPENAI,
    UNIQUE_ID_OLLAMA: EMBEDDING_MODELS_OLLAMA,
}

# Entity indexing (v5.0.0)
ENTITY_SOURCE_TYPE = "entities"
ENTITY_PRESETS = ["minimal", "optimal", "maximal", "paranoid"]
ENTITY_DEFAULT_PRESET = "optimal"
ENTITY_TOOL_NAME = "search_entities"
SERVICE_REINDEX_ENTITIES = "reindex_entities"
EVENT_ENTITIES_REINDEXED = f"{DOMAIN}_entities_reindexed"
ENTITY_INDEX_BATCH_SIZE = 32
ENTITY_INDEX_BATCH_PAUSE_SECONDS = 0.5
# Comfortably under MemoryStore's chunking thresholds (MEMORY_CHUNK_SIZE /
# MEMORY_MAX_TEXT_LEN) so a catalogue entry never splits into multiple
# chunks. `MemoryStore.add` only honours the given doc_id verbatim when a
# text yields exactly one chunk; a multi-chunk catalogue would be stored
# under suffixed doc_ids the next sweep's fingerprint lookup can never find,
# so it would re-embed every sweep, forever.
ENTITY_CATALOGUE_MAX_CHARS = 900
ENTITY_REGISTRY_DEBOUNCE_SECONDS = 5
ENTITY_STATE_FLUSH_SECONDS = 30
ENTITY_SEARCH_DEFAULT_TOP_K = 10
ENTITY_SEARCH_MAX_TOP_K = 50
ENTITY_LEXICAL_CANDIDATES = 200

# Only what a person controls.
ENTITY_MINIMAL_DOMAINS = [
    "light",
    "switch",
    "cover",
    "climate",
    "lock",
    "fan",
    "media_player",
    "scene",
    "script",
    "vacuum",
    "water_heater",
    "humidifier",
    "valve",
]
# `optimal` adds these whole domains on top of the minimal set.
ENTITY_OPTIMAL_EXTRA_DOMAINS = [
    "button",
    "input_boolean",
    "input_select",
    "input_number",
    "select",
    "number",
    "alarm_control_panel",
    "person",
    "weather",
]
# ...and these sensor / binary_sensor device classes. Battery level, signal
# strength and the like are deliberately absent: they dominate a real home by
# count and carry no meaning a user would ever search for.
ENTITY_MEANINGFUL_DEVICE_CLASSES = [
    "temperature",
    "humidity",
    "illuminance",
    "pressure",
    "motion",
    "occupancy",
    "presence",
    "door",
    "window",
    "opening",
    "garage_door",
    "smoke",
    "gas",
    "moisture",
    "carbon_monoxide",
    "carbon_dioxide",
    "power",
    "energy",
    "sound",
    "vibration",
    "problem",
]

# RESERVED_TOOL_NAMES lives here, after ENTITY_TOOL_NAME, because it
# references that name — defining it up near the other tool-name constants
# would forward-reference a name that doesn't exist yet at that point in the
# module and raise NameError on import.
RESERVED_TOOL_NAMES = frozenset({HISTORY_TOOL_NAME, DELEGATE_TOOL_NAME, ENTITY_TOOL_NAME})

# Dynamic entity context (v5.0.0, roadmap subsystem C)
CONF_DYNAMIC_ENTITY_CONTEXT = "dynamic_entity_context"
DEFAULT_DYNAMIC_ENTITY_CONTEXT = True
CONF_DYNAMIC_CONTEXT_PRESET = "dynamic_context_preset"
CONF_DYNAMIC_CONTEXT_ON_ASSIST = "dynamic_context_on_assist"
DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST = False

# How many entities the per-turn retrieval may add. A constant rather than an
# option: every extra option is a support surface, and if 12 proves wrong it
# should change in one place for everyone.
ENTITY_CONTEXT_MAX_ENTITIES = 12
# Generous — roughly 300-500 entities. Past this the skeleton stops being a map
# and starts being the dump it replaced.
ENTITY_SKELETON_MAX_CHARS = 6000
# Registry events are the real invalidation; this is the backstop.
ENTITY_SKELETON_CACHE_TTL = 300  # seconds
