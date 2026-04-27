"""Conversation entity for SmartChain integration."""

import base64
import json
import logging
import time
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any, Literal

import voluptuous_openapi
from home_assistant_intents import get_languages
from homeassistant.components import conversation
from homeassistant.components.conversation import (
    ChatLog,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    Attachment,
    SystemContent,
    ToolResultContent,
    UserContent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import intent, llm, template
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from .const import (
    CONF_CHAT_HISTORY,
    CONF_ENABLE_HISTORY_TOOL,
    CONF_LLM_HASS_API,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    DEFAULT_CHAT_HISTORY,
    DEFAULT_DEVICES_PROMPT,
    DEFAULT_ENABLE_HISTORY_TOOL,
    DEFAULT_PROCESS_BUILTIN_SENTENCES,
    DEFAULT_PROMPT,
    DELEGATE_TOOL_NAME,
    DOMAIN,
    HISTORY_TOOL_NAME,
    MAX_TOOL_ITERATIONS,
    SUBENTRY_TYPE_CONVERSATION,
)
from .delegate_tool import (
    execute_delegate_tool,
    get_delegate_tool_definition,
)
from .history_tool import execute_history_tool, get_history_tool_definition
from .skills import load_skills, skills_to_prompt

LOGGER = logging.getLogger(__name__)
PROMPT_CACHE_TTL = 30  # seconds


async def async_setup_entry(
    hass,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up conversation entities."""
    entities: list[SmartChainConversationEntity] = []

    subentries = config_entry.subentries
    if subentries:
        for sub_id, subentry in subentries.items():
            if subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
                continue
            entities.append(
                SmartChainConversationEntity(
                    config_entry,
                    subentry_id=sub_id,
                    options=dict(subentry.data),
                )
            )
    else:
        # Legacy mode: single entity from entry.options
        entities.append(SmartChainConversationEntity(config_entry))

    async_add_entities(entities)


def _ha_tool_to_dict(tool: llm.Tool) -> dict[str, Any]:
    """Convert HA llm.Tool to dict for LangChain bind_tools."""
    parameters = voluptuous_openapi.convert(tool.parameters)
    return {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": parameters,
    }


class SmartChainConversationEntity(ConversationEntity):
    """SmartChain conversation entity using ConversationEntity API."""

    _attr_has_entity_name = True
    _attr_supports_streaming = True

    def __init__(
        self,
        entry: ConfigEntry,
        subentry_id: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the entity."""
        self.entry = entry
        self._subentry_id = subentry_id
        self._options = options or {}
        self._skills_prompt: str | None = None
        self._prompt_cache: str | None = None
        self._prompt_cache_key: str | None = None
        self._prompt_cache_time: float = 0.0

        if subentry_id:
            self._attr_unique_id = f"{entry.entry_id}_{subentry_id}"
            self._attr_name = entry.subentries[subentry_id].title
        else:
            self._attr_unique_id = entry.entry_id
            self._attr_name = None

    @property
    def _agent_options(self) -> dict[str, Any]:
        """Return the effective options for this agent."""
        if self._subentry_id:
            return self._options
        return dict(self.entry.options)

    @property
    def _client(self) -> Any:
        """Return the LLM client for this agent."""
        if self._subentry_id and isinstance(self.entry.runtime_data, dict):
            return self.entry.runtime_data[self._subentry_id]
        return self.entry.runtime_data

    @property
    def _sibling_agents(self) -> list[dict[str, str]]:
        """Return list of other agents in the same config entry (for delegation)."""
        if not self._subentry_id or not self.entry.subentries:
            return []
        agents = []
        for sub_id, subentry in self.entry.subentries.items():
            if sub_id == self._subentry_id:
                continue
            if subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
                continue
            agents.append({"name": subentry.title, "sub_id": sub_id})
        return agents

    @property
    def _agent_map(self) -> dict[str, str]:
        """Return mapping of agent_name -> subentry_id for delegation."""
        return {a["name"]: a["sub_id"] for a in self._sibling_agents}

    def _render_prompt_cached(self, raw_prompt: str) -> str:
        """Render Jinja2 prompt with TTL cache to avoid repeated template rendering."""
        now = time.monotonic()
        if (
            self._prompt_cache is not None
            and self._prompt_cache_key == raw_prompt
            and (now - self._prompt_cache_time) < PROMPT_CACHE_TTL
        ):
            return self._prompt_cache

        rendered = template.Template(raw_prompt, self.hass).async_render(
            {"ha_name": self.hass.config.location_name},
            parse_result=False,
        )
        self._prompt_cache = rendered
        self._prompt_cache_key = raw_prompt
        self._prompt_cache_time = now
        return rendered

    async def _async_get_skills_prompt(self) -> str:
        """Return cached skills prompt text. First call reads YAML files in executor."""
        if self._skills_prompt is None:
            skills = await self.hass.async_add_executor_job(
                load_skills, self.hass.config.config_dir
            )
            self._skills_prompt = skills_to_prompt(skills)
        return self._skills_prompt

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return get_languages()

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
    ) -> ConversationResult:
        """Handle a conversation message via ChatLog API."""
        options = self._agent_options
        llm_hass_api = options.get(CONF_LLM_HASS_API)
        user_prompt = options.get(CONF_PROMPT, DEFAULT_PROMPT)

        if llm_hass_api:
            try:
                await chat_log.async_provide_llm_data(
                    user_input.as_llm_context(DOMAIN),
                    llm_hass_api,
                    user_prompt,
                    user_input.extra_system_prompt,
                )
            except conversation.ConverseError as err:
                return err.as_conversation_result()
        else:
            raw_prompt = user_prompt + DEFAULT_DEVICES_PROMPT
            prompt = self._render_prompt_cached(raw_prompt)
            chat_log.content[0] = SystemContent(content=prompt)

        # Append skills prompt to system message
        skills_text = await self._async_get_skills_prompt()
        if skills_text and isinstance(chat_log.content[0], SystemContent):
            chat_log.content[0] = SystemContent(content=chat_log.content[0].content + skills_text)

        use_builtin = options.get(CONF_PROCESS_BUILTIN_SENTENCES, DEFAULT_PROCESS_BUILTIN_SENTENCES)
        if use_builtin and not llm_hass_api:
            from homeassistant.components.conversation import agent_manager

            default_agent = agent_manager.async_get_agent(self.hass, None)
            default_response = await default_agent.async_process(user_input)

            if default_response.response.intent:
                speech = default_response.response.speech.get("plain", {}).get("speech", "")
                chat_log.async_add_assistant_content_without_tools(
                    AssistantContent(
                        agent_id=user_input.agent_id,
                        content=speech,
                    )
                )
                return default_response

        client = self._client
        tools: list[dict[str, Any]] = (
            [_ha_tool_to_dict(tool) for tool in chat_log.llm_api.tools] if chat_log.llm_api else []
        )

        # Add history tool if enabled
        history_enabled = options.get(CONF_ENABLE_HISTORY_TOOL, DEFAULT_ENABLE_HISTORY_TOOL)
        if history_enabled:
            tools.append(get_history_tool_definition())

        # Add delegate tool if there are sibling agents
        sibling_agents = self._sibling_agents
        if sibling_agents:
            tools.append(get_delegate_tool_definition(sibling_agents))

        bound_client = client.bind_tools(tools) if tools else client

        for _iteration in range(MAX_TOOL_ITERATIONS):
            chat_history_enabled = options.get(CONF_CHAT_HISTORY, DEFAULT_CHAT_HISTORY)
            if chat_history_enabled:
                # _chatlog_to_langchain may read attachment files and run TurboJPEG —
                # both blocking. Offload to executor when attachments are present.
                if any(isinstance(c, UserContent) and c.attachments for c in chat_log.content):
                    messages = await self.hass.async_add_executor_job(
                        _chatlog_to_langchain, chat_log
                    )
                else:
                    messages = _chatlog_to_langchain(chat_log)
            else:
                messages = [
                    SystemMessage(content=chat_log.content[0].content),
                    HumanMessage(content=user_input.text),
                ]

            try:
                async for _content in chat_log.async_add_delta_content_stream(
                    user_input.agent_id,
                    _async_langchain_stream(bound_client, messages),
                ):
                    pass
            except Exception as err:
                LOGGER.exception("Unexpected exception %s", type(err))
                response = intent.IntentResponse(language=user_input.language)
                response.async_set_error(
                    intent.IntentResponseErrorCode.UNKNOWN,
                    f"Houston we have a problem: {err}",
                )
                return ConversationResult(
                    conversation_id=chat_log.conversation_id, response=response
                )

            # Handle custom tool calls (marked as external)
            if history_enabled:
                await _handle_history_tool_calls(self.hass, chat_log, user_input.agent_id)
            if sibling_agents:
                rd = self.entry.runtime_data
                clients = rd if isinstance(rd, dict) else {}
                await _handle_delegate_tool_calls(
                    clients, self._agent_map, chat_log, user_input.agent_id
                )

            if not chat_log.unresponded_tool_results:
                break

        return conversation.async_get_result_from_chat_log(user_input, chat_log)


def _attachment_to_base64(attachment: Attachment) -> str | None:
    """Read an attachment file and return base64-encoded data URL."""
    path = Path(attachment.path)
    if not path.exists():
        LOGGER.warning("Attachment file not found: %s", path)
        return None

    try:
        image_data = path.read_bytes()
    except OSError as err:
        LOGGER.warning("Failed to read attachment %s: %s", path, err)
        return None

    # Optional: compress large images with PyTurboJPEG
    mime = attachment.mime_type or "image/jpeg"
    if mime.startswith("image/") and len(image_data) > 512 * 1024:
        try:
            from turbojpeg import TurboJPEG

            jpeg = TurboJPEG()
            image_data = jpeg.encode(
                jpeg.decode(image_data),
                quality=80,
            )
            mime = "image/jpeg"
        except Exception:
            pass  # Use original image if compression fails

    encoded = base64.b64encode(image_data).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def _chatlog_to_langchain(chat_log: ChatLog) -> list[BaseMessage]:
    """Convert ChatLog content to LangChain message list."""
    messages: list[BaseMessage] = []
    for content in chat_log.content:
        if isinstance(content, SystemContent):
            messages.append(SystemMessage(content=content.content))
        elif isinstance(content, UserContent):
            if content.attachments:
                # Multimodal message: text + images
                parts: list[dict[str, Any]] = []
                if content.content:
                    parts.append({"type": "text", "text": content.content})
                for att in content.attachments:
                    if att.mime_type and att.mime_type.startswith("image/"):
                        data_url = _attachment_to_base64(att)
                        if data_url:
                            parts.append({"type": "image_url", "image_url": {"url": data_url}})
                messages.append(HumanMessage(content=parts if parts else content.content))
            else:
                messages.append(HumanMessage(content=content.content))
        elif isinstance(content, AssistantContent):
            if content.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "name": tc.tool_name,
                        "args": tc.tool_args,
                    }
                    for tc in content.tool_calls
                ]
                messages.append(
                    AIMessage(
                        content=content.content or "",
                        tool_calls=tool_calls,
                    )
                )
            elif content.content:
                messages.append(AIMessage(content=content.content))
        elif isinstance(content, ToolResultContent):
            messages.append(
                ToolMessage(
                    content=json.dumps(content.tool_result),
                    tool_call_id=content.tool_call_id,
                    name=content.tool_name,
                )
            )
    return messages


async def _handle_history_tool_calls(hass, chat_log: ChatLog, agent_id: str) -> None:
    """Execute pending history tool calls and add results to chat_log."""
    for content in chat_log.content:
        if not isinstance(content, AssistantContent) or not content.tool_calls:
            continue
        for tc in content.tool_calls:
            if tc.tool_name != HISTORY_TOOL_NAME or not tc.external:
                continue
            # Check if result already exists
            has_result = any(
                isinstance(c, ToolResultContent) and c.tool_call_id == tc.id
                for c in chat_log.content
            )
            if has_result:
                continue
            result = await execute_history_tool(
                hass,
                tc.tool_args.get("entity_id", ""),
                tc.tool_args.get("hours", 1.0),
            )
            chat_log.async_add_assistant_content_without_tools(
                ToolResultContent(
                    agent_id=agent_id,
                    tool_call_id=tc.id,
                    tool_name=HISTORY_TOOL_NAME,
                    tool_result=result,
                )
            )


async def _handle_delegate_tool_calls(
    clients: dict[str, object],
    agent_map: dict[str, str],
    chat_log: ChatLog,
    agent_id: str,
) -> None:
    """Execute pending delegate tool calls and add results to chat_log."""
    for content in chat_log.content:
        if not isinstance(content, AssistantContent) or not content.tool_calls:
            continue
        for tc in content.tool_calls:
            if tc.tool_name != DELEGATE_TOOL_NAME or not tc.external:
                continue
            has_result = any(
                isinstance(c, ToolResultContent) and c.tool_call_id == tc.id
                for c in chat_log.content
            )
            if has_result:
                continue
            result = await execute_delegate_tool(
                clients,
                agent_map,
                tc.tool_args.get("agent_name", ""),
                tc.tool_args.get("message", ""),
            )
            chat_log.async_add_assistant_content_without_tools(
                ToolResultContent(
                    agent_id=agent_id,
                    tool_call_id=tc.id,
                    tool_name=DELEGATE_TOOL_NAME,
                    tool_result=result,
                )
            )


async def _async_langchain_stream(
    client: Any, messages: list[BaseMessage]
) -> AsyncIterable[dict[str, Any]]:
    """Convert LangChain astream chunks to HA delta dicts."""
    first = True
    async for chunk in client.astream(messages):
        delta: dict[str, Any] = {}
        if first:
            delta["role"] = "assistant"
            first = False
        if chunk.content:
            delta["content"] = chunk.content

        if chunk.tool_calls:
            delta["tool_calls"] = [
                llm.ToolInput(
                    tool_name=tc["name"],
                    tool_args=tc["args"],
                    id=tc["id"],
                    external=(tc["name"] in (HISTORY_TOOL_NAME, DELEGATE_TOOL_NAME)),
                )
                for tc in chunk.tool_calls
            ]

        if delta:
            yield delta
