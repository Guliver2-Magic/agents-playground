"""
Faster-Whisper STT Plugin for LiveKit Agents

Custom STT plugin wrapping Faster-Whisper API for local GPU-accelerated
speech-to-text transcription with multilingual support.

Author: C-3PO Team
Date: 2026-01-02
"""
import asyncio
import logging
import aiohttp
from typing import Optional
from livekit.agents import stt, utils, APIConnectionError, APIStatusError, APITimeoutError
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

logger = logging.getLogger(__name__)


class WhisperSTT(stt.STT):
    """
    Faster-Whisper STT plugin for LiveKit Agents.

    Wraps Faster-Whisper API (http://faster-whisper:8000) to provide
    local GPU-accelerated speech recognition for LiveKit voice agents.

    Implements LiveKit STT interface with:
    - recognize(): Audio → SpeechStream
    - stream(): Streaming STT support

    Supported languages: French, English, Spanish (auto-detection)
    Model: large-v3 (GPU-optimized)
    """

    def __init__(
        self,
        url: str = "http://faster-whisper:8000",
        language: Optional[str] = None,  # None = auto-detect
        model: str = "large-v3",
        temperature: float = 0.0,
        vad_filter: bool = True,
        word_timestamps: bool = False,
        http_session: Optional[aiohttp.ClientSession] = None
    ):
        """
        Initialize Faster-Whisper STT plugin.

        Args:
            url: Faster-Whisper API endpoint
            language: Language code (fr, en, es) or None for auto-detection
            model: Whisper model name (large-v3 recommended)
            temperature: Sampling temperature (0.0 = deterministic)
            vad_filter: Enable Voice Activity Detection filtering
            word_timestamps: Include word-level timestamps
            http_session: Optional aiohttp ClientSession
        """
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,  # Faster-Whisper supports streaming
                interim_results=False  # Only final results for now
            )
        )

        self.url = url
        self.language = language
        self.model = model
        self.temperature = temperature
        self.vad_filter = vad_filter
        self.word_timestamps = word_timestamps
        self._session = http_session

        logger.info(
            f"WhisperSTT initialized: model={model}, "
            f"language={language or 'auto-detect'}, vad_filter={vad_filter}"
        )

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        """Close HTTP session on shutdown."""
        if self._session:
            await self._session.close()

    def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: Optional[str] = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "WhisperRecognizeStream":
        """
        Internal method to recognize speech from audio buffer.

        Called by the base STT.recognize() method.

        Args:
            buffer: Audio buffer to transcribe
            language: Override language (fr, en, es) or None for auto-detect
            conn_options: API connection options

        Returns:
            WhisperRecognizeStream instance
        """
        return WhisperRecognizeStream(
            stt=self,
            buffer=buffer,
            language=language or self.language,
            conn_options=conn_options,
        )


class WhisperRecognizeStream(stt.SpeechStream):
    """Recognize speech from audio buffer using Faster-Whisper API."""

    def __init__(
        self,
        *,
        stt: WhisperSTT,
        buffer: utils.AudioBuffer,
        language: Optional[str],
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(stt=stt, conn_options=conn_options)
        self._stt: WhisperSTT = stt
        self._buffer = buffer
        self._language = language

    async def _run(self) -> None:
        """
        Execute STT recognition and emit events.
        """
        endpoint = f"{self._stt.url}/v1/audio/transcriptions"

        # Convert audio buffer to WAV bytes
        audio_bytes = self._buffer.tobytes()

        # Prepare multipart form data
        data = aiohttp.FormData()
        data.add_field(
            "file",
            audio_bytes,
            filename="audio.wav",
            content_type="audio/wav"
        )
        data.add_field("model", self._stt.model)

        if self._language:
            data.add_field("language", self._language)

        data.add_field("temperature", str(self._stt.temperature))
        data.add_field("vad_filter", str(self._stt.vad_filter).lower())
        data.add_field("response_format", "json")

        if self._stt.word_timestamps:
            data.add_field("timestamp_granularities[]", "word")

        logger.debug(
            f"Whisper STT request: audio_len={len(audio_bytes)}, "
            f"language={self._language or 'auto'}"
        )

        try:
            async with self._stt._ensure_session().post(
                endpoint,
                data=data,
                timeout=aiohttp.ClientTimeout(
                    total=30,
                    sock_connect=self._conn_options.timeout,
                ),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise APIStatusError(
                        message=f"Faster-Whisper STT failed: {error_text}",
                        status_code=resp.status,
                        request_id=None,
                        body=None,
                    )

                result = await resp.json()

                # Extract transcript and language
                transcript = result.get("text", "").strip()
                detected_language = result.get("language", self._language)

                if not transcript:
                    logger.debug("Empty transcript received from Whisper")
                    return

                logger.info(
                    f"✓ STT transcribed: '{transcript[:50]}...' "
                    f"(language={detected_language})"
                )

                # Create final speech event
                event = stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=[
                        stt.SpeechData(
                            text=transcript,
                            language=detected_language,
                            confidence=result.get("confidence", 1.0)
                        )
                    ]
                )

                # Emit event
                self._event_ch.send_nowait(event)

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
            logger.error(f"Faster-Whisper API connection error: {e}")
            raise APIConnectionError() from e
        except Exception as e:
            logger.error(f"STT recognition error: {e}", exc_info=True)
            raise
