"""Keep LangChain's Yandex chat contract while avoiding SDK/protobuf conflicts.

Home Assistant 2026.10 requires protobuf 7; yandexcloud requires protobuf <7.
The parent supplies configuration and LangChain integration, while both request
paths use Yandex's REST API instead of importing yandexcloud at the first turn.
"""

from typing import Any

import httpx
from langchain_community.chat_models import ChatYandexGPT as _ChatYandexGPT
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

COMPLETION_URL = "https://ai.api.cloud.yandex.net/foundationModels/v1/completion"


def _retryable(error: BaseException) -> bool:
    return isinstance(error, httpx.TransportError) or (
        isinstance(error, httpx.HTTPStatusError)
        and (error.response.status_code == 429 or error.response.status_code >= 500)
    )


class ChatYandexGPT(_ChatYandexGPT):
    """Yandex chat using synchronous and asynchronous HTTP clients."""

    def _request_body(self, messages: list[BaseMessage]) -> dict[str, Any]:
        if not messages:
            raise ValueError("You should provide at least one message to start the chat!")
        roles = {SystemMessage: "system", HumanMessage: "user", AIMessage: "assistant"}
        history = []
        for message in messages:
            for message_type, role in roles.items():
                if isinstance(message, message_type):
                    history.append({"role": role, "text": message.content})
                    break
        return {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": self.temperature,
                "maxTokens": str(self.max_tokens),
            },
            "messages": history,
        }

    def _retry(self):
        return retry(
            reraise=True,
            stop=stop_after_attempt(max(1, self.max_retries)),
            wait=wait_exponential(min=self.sleep_interval, max=60),
            retry=retry_if_exception(_retryable),
        )

    @staticmethod
    def _result(response: httpx.Response, stop: list[str] | None) -> ChatResult:
        response.raise_for_status()
        text = response.json()["result"]["alternatives"][0]["message"]["text"]
        if stop:
            text = text[
                : min((text.find(token) for token in stop if token in text), default=len(text))
            ]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        body = self._request_body(messages)
        with httpx.Client(headers=dict(self.grpc_metadata or ()), timeout=60) as client:

            @self._retry()
            def request() -> ChatResult:
                return self._result(client.post(COMPLETION_URL, json=body), stop)

            return request()

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        body = self._request_body(messages)
        async with httpx.AsyncClient(headers=dict(self.grpc_metadata or ()), timeout=60) as client:

            @self._retry()
            async def request() -> ChatResult:
                return self._result(await client.post(COMPLETION_URL, json=body), stop)

            return await request()
