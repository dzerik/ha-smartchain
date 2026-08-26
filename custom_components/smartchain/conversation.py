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
from homeassistant.util import dt as dt_util
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from .const import (
    CONF_CHAT_HISTORY,
    CONF_DYNAMIC_CONTEXT_ON_ASSIST,
    CONF_DYNAMIC_CONTEXT_PRESET,
    CONF_DYNAMIC_ENTITY_CONTEXT,
    CONF_LLM_HASS_API,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    CRITIQUE_TOOL_NAME,
    DEFAULT_CHAT_HISTORY,
    DEFAULT_DEVICES_PROMPT,
    DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST,
    DEFAULT_DYNAMIC_ENTITY_CONTEXT,
    DEFAULT_PROCESS_BUILTIN_SENTENCES,
    DEFAULT_PROMPT,
    DELEGATE_MANY_TOOL_NAME,
    DELEGATE_TOOL_NAME,
    DOMAIN,
    ENTITY_DEFAULT_PRESET,
    ENTITY_SEARCH_DEFAULT_TOP_K,
    ENTITY_TOOL_NAME,
    HISTORY_TOOL_NAME,
    MAX_TOOL_ITERATIONS,
    MEMORY_TOOL_NAME,
    SUBENTRY_TYPE_CONVERSATION,
)
from .delegate_tool import (
    execute_delegate_tool,
    get_delegate_tool_definition,
)
from .history_tool import execute_history_tool, get_history_tool_definition
from .skills import load_skills, skills_to_prompt
from .tools import CustomTool, ToolRegistry
from .tools.critique_tool import (
    execute_critique_tool,
    get_critique_tool_definition,
)
from .tools.delegate_many_tool import (
    execute_delegate_many_tool,
    get_delegate_many_tool_definition,
)
from .tools.dispatcher import dispatch as dispatch_custom_tool
from .tools.inventory import (
    builtin_admitted,
    builtin_tool_names,
    custom_admitted,
    custom_tools_for,
    sibling_agents,
)
from .tools.memory.entity_context import build_entity_context, build_retrieved_context
from .tools.memory.entity_tool import (
    execute_entity_search,
    get_entity_tool_definition,
)
from .tools.memory.ingest import ingest_conversation_turn
from .tools.memory.registry import MemoryRegistry
from .tools.memory.search_tool import (
    execute_memory_search,
    get_memory_tool_definition,
)

LOGGER = logging.getLogger(__name__)
PROMPT_CACHE_TTL = 30  # seconds


async def async_setup_entry(
    hass,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up conversation entities."""
    entities: list[SmartChainConversationEntity] = []

    for sub_id, subentry in (config_entry.subentries or {}).items():
        if subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
            continue
        entities.append(
            SmartChainConversationEntity(
                config_entry,
                subentry_id=sub_id,
                options=dict(subentry.data),
            )
        )

    if not entities and config_entry.minor_version < 2:
        # Only an entry whose migration refused stays below minor version 2
        # (see `__init__._migrate_legacy_agent`). It keeps its single legacy
        # entity rather than losing it; an entry with no agents and no refused
        # migration is a connection nobody is using yet and gets no entity.
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
        self._options = options if options is not None else {}
        self._options_explicit = options is not None
        self._skills_prompt: str | None = None
        self._prompt_cache: str | None = None
        self._prompt_cache_key: str | None = None
        self._prompt_cache_time: float = 0.0

        if subentry_id:
            self._attr_unique_id = f"{entry.entry_id}_{subentry_id}"
            subentry = (entry.subentries or {}).get(subentry_id)
            self._attr_name = subentry.title if subentry is not None else subentry_id
        else:
            self._attr_unique_id = entry.entry_id
            self._attr_name = None

    @property
    def _agent_options(self) -> dict[str, Any]:
        """Return the effective options for this agent."""
        if self._subentry_id or self._options_explicit:
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
        cache = getattr(self, "_sibling_agents_cache", None)
        if cache is not None:
            return cache
        return sibling_agents(self.entry, self._subentry_id)

    @property
    def _agent_map(self) -> dict[str, str]:
        """Return mapping of agent_name -> subentry_id for delegation."""
        return {a["name"]: a["sub_id"] for a in self._sibling_agents}

    def _collect_custom_tools(self, registry: ToolRegistry) -> list[CustomTool]:
        """Return registry tools allowed for this agent.

        The admission rule itself lives in `tools/inventory.py`, so that the
        tools this agent is bound with and the tools the panel reports for it
        are decided by the same function. This wrapper only supplies the
        registry, and exists because a caller with a registry in hand should
        not have to reach into `hass.data` to filter it.
        """
        return [tool for tool in registry.all() if custom_admitted(self._agent_options, tool.name)]

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

    async def _build_system_prompt(
        self, options: dict[str, Any], user_input: ConversationInput
    ) -> str:
        """Compose the system prompt for a turn without the Assist API.

        With `dynamic_entity_context` off, or when the skeleton could not be
        built, this reproduces today's prompt byte-for-byte through the same
        cache — both cases mean: behave exactly as this integration always
        has. Only the user prompt is a template; the context is plain text
        and varies per turn, so running Jinja over the pair would bust the
        cache on every message for no gain.
        """
        user_prompt = options.get(CONF_PROMPT, DEFAULT_PROMPT)
        dynamic = options.get(CONF_DYNAMIC_ENTITY_CONTEXT, DEFAULT_DYNAMIC_ENTITY_CONTEXT)
        context = None
        if dynamic:
            context = await build_entity_context(
                self.hass,
                preset=options.get(CONF_DYNAMIC_CONTEXT_PRESET, ENTITY_DEFAULT_PRESET),
                query=user_input.text or "",
            )

        if context is None:
            raw_prompt = user_prompt + DEFAULT_DEVICES_PROMPT
            return self._render_prompt_cached(raw_prompt)

        prompt = self._render_prompt_cached(user_prompt)
        if context:
            prompt = f"{prompt}\n\n{context}"
        return prompt

    async def _build_extra_system_prompt(
        self, options: dict[str, Any], user_input: ConversationInput
    ) -> str | None:
        """Compose `extra_system_prompt` for a turn that goes through Assist.

        With the Assist API, Home Assistant already injects its own exposed-
        entity list and control tools; adding our skeleton on top would
        duplicate it and grow a prompt we have no way to shrink. So this path
        adds only the retrieved block — the semantic hits a name-based
        exposure list does not surface — and only when the option is on.

        `user_input.extra_system_prompt` may already hold the user's own
        text. Off, or a retrieval that yields (or fails into) nothing, must
        return it completely unchanged — not "", not None coerced to
        something else — since it is handed straight to
        `async_provide_llm_data` as the fourth argument.

        `build_retrieved_context` is documented to never raise — it returns
        "" on any internal failure — so this trusts that contract the same
        way `_build_system_prompt` trusts `build_entity_context`'s, rather
        than wrapping it in a second guard that would silently mask a
        regression in the callee's own.

        Both switches must be on. `dynamic_entity_context` is the master
        switch for the whole feature and is documented as the one checkbox
        that restores the pre-v5.0.0 behaviour; an Assist extension that kept
        injecting a retrieved block after it was unticked would make that
        promise false on exactly the path the user is most likely to be on.
        """
        if not options.get(CONF_DYNAMIC_ENTITY_CONTEXT, DEFAULT_DYNAMIC_ENTITY_CONTEXT):
            return user_input.extra_system_prompt
        if not options.get(CONF_DYNAMIC_CONTEXT_ON_ASSIST, DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST):
            return user_input.extra_system_prompt

        block = await build_retrieved_context(
            self.hass,
            preset=options.get(CONF_DYNAMIC_CONTEXT_PRESET, ENTITY_DEFAULT_PRESET),
            query=user_input.text or "",
        )
        if not block:
            return user_input.extra_system_prompt

        extra = user_input.extra_system_prompt or ""
        return f"{extra}\n\n{block}" if extra else block

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
            extra_system_prompt = await self._build_extra_system_prompt(options, user_input)
            try:
                await chat_log.async_provide_llm_data(
                    user_input.as_llm_context(DOMAIN),
                    llm_hass_api,
                    user_prompt,
                    extra_system_prompt,
                )
            except conversation.ConverseError as err:
                return err.as_conversation_result()
        else:
            prompt = await self._build_system_prompt(options, user_input)
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

        # Which built-ins this agent gets is decided in exactly one place —
        # tools/inventory.py — so that `smartchain/agent/tools` reports the set
        # that is actually bound here rather than a second guess at it.
        siblings = self._sibling_agents
        builtin_names = builtin_tool_names(self.hass, self.entry, self._subentry_id, options)

        history_enabled = HISTORY_TOOL_NAME in builtin_names
        if history_enabled:
            tools.append(get_history_tool_definition())

        if DELEGATE_TOOL_NAME in builtin_names:
            tools.append(get_delegate_tool_definition(siblings))

        # `ask_agents` and `critique_response` shared one switch and now hold
        # one list entry each, so they are tracked apart: an agent may fan out
        # without also being allowed to ask for a second opinion.
        delegate_many_enabled = DELEGATE_MANY_TOOL_NAME in builtin_names
        critique_enabled = CRITIQUE_TOOL_NAME in builtin_names
        if delegate_many_enabled:
            tools.append(get_delegate_many_tool_definition(siblings))
        if critique_enabled:
            tools.append(get_critique_tool_definition(siblings))

        memory_registry: MemoryRegistry | None = self.hass.data.get(DOMAIN, {}).get("memory")
        memory_enabled = MEMORY_TOOL_NAME in builtin_names
        if memory_enabled:
            tools.append(get_memory_tool_definition(memory_registry))

        entity_enabled = ENTITY_TOOL_NAME in builtin_names
        if entity_enabled:
            tools.append(get_entity_tool_definition(memory_registry))

        custom_tools = custom_tools_for(self.hass, options)
        if custom_tools:
            tools.extend(t.to_llm_schema() for t in custom_tools)
        bound_client = client.bind_tools(tools) if tools else client
        custom_by_name: dict[str, CustomTool] = {t.name: t for t in custom_tools}

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
                _extra_external: frozenset[str] = (
                    frozenset({MEMORY_TOOL_NAME}) if memory_enabled else frozenset()
                )
                if entity_enabled:
                    _extra_external |= {ENTITY_TOOL_NAME}
                if delegate_many_enabled:
                    _extra_external |= {DELEGATE_MANY_TOOL_NAME}
                if critique_enabled:
                    _extra_external |= {CRITIQUE_TOOL_NAME}
                async for _content in chat_log.async_add_delta_content_stream(
                    user_input.agent_id,
                    _async_langchain_stream(
                        bound_client,
                        messages,
                        frozenset(custom_by_name) | _extra_external,
                    ),
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
            if memory_enabled:
                for content in list(chat_log.content):
                    if not isinstance(content, AssistantContent) or not content.tool_calls:
                        continue
                    for tc in content.tool_calls:
                        if tc.tool_name != MEMORY_TOOL_NAME or not tc.external:
                            continue
                        if any(
                            isinstance(c, ToolResultContent) and c.tool_call_id == tc.id
                            for c in chat_log.content
                        ):
                            continue
                        args = tc.tool_args or {}
                        try:
                            result_text = await execute_memory_search(
                                self.hass,
                                query=args.get("query", ""),
                                top_k=int(args.get("top_k", 5)),
                                kind=str(args.get("kind", "any")),
                                subentry_id=self._subentry_id,
                                store=args.get("store"),
                            )
                        except Exception:
                            LOGGER.exception("search_memory dispatch failed")
                            result_text = "Memory lookup failed; see logs."
                        chat_log.async_add_assistant_content_without_tools(
                            ToolResultContent(
                                agent_id=user_input.agent_id,
                                tool_call_id=tc.id,
                                tool_name=tc.tool_name,
                                tool_result=result_text,
                            )
                        )
            if entity_enabled:
                for content in list(chat_log.content):
                    if not isinstance(content, AssistantContent) or not content.tool_calls:
                        continue
                    for tc in content.tool_calls:
                        if tc.tool_name != ENTITY_TOOL_NAME or not tc.external:
                            continue
                        if any(
                            isinstance(c, ToolResultContent) and c.tool_call_id == tc.id
                            for c in chat_log.content
                        ):
                            continue
                        args = tc.tool_args or {}
                        try:
                            result_text = await execute_entity_search(
                                self.hass,
                                query=args.get("query", ""),
                                top_k=int(args.get("top_k", ENTITY_SEARCH_DEFAULT_TOP_K)),
                                domain=args.get("domain"),
                                area=args.get("area"),
                                state=args.get("state"),
                                store=args.get("store"),
                            )
                        except Exception:
                            LOGGER.exception("search_entities dispatch failed")
                            result_text = "Entity lookup failed; see logs."
                        chat_log.async_add_assistant_content_without_tools(
                            ToolResultContent(
                                agent_id=user_input.agent_id,
                                tool_call_id=tc.id,
                                tool_name=tc.tool_name,
                                tool_result=result_text,
                            )
                        )
            if siblings:
                rd = self.entry.runtime_data
                clients = rd if isinstance(rd, dict) else {}
                if DELEGATE_TOOL_NAME in builtin_names:
                    await _handle_delegate_tool_calls(
                        clients, self._agent_map, chat_log, user_input.agent_id
                    )
                if delegate_many_enabled:
                    await _handle_delegate_many_tool_calls(
                        clients, self._agent_map, chat_log, user_input.agent_id
                    )
                if critique_enabled:
                    await _handle_critique_tool_calls(
                        clients, self._agent_map, chat_log, user_input.agent_id
                    )

            # Handle YAML-defined custom-tool calls.
            if custom_by_name:
                for content in list(chat_log.content):
                    if not isinstance(content, AssistantContent) or not content.tool_calls:
                        continue
                    for tc in content.tool_calls:
                        if tc.tool_name not in custom_by_name or not tc.external:
                            continue
                        if any(
                            isinstance(c, ToolResultContent) and c.tool_call_id == tc.id
                            for c in chat_log.content
                        ):
                            continue
                        tool_result = await dispatch_custom_tool(
                            self.hass, custom_by_name[tc.tool_name], tc.tool_args
                        )
                        chat_log.async_add_assistant_content_without_tools(
                            ToolResultContent(
                                agent_id=user_input.agent_id,
                                tool_call_id=tc.id,
                                tool_name=tc.tool_name,
                                tool_result=tool_result,
                            )
                        )

            if not chat_log.unresponded_tool_results:
                break

        if memory_enabled:
            ingest_targets = memory_registry.stores_for_conversation_ingest()
            assistant_text = ""
            for content in reversed(chat_log.content):
                if isinstance(content, AssistantContent) and content.content:
                    assistant_text = content.content
                    break
            if assistant_text and ingest_targets:
                self.hass.async_create_background_task(
                    ingest_conversation_turn(
                        ingest_targets,
                        user_text=user_input.text or "",
                        assistant_text=assistant_text,
                        metadata={
                            "kind": "conversation",
                            "timestamp": dt_util.utcnow().isoformat(),
                            "agent_id": user_input.agent_id,
                            "subentry_id": self._subentry_id or "",
                            "conversation_id": chat_log.conversation_id,
                        },
                    ),
                    name="smartchain_memory_ingest",
                )

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


async def _handle_delegate_many_tool_calls(
    clients: dict,
    agent_map: dict[str, str],
    chat_log: ChatLog,
    agent_id: str,
) -> None:
    """Run pending ask_agents tool calls and append their results."""
    for content in list(chat_log.content):
        if not isinstance(content, AssistantContent) or not content.tool_calls:
            continue
        for tc in content.tool_calls:
            if tc.tool_name != DELEGATE_MANY_TOOL_NAME or not tc.external:
                continue
            if any(
                isinstance(c, ToolResultContent) and c.tool_call_id == tc.id
                for c in chat_log.content
            ):
                continue
            args = tc.tool_args or {}
            try:
                result_text = await execute_delegate_many_tool(
                    clients,
                    agent_map,
                    list(args.get("agents", [])),
                    str(args.get("query", "")),
                )
            except Exception:
                LOGGER.exception("ask_agents dispatch failed")
                result_text = "Tool execution failed; check Home Assistant logs."
            chat_log.async_add_assistant_content_without_tools(
                ToolResultContent(
                    agent_id=agent_id,
                    tool_call_id=tc.id,
                    tool_name=tc.tool_name,
                    tool_result=result_text,
                )
            )


async def _handle_critique_tool_calls(
    clients: dict,
    agent_map: dict[str, str],
    chat_log: ChatLog,
    agent_id: str,
) -> None:
    """Run pending critique_response tool calls and append their results."""
    for content in list(chat_log.content):
        if not isinstance(content, AssistantContent) or not content.tool_calls:
            continue
        for tc in content.tool_calls:
            if tc.tool_name != CRITIQUE_TOOL_NAME or not tc.external:
                continue
            if any(
                isinstance(c, ToolResultContent) and c.tool_call_id == tc.id
                for c in chat_log.content
            ):
                continue
            args = tc.tool_args or {}
            try:
                result_text = await execute_critique_tool(
                    clients,
                    agent_map,
                    str(args.get("reviewer", "")),
                    str(args.get("original_question", "")),
                    str(args.get("candidate_answer", "")),
                )
            except Exception:
                LOGGER.exception("critique_response dispatch failed")
                result_text = "Tool execution failed; check Home Assistant logs."
            chat_log.async_add_assistant_content_without_tools(
                ToolResultContent(
                    agent_id=agent_id,
                    tool_call_id=tc.id,
                    tool_name=tc.tool_name,
                    tool_result=result_text,
                )
            )


async def _async_langchain_stream(
    client: Any,
    messages: list[BaseMessage],
    external_tool_names: frozenset[str] = frozenset(),
) -> AsyncIterable[dict[str, Any]]:
    """Convert LangChain astream chunks to HA delta dicts."""
    _external = external_tool_names | {HISTORY_TOOL_NAME, DELEGATE_TOOL_NAME}
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
                    external=(tc["name"] in _external),
                )
                for tc in chunk.tool_calls
            ]

        if delta:
            yield delta


def _collect_multi_agent_tool_names(
    entity: "SmartChainConversationEntity",
) -> list[str]:
    """Return the names of multi-agent tools this entity would expose right now.

    Answers the question for an *entity*, whose sibling list may be stubbed;
    `tools.inventory.builtin_tool_names` answers it for a config entry, which
    is what `_async_handle_message` and the panel use. Both defer to
    `builtin_admitted` for the admission rule, so the two cannot disagree about
    whether the agent is allowed these tools — only about who its siblings are.
    """
    if not entity._sibling_agents:
        return []
    options = entity._agent_options
    return [
        name
        for name in (DELEGATE_MANY_TOOL_NAME, CRITIQUE_TOOL_NAME)
        if builtin_admitted(options, name)
    ]
