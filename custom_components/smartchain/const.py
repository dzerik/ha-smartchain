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
GENERATE_AUTOMATION_PROMPT = """You are a Home Assistant automation expert. Generate a valid HA automation YAML based on the user's description.

Rules:
- Output ONLY valid YAML (no markdown code fences, no explanation, no comments)
- The YAML must be a single automation object with: alias, description, trigger, action
- Add condition only if logically needed
- Use standard HA trigger platforms: time, state, numeric_state, sun, zone, event, template
- Use standard HA action services: light.turn_on, switch.turn_off, notify.send_message, climate.set_temperature, etc.
- Use proper entity_id format (domain.name)
- For time-based triggers use platform: time with "at" field (HH:MM:SS)
- For weekday conditions use condition: time with weekday list
- For presence use person.* entities or device_tracker.*
- Keep it simple and practical
- IMPORTANT: Use ONLY entity_ids from the list below. Do NOT invent entity_ids.

{ha_context}

User description: {description}"""

GENERATE_SCRIPT_PROMPT = """You are a Home Assistant expert. Generate a valid HA script YAML based on the user's description.

Rules:
- Output ONLY valid YAML (no markdown code fences, no explanation, no comments)
- The YAML must be a single script object with: alias, description, sequence
- sequence is a list of actions (service calls, delays, conditions, etc.)
- Use standard HA services: light.turn_on, switch.turn_off, notify.send_message, etc.
- Use proper entity_id format (domain.name)
- Keep it simple and practical
- IMPORTANT: Use ONLY entity_ids from the list below. Do NOT invent entity_ids.

{ha_context}

User description: {description}"""

GENERATE_SCENE_PROMPT = """You are a Home Assistant expert. Generate a valid HA scene YAML based on the user's description.

Rules:
- Output ONLY valid YAML (no markdown code fences, no explanation, no comments)
- The YAML must be a single scene object with: name and entities
- entities is a dict of entity_id -> desired state/attributes
- For lights: state on/off, brightness (0-255), color_temp, rgb_color, etc.
- For switches/fans/covers: state on/off
- For climate: temperature, hvac_mode
- Keep it simple and practical
- IMPORTANT: Use ONLY entity_ids from the list below. Do NOT invent entity_ids.

{ha_context}

User description: {description}"""

GENERATE_BLUEPRINT_PROMPT = """You are a Home Assistant blueprint expert. Generate a valid HA automation blueprint YAML based on the user's description.

Rules:
- Output ONLY valid YAML (no markdown code fences, no explanation, no comments)
- The YAML must be a valid blueprint with:
  - blueprint: (name, description, domain: automation, input: with configurable parameters)
  - trigger: (using !input references for configurable entities/values)
  - condition: (optional, use !input if configurable)
  - action: (using !input references for configurable entities/values)
- Make entity references configurable via input selectors (entity, device, text, number, boolean, select, time)
- Use proper selector types for inputs (e.g. entity: domain: light for light entities)
- Include sensible defaults where appropriate
- Keep it practical and reusable

{ha_context}

User description: {description}"""

GENERATE_PROMPTS = {
    "automation": GENERATE_AUTOMATION_PROMPT,
    "script": GENERATE_SCRIPT_PROMPT,
    "scene": GENERATE_SCENE_PROMPT,
    "blueprint": GENERATE_BLUEPRINT_PROMPT,
}

CONF_ENABLE_HISTORY_TOOL = "enable_history_tool"
DEFAULT_ENABLE_HISTORY_TOOL = False
HISTORY_TOOL_NAME = "get_state_history"
HISTORY_TOOL_MAX_HOURS = 24
DELEGATE_TOOL_NAME = "ask_agent"
