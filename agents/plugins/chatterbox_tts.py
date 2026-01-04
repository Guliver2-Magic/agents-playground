"""
Chatterbox TTS Plugin for LiveKit Agents

Custom TTS plugin wrapping Chatterbox API (ResembleAI) for HAL 9000
and C-3PO voice cloning.

Author: C-3PO Team
Date: 2026-01-02
"""
import asyncio
import logging
import aiohttp
from typing import Optional
from livekit.agents import tts, utils, APIConnectionError, APIStatusError, APITimeoutError
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

logger = logging.getLogger(__name__)


class ChatterboxTTS(tts.TTS):
    """
    Chatterbox TTS plugin for LiveKit Agents.

    Wraps Chatterbox API (http://chatterbox-tts:8004) to provide
    custom voice cloning (HAL 9000, C-3PO) for LiveKit voice agents.

    Implements LiveKit TTS interface with:
    - synthesize(): Text → ChunkedStream
    - stream(): Streaming TTS (future)

    Voice files:
    - c3po_short_30s_44k.wav: C-3PO voice (17.76s, 44.1kHz)
    - hal_combined_44k.wav: HAL 9000 voice (74.14s, 44.1kHz)
    - barry_combined_44k.wav: Barry voice (88.87s, 44.1kHz)
    """

    def __init__(
        self,
        url: str = "http://chatterbox-tts-chatterbox-tts-server-1:8004",
        voice: str = "hal_combined_44k.wav",
        sample_rate: int = 44100,
        language: str = "fr",
        temperature: float = 0.7,
        speed_factor: float = 1.0,
        http_session: Optional[aiohttp.ClientSession] = None
    ):
        """
        Initialize Chatterbox TTS plugin.

        Args:
            url: Chatterbox API endpoint
            voice: Voice filename (c3po_short_30s_44k.wav, hal_combined_44k.wav, barry_combined_44k.wav)
            sample_rate: Output sample rate (44100 recommended)
            language: Language code (fr, en, es)
            temperature: Voice temperature 0.0-1.0
            speed_factor: Speech speed multiplier
            http_session: Optional aiohttp ClientSession
        """
        super().__init__(
            capabilities=tts.TTSCapabilities(
                streaming=False  # Chatterbox doesn't support streaming yet
            ),
            sample_rate=sample_rate,
            num_channels=1
        )

        self.url = url
        self.voice = voice
        self.language = language
        self.temperature = temperature
        self.speed_factor = speed_factor
        self._session = http_session

        logger.info(
            f"ChatterboxTTS initialized: voice={voice}, "
            f"sample_rate={sample_rate}Hz, language={language}"
        )

    @property
    def model(self) -> str:
        return "chatterbox-multilingual"

    @property
    def provider(self) -> str:
        return "Chatterbox"

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "ChatterboxChunkedStream":
        """
        Synthesize text to audio.

        Args:
            text: Text to synthesize
            conn_options: API connection options

        Returns:
            ChatterboxChunkedStream instance
        """
        return ChatterboxChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        """Close HTTP session on shutdown."""
        if self._session:
            await self._session.close()


class ChatterboxChunkedStream(tts.ChunkedStream):
    """Synthesize text to speech using Chatterbox API."""

    def __init__(
        self,
        *,
        tts: ChatterboxTTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: ChatterboxTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        """
        Execute TTS synthesis and emit audio frames.

        Args:
            output_emitter: AudioEmitter to push audio data to
        """
        endpoint = f"{self._tts.url}/tts"

        # Use the correct Chatterbox API format with predefined voices
        payload = {
            "text": self._input_text,
            "voice_mode": "predefined",
            "predefined_voice_id": self._tts.voice,
            "language": self._tts.language,
            "temperature": self._tts.temperature,
            "speed_factor": self._tts.speed_factor
        }

        logger.debug(
            f"Chatterbox TTS request: voice={self._tts.voice}, "
            f"text_len={len(self._input_text)}"
        )

        try:
            async with self._tts._ensure_session().post(
                endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(
                    total=30,
                    sock_connect=self._conn_options.timeout,
                ),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise APIStatusError(
                        message=f"Chatterbox TTS failed: {error_text}",
                        status_code=resp.status,
                        request_id=None,
                        body=None,
                    )

                # Initialize output emitter
                output_emitter.initialize(
                    request_id=utils.shortuuid(),
                    sample_rate=self._tts.sample_rate,
                    num_channels=1,
                    mime_type="audio/wav",
                )

                # Read and push audio data
                audio_bytes = await resp.read()

                logger.info(
                    f"✓ TTS synthesized: {len(audio_bytes)} bytes "
                    f"({len(audio_bytes) / (self._tts.sample_rate * 2):.2f}s audio)"
                )

                output_emitter.push(audio_bytes)
                output_emitter.flush()

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
            logger.error(f"Chatterbox API connection error: {e}")
            raise APIConnectionError() from e
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}", exc_info=True)
            raise
