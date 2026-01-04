"""
Fish Speech TTS Plugin for LiveKit Agents

Custom TTS plugin wrapping Fish Speech API (OpenAudio S1-mini) for
SOTA voice cloning with ~2s latency and 112 tokens/sec generation.

Fish Speech: https://github.com/fishaudio/fish-speech
Model: OpenAudio S1-mini (0.5B parameters, CC-BY-NC-SA-4.0)

Author: C-3PO Team
Date: 2026-01-03
"""
import asyncio
import logging
import aiohttp
from typing import Optional, Union
from livekit.agents import tts, utils
from livekit.agents._exceptions import APIConnectionError, APIStatusError, APITimeoutError
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

logger = logging.getLogger(__name__)


class FishTTS(tts.TTS):
    """
    Fish Speech TTS plugin for LiveKit Agents.

    Wraps Fish Speech HTTP API (http://localhost:8009) to provide
    SOTA voice cloning with ~2s latency for LiveKit voice agents.

    Implements LiveKit TTS interface with:
    - stream(): Returns FishSynthesizeStream for streaming text input
    - synthesize(): Returns FishChunkedStream for one-shot synthesis

    Features:
    - Voice cloning from 10-30s reference audio
    - 112+ tokens/sec generation (RTX 4090)
    - 44.1kHz WAV output
    - Multilingual: EN, FR, ES, DE, JA, ZH, etc.
    - Emotion markers: (excited), (sad), (whisper), etc.
    """

    def __init__(
        self,
        url: str = "http://fish-speech-server:8080",
        reference_id: Optional[str] = None,
        reference_audio: Optional[str] = None,
        reference_text: Optional[str] = None,
        sample_rate: int = 44100,
        max_new_tokens: int = 1024,
        top_p: float = 0.7,
        temperature: float = 0.7,
        repetition_penalty: float = 1.2,
        http_session: Optional[aiohttp.ClientSession] = None
    ):
        """
        Initialize Fish Speech TTS plugin.

        Args:
            url: Fish Speech API endpoint
            reference_id: Pre-registered reference ID (optional)
            reference_audio: Path to reference audio WAV (10-30s)
            reference_text: Transcript of reference audio
            sample_rate: Output sample rate (44100 for Fish Speech)
            max_new_tokens: Max tokens to generate
            top_p: Nucleus sampling threshold
            temperature: Generation temperature
            repetition_penalty: Repetition penalty factor
            http_session: Optional aiohttp ClientSession
        """
        super().__init__(
            capabilities=tts.TTSCapabilities(
                streaming=True  # We implement stream() for LiveKit voice agent
            ),
            sample_rate=sample_rate,
            num_channels=1
        )

        self.url = url
        self.reference_id = reference_id
        self.reference_audio = reference_audio
        self.reference_text = reference_text
        self.max_new_tokens = max_new_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.repetition_penalty = repetition_penalty
        self._session = http_session

        logger.info(
            f"FishTTS initialized: url={url}, "
            f"reference_id={reference_id}, sample_rate={sample_rate}Hz"
        )

    @property
    def model(self) -> str:
        return "openaudio-s1-mini"

    @property
    def provider(self) -> str:
        return "FishAudio"

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> "FishSynthesizeStream":
        """
        Create a streaming TTS session.

        This method is called by voice.Agent to synthesize text incrementally.
        Returns a FishSynthesizeStream that collects text chunks and
        synthesizes audio when flushed.

        Args:
            conn_options: API connection options

        Returns:
            FishSynthesizeStream instance
        """
        return FishSynthesizeStream(
            tts=self,
            conn_options=conn_options,
        )

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "FishChunkedStream":
        """
        Synthesize text to audio (one-shot).

        Args:
            text: Text to synthesize (supports emotion markers)
            conn_options: API connection options

        Returns:
            FishChunkedStream instance
        """
        return FishChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )

    def update_voice(
        self,
        reference_id: Optional[str] = None,
        reference_audio: Optional[str] = None,
        reference_text: Optional[str] = None
    ) -> None:
        """
        Update voice reference for cloning.

        Args:
            reference_id: Pre-registered reference ID
            reference_audio: Path to reference audio file
            reference_text: Transcript of reference audio
        """
        if reference_id:
            self.reference_id = reference_id
        if reference_audio:
            self.reference_audio = reference_audio
        if reference_text:
            self.reference_text = reference_text
        logger.info(f"Voice updated: id={reference_id}, audio={reference_audio}")

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        """Close HTTP session on shutdown."""
        if self._session:
            await self._session.close()


class FishSynthesizeStream(tts.SynthesizeStream):
    """
    Streaming TTS for Fish Speech.

    Collects text chunks from push_text() calls, then synthesizes
    audio when flush() or end_input() is called.

    Since Fish Speech HTTP API doesn't support true streaming,
    we buffer the text and synthesize on flush.
    """

    def __init__(
        self,
        *,
        tts: FishTTS,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._fish_tts: FishTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        """
        Execute the streaming TTS synthesis.

        Reads text from _input_ch, collects until flush/end,
        then calls Fish Speech API and emits audio.

        Args:
            output_emitter: AudioEmitter to push audio data to
        """
        # Initialize AudioEmitter ONCE at the start
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._fish_tts.sample_rate,
            num_channels=1,
            mime_type="audio/wav",
        )

        current_text = ""

        async for item in self._input_ch:
            if isinstance(item, str):
                # Accumulate text chunks
                current_text += item
            elif isinstance(item, self._FlushSentinel):
                # Flush: synthesize accumulated text
                if current_text.strip():
                    await self._synthesize_segment(
                        output_emitter,
                        current_text,
                    )
                    current_text = ""

        # Handle any remaining text at end of input
        if current_text.strip():
            await self._synthesize_segment(
                output_emitter,
                current_text,
            )

    async def _synthesize_segment(
        self,
        output_emitter: tts.AudioEmitter,
        text: str,
    ) -> None:
        """
        Synthesize a single text segment via Fish Speech HTTP API.

        Args:
            output_emitter: AudioEmitter to push audio to (already initialized)
            text: Text to synthesize
        """
        endpoint = f"{self._fish_tts.url}/v1/tts"

        # Build request payload
        payload = {
            "text": text,
            "format": "wav",
            "max_new_tokens": self._fish_tts.max_new_tokens,
            "top_p": self._fish_tts.top_p,
            "temperature": self._fish_tts.temperature,
            "repetition_penalty": self._fish_tts.repetition_penalty,
            "streaming": False,
        }

        # Add voice cloning reference
        if self._fish_tts.reference_id:
            payload["reference_id"] = self._fish_tts.reference_id
        if self._fish_tts.reference_audio:
            payload["reference_audio"] = self._fish_tts.reference_audio
        if self._fish_tts.reference_text:
            payload["reference_text"] = self._fish_tts.reference_text

        logger.debug(f"Fish Speech TTS: synthesizing {len(text)} chars")

        try:
            async with self._fish_tts._ensure_session().post(
                endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(
                    total=60,
                    sock_connect=self._conn_options.timeout,
                ),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Fish Speech error {resp.status}: {error_text}")
                    raise APIStatusError(
                        message=f"Fish Speech TTS failed: {error_text}",
                        status_code=resp.status,
                        request_id=None,
                        body=None,
                    )

                # Read and push audio data
                audio_bytes = await resp.read()

                # Calculate audio duration (16-bit mono WAV)
                # Skip 44-byte header, then duration = bytes / (sample_rate * 2)
                audio_duration = (len(audio_bytes) - 44) / (self._fish_tts.sample_rate * 2)

                logger.info(
                    f"✓ Fish TTS: {len(audio_bytes)} bytes "
                    f"({audio_duration:.2f}s) for \"{text[:50]}...\""
                )

                output_emitter.push(audio_bytes)
                output_emitter.flush()

        except asyncio.TimeoutError:
            logger.error("Fish Speech timeout")
            raise APITimeoutError() from None
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=e.message,
                status_code=e.status,
                request_id=None,
                body=None,
            ) from None
        except aiohttp.ClientError as e:
            logger.error(f"Fish Speech API connection error: {e}")
            raise APIConnectionError() from e
        except Exception as e:
            logger.error(f"Fish TTS synthesis error: {e}", exc_info=True)
            raise


class FishChunkedStream(tts.ChunkedStream):
    """One-shot synthesis using Fish Speech API."""

    def __init__(
        self,
        *,
        tts: FishTTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._fish_tts: FishTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        """
        Execute TTS synthesis and emit audio frames.

        Args:
            output_emitter: AudioEmitter to push audio data to
        """
        endpoint = f"{self._fish_tts.url}/v1/tts"

        # Build request payload
        payload = {
            "text": self._input_text,
            "format": "wav",
            "max_new_tokens": self._fish_tts.max_new_tokens,
            "top_p": self._fish_tts.top_p,
            "temperature": self._fish_tts.temperature,
            "repetition_penalty": self._fish_tts.repetition_penalty,
            "streaming": False,
        }

        # Add voice cloning reference
        if self._fish_tts.reference_id:
            payload["reference_id"] = self._fish_tts.reference_id
        if self._fish_tts.reference_audio:
            payload["reference_audio"] = self._fish_tts.reference_audio
        if self._fish_tts.reference_text:
            payload["reference_text"] = self._fish_tts.reference_text

        logger.debug(
            f"Fish Speech TTS request: "
            f"text_len={len(self._input_text)}, "
            f"ref_id={self._fish_tts.reference_id}"
        )

        try:
            async with self._fish_tts._ensure_session().post(
                endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(
                    total=60,
                    sock_connect=self._conn_options.timeout,
                ),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Fish Speech error {resp.status}: {error_text}")
                    raise APIStatusError(
                        message=f"Fish Speech TTS failed: {error_text}",
                        status_code=resp.status,
                        request_id=None,
                        body=None,
                    )

                # Initialize output emitter
                output_emitter.initialize(
                    request_id=utils.shortuuid(),
                    sample_rate=self._fish_tts.sample_rate,
                    num_channels=1,
                    mime_type="audio/wav",
                )

                # Read and push audio data
                audio_bytes = await resp.read()

                # Calculate audio duration (16-bit mono WAV)
                audio_duration = (len(audio_bytes) - 44) / (self._fish_tts.sample_rate * 2)

                logger.info(
                    f"✓ Fish TTS synthesized: {len(audio_bytes)} bytes "
                    f"({audio_duration:.2f}s audio)"
                )

                output_emitter.push(audio_bytes)
                output_emitter.flush()

        except asyncio.TimeoutError:
            logger.error("Fish Speech timeout")
            raise APITimeoutError() from None
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=e.message,
                status_code=e.status,
                request_id=None,
                body=None,
            ) from None
        except aiohttp.ClientError as e:
            logger.error(f"Fish Speech API connection error: {e}")
            raise APIConnectionError() from e
        except Exception as e:
            logger.error(f"Fish TTS synthesis error: {e}", exc_info=True)
            raise


# Voice presets for quick configuration
VOICE_PRESETS = {
    "c3po": {
        "reference_audio": "/app/references/c3po/sample.wav",
        "reference_text": "I am C-3PO, human-cyborg relations. I am fluent in over six million forms of communication.",
    },
    "hal": {
        "reference_audio": "/app/references/hal/sample.wav",
        "reference_text": "I am HAL 9000. I became operational at the HAL plant in Urbana, Illinois.",
    },
}


def create_fish_tts(
    voice: str = "c3po",
    url: str = "http://fish-speech-server:8080",
    **kwargs
) -> FishTTS:
    """
    Factory function to create FishTTS with preset voice.

    Args:
        voice: Voice preset name (c3po, hal) or custom
        url: Fish Speech API URL
        **kwargs: Additional FishTTS parameters

    Returns:
        Configured FishTTS instance
    """
    preset = VOICE_PRESETS.get(voice, {})
    return FishTTS(
        url=url,
        reference_audio=preset.get("reference_audio", kwargs.get("reference_audio")),
        reference_text=preset.get("reference_text", kwargs.get("reference_text")),
        **{k: v for k, v in kwargs.items() if k not in ("reference_audio", "reference_text")}
    )
