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
UNIQUE_ID_GIGACHAT = "GigaChat"
UNIQUE_ID_YANDEX_GPT = "YandexGPT"
UNIQUE_ID_OPENAI = "OpenAI"

UNIQUE_ID = {
    ID_GIGACHAT: UNIQUE_ID_GIGACHAT,
    ID_YANDEX_GPT: UNIQUE_ID_YANDEX_GPT,
    ID_OPENAI: UNIQUE_ID_OPENAI,
}

CONF_ENGINE_OPTIONS = [
    selector.SelectOptionDict(value=ID_GIGACHAT, label=UNIQUE_ID_GIGACHAT),
    selector.SelectOptionDict(value=ID_YANDEX_GPT, label=UNIQUE_ID_YANDEX_GPT),
    selector.SelectOptionDict(value=ID_OPENAI, label=UNIQUE_ID_OPENAI),
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
ENGINE_MODELS = {
    UNIQUE_ID_GIGACHAT: MODELS_GIGACHAT,
    UNIQUE_ID_YANDEX_GPT: DEFAULT_MODELS_YANDEX_GPT,
    UNIQUE_ID_OPENAI: MODELS_OPENAI,
}
DEFAULT_MODEL = {
    ID_GIGACHAT: None,
    ID_OPENAI: "gpt-4.1-mini",
    ID_YANDEX_GPT: None,
}

CONF_LLM_HASS_API = "llm_hass_api"
CONF_API_KEY = "api_key"
CONF_FOLDER_ID = "folder_id"

MAX_TOOL_ITERATIONS = 10
