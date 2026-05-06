"""LLM client factory. Switches between the real `langchain-openai` chat
client and the deterministic stub based on settings.LLM_BACKEND."""

from __future__ import annotations

from typing import Protocol

from discogs_agent.config import settings
from discogs_agent.llm import stub as stub_module


class ChatLike(Protocol):
    """Minimal interface our nodes rely on. Both the real LangChain
    chat client and the stub conform to this."""

    def invoke(self, messages: list[dict[str, str]]) -> ChatResponse: ...


class ChatResponse(Protocol):
    """The output of `invoke()`. We rely only on `.content` (str) and
    `.usage` (token-count dict). Both real and stub provide them."""

    content: str
    usage: dict[str, int]


def get_chat_client(model_name: str) -> ChatLike:
    """Factory. Returns a stub for tests, real OpenAI client otherwise."""
    if settings.LLM_BACKEND == "stub":
        return stub_module.StubChatModel(model_name=model_name)
    # Lazy import — keeps the langchain-openai dep optional in tests.
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    return _LangChainChatAdapter(
        ChatOpenAI(
            model=model_name,
            api_key=SecretStr(settings.OPENAI_API_KEY),
            temperature=0.0,
        )
    )


class _LangChainChatAdapter:
    """Thin adapter over `langchain_openai.ChatOpenAI` exposing our
    `ChatLike` protocol."""

    def __init__(self, client: object) -> None:
        self._client = client
        self.model_name = getattr(client, "model_name", None) or getattr(client, "model", "unknown")

    def invoke(self, messages: list[dict[str, str]]) -> ChatResponse:
        # langchain expects a list of (role, content) tuples or message objects.
        from langchain_core.messages import (
            AIMessage,
            HumanMessage,
            SystemMessage,
        )

        lc_messages: list[object] = []
        for m in messages:
            role = m["role"]
            content = m["content"]
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        result = self._client.invoke(lc_messages)  # type: ignore[attr-defined]

        # Token counts from langchain's response metadata.
        usage_meta = getattr(result, "usage_metadata", None) or {}
        usage = {
            "prompt_tokens": int(usage_meta.get("input_tokens", 0)),
            "completion_tokens": int(usage_meta.get("output_tokens", 0)),
        }

        return _SimpleResponse(content=str(result.content), usage=usage)


class _SimpleResponse:
    def __init__(self, content: str, usage: dict[str, int]) -> None:
        self.content = content
        self.usage = usage
