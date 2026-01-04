"""
Ollama LLM Plugin for LiveKit Agents

Custom LLM plugin wrapping Ollama API for local GPU-accelerated
language model inference with multilingual support.

Author: C-3PO Team
Date: 2026-01-02
"""
import asyncio
import logging
import json
import aiohttp
from typing import Optional, List, Dict, Any
from livekit.agents import llm, utils, APIConnectionError, APIStatusError, APITimeoutError
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

logger = logging.getLogger(__name__)


class OllamaLLM(llm.LLM):
    """
    Ollama LLM plugin for LiveKit Agents.

    Wraps Ollama API (http://ollama:11434) to provide local GPU-accelerated
    language model inference for LiveKit voice agents.

    Implements LiveKit LLM interface with:
    - chat(): Messages → ChatStream
    - Supports streaming responses
    - Multilingual (FR/EN/ES)

    Supported models: qwen2.5:7b, llama3.2:3b, mistral, etc.
    """

    def __init__(
        self,
        url: str = "http://ollama:11434",
        model: str = "qwen2.5:7b",
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        max_tokens: int = 2048,
        http_session: Optional[aiohttp.ClientSession] = None
    ):
        """
        Initialize Ollama LLM plugin.

        Args:
            url: Ollama API endpoint
            model: Model name (qwen2.5:7b, llama3.2:3b, mistral)
            temperature: Sampling temperature (0.0-1.0)
            top_p: Nucleus sampling threshold
            top_k: Top-k sampling parameter
            max_tokens: Maximum tokens to generate
            http_session: Optional aiohttp ClientSession
        """
        super().__init__()

        self.url = url
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.max_tokens = max_tokens
        self._session = http_session

        logger.info(
            f"OllamaLLM initialized: model={model}, "
            f"temperature={temperature}, max_tokens={max_tokens}"
        )

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        """Close HTTP session on shutdown."""
        if self._session:
            await self._session.close()

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "OllamaChatStream":
        """
        Generate chat completion from conversation context.

        Args:
            chat_ctx: Conversation context with messages
            conn_options: API connection options

        Returns:
            OllamaChatStream instance

        Note: Function tools are handled automatically by the Agent.
        """
        return OllamaChatStream(
            llm=self,
            chat_ctx=chat_ctx,
            conn_options=conn_options,
        )


class OllamaChatStream(llm.LLMStream):
    """Generate chat completion using Ollama API with streaming support."""

    def __init__(
        self,
        *,
        llm: OllamaLLM,
        chat_ctx: llm.ChatContext,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(llm=llm, chat_ctx=chat_ctx, conn_options=conn_options)
        self._llm: OllamaLLM = llm

    def _convert_messages(self) -> List[Dict[str, str]]:
        """
        Convert LiveKit ChatContext to Ollama message format.

        Returns:
            List of Ollama-formatted messages
        """
        ollama_messages = []

        for msg in self._chat_ctx.messages:
            # Map LiveKit roles to Ollama roles
            role = "user" if msg.role == "user" else "assistant"

            if msg.role == "system":
                role = "system"

            # Combine all content into single text
            content_parts = []
            for content in msg.content:
                if isinstance(content, str):
                    content_parts.append(content)
                elif hasattr(content, "text"):
                    content_parts.append(content.text)

            if content_parts:
                ollama_messages.append({
                    "role": role,
                    "content": " ".join(content_parts)
                })

        return ollama_messages

    async def _run(self) -> None:
        """
        Execute LLM chat completion and emit events.
        """
        endpoint = f"{self._llm.url}/api/chat"

        # Convert messages to Ollama format
        messages = self._convert_messages()

        if not messages:
            logger.warning("Empty message list, skipping LLM request")
            return

        payload = {
            "model": self._llm.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self._llm.temperature,
                "top_p": self._llm.top_p,
                "top_k": self._llm.top_k,
                "num_predict": self._llm.max_tokens,
            }
        }

        logger.debug(
            f"Ollama LLM request: model={self._llm.model}, "
            f"messages={len(messages)}, stream=True"
        )

        try:
            async with self._llm._ensure_session().post(
                endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(
                    total=60,  # LLM can take longer
                    sock_connect=self._conn_options.timeout,
                ),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise APIStatusError(
                        message=f"Ollama LLM failed: {error_text}",
                        status_code=resp.status,
                        request_id=None,
                        body=None,
                    )

                # Stream NDJSON responses
                full_response = ""
                async for line in resp.content:
                    if not line:
                        continue

                    try:
                        chunk = json.loads(line.decode("utf-8"))

                        # Extract message content
                        message = chunk.get("message", {})
                        content = message.get("content", "")

                        if content:
                            full_response += content

                            # Emit content chunk
                            self._event_ch.send_nowait(
                                llm.ChatChunk(
                                    request_id=utils.shortuuid(),
                                    choices=[
                                        llm.Choice(
                                            delta=llm.ChoiceDelta(
                                                role="assistant",
                                                content=content
                                            ),
                                            index=0
                                        )
                                    ]
                                )
                            )

                        # Check if done
                        if chunk.get("done", False):
                            logger.info(
                                f"✓ LLM completed: {len(full_response)} chars "
                                f"(model={self._llm.model})"
                            )

                            # Emit final message
                            self._event_ch.send_nowait(
                                llm.ChatChunk(
                                    request_id=utils.shortuuid(),
                                    choices=[
                                        llm.Choice(
                                            delta=llm.ChoiceDelta(
                                                role="assistant",
                                                content=""
                                            ),
                                            index=0,
                                            finish_reason="stop"
                                        )
                                    ]
                                )
                            )
                            break

                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse Ollama chunk: {e}")
                        continue

        except asyncio.TimeoutError:
            raise APITimeoutError() from None
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=e.message,
                status_code=e.status,
                request_id=None,
                body=None,
            ) from None
        except aiohttp.ClientError as e:
            logger.error(f"Ollama API connection error: {e}")
            raise APIConnectionError() from e
        except Exception as e:
            logger.error(f"LLM chat completion error: {e}", exc_info=True)
            raise
