"""
F5-TTS Plugin for LiveKit Agents

Fast, GPU-efficient TTS with voice cloning using F5-TTS.
Uses subprocess for generation with post-processing to extract generated audio only.

Architecture:
- F5-TTS generates: reference_audio (12s max) + generated_audio
- Post-processing: Skip reference duration to get only generated part
- Output: PCM 24kHz mono

Performance:
- GPU memory: ~3GB (vs 10GB for Chatterbox)
- Generation: ~0.25x RTF (4x faster than real-time)
- Stable on RTX A5000/A6000

Author: C-3PO Team
Date: 2026-01-03
"""
import asyncio
import logging
import subprocess
import tempfile
import os
from typing import Optional
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

from livekit.agents import tts, utils, APIConnectionError, APITimeoutError
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

logger = logging.getLogger(__name__)


class F5TTS(tts.TTS):
    """
    F5-TTS plugin for LiveKit Agents.

    Uses Docker container for GPU-accelerated TTS with voice cloning.
    Post-processes output to extract only generated audio.
    """

    def __init__(
        self,
        container_name: str = "f5-tts-server",
        voice_file: str = "c3po_short_30s_44k.wav",
        voice_text: str = "I am C-3PO human cyborg relations",
        sample_rate: int = 24000,
        speed: float = 1.0,
        reference_duration: float = 12.0,
    ):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1
        )

        self.container_name = container_name
        self.voice_file = voice_file
        self.voice_text = voice_text
        self.speed = speed
        self.reference_duration = reference_duration

        logger.info(
            f"F5TTS initialized: voice={voice_file}, "
            f"sample_rate={sample_rate}Hz"
        )

    @property
    def model(self) -> str:
        return "F5TTS_v1_Base"

    @property
    def provider(self) -> str:
        return "F5-TTS"

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "F5TTSChunkedStream":
        return F5TTSChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )


class F5TTSChunkedStream(tts.ChunkedStream):
    """Synthesize text using F5-TTS with audio surgery."""

    def __init__(
        self,
        *,
        tts: F5TTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: F5TTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        """
        Execute TTS with audio surgery to extract only generated speech.

        Pipeline:
        1. Generate via F5-TTS CLI (outputs ref + generated)
        2. Audio surgery: skip reference duration
        3. Trim silence
        4. Emit PCM to LiveKit
        """
        import time
        start_time = time.time()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.wav")
            container_output = "/tmp/livekit_tts_output.wav"

            # Build command as list (safe, no shell injection)
            cmd_args = [
                "docker", "exec", self._tts.container_name,
                "f5-tts_infer-cli",
                "-m", "F5TTS_v1_Base",
                "-r", f"/app/voices/{self._tts.voice_file}",
                "-s", self._tts.voice_text,
                "-t", self._input_text,
                "--remove_silence",
                "--speed", str(self._tts.speed),
                "-w", container_output,
            ]

            logger.debug(f"F5-TTS generating: '{self._input_text[:50]}...'")

            try:
                # Run F5-TTS CLI using subprocess (safe)
                process = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=60.0
                )

                if process.returncode != 0:
                    error_msg = stderr.decode()[:200] if stderr else "Unknown error"
                    logger.error(f"F5-TTS CLI failed: {error_msg}")
                    raise APIConnectionError(f"F5-TTS error: {error_msg}")

                # Copy output from container (safe subprocess)
                copy_args = [
                    "docker", "cp",
                    f"{self._tts.container_name}:{container_output}",
                    output_file
                ]
                copy_process = await asyncio.create_subprocess_exec(
                    *copy_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await copy_process.communicate()

                if not os.path.exists(output_file):
                    raise APIConnectionError("F5-TTS output file not found")

                # === AUDIO SURGERY ===
                # F5-TTS outputs: reference (12s max) + generated
                # We extract ONLY the generated part

                audio = AudioSegment.from_file(output_file)
                original_duration = len(audio)

                # Skip reference duration (12s = 12000ms)
                skip_ms = int(self._tts.reference_duration * 1000)
                if len(audio) > skip_ms:
                    audio = audio[skip_ms:]
                else:
                    logger.warning(f"Audio shorter than reference: {len(audio)}ms")

                # Trim leading/trailing silence
                start_trim = detect_leading_silence(audio, silence_threshold=-40)
                end_trim = detect_leading_silence(audio.reverse(), silence_threshold=-40)
                if start_trim < len(audio) and end_trim < len(audio):
                    audio = audio[start_trim:len(audio) - end_trim]

                # Convert to target format
                audio = audio.set_frame_rate(self._tts.sample_rate)
                audio = audio.set_channels(1)
                audio = audio.set_sample_width(2)

                pcm_data = audio.raw_data
                duration = len(audio) / 1000
                elapsed = time.time() - start_time

                logger.info(
                    f"F5-TTS: {len(pcm_data)} bytes, "
                    f"{duration:.2f}s audio (from {original_duration/1000:.1f}s), "
                    f"{elapsed:.2f}s gen, RTF={elapsed/max(duration,0.1):.2f}x"
                )

                # Emit to LiveKit
                output_emitter.initialize(
                    request_id=utils.shortuuid(),
                    sample_rate=self._tts.sample_rate,
                    num_channels=1,
                    mime_type="audio/pcm",
                )

                # Push in chunks
                chunk_size = 16384
                for i in range(0, len(pcm_data), chunk_size):
                    output_emitter.push(pcm_data[i:i + chunk_size])

                output_emitter.flush()

            except asyncio.TimeoutError:
                logger.error("F5-TTS timeout")
                raise APITimeoutError()
            except Exception as e:
                logger.error(f"F5-TTS error: {e}")
                raise


# Voice presets with CORRECT reference durations
# F5-TTS outputs: reference_audio + generated_audio
# We must skip the exact reference duration to get only generated speech
VOICE_PRESETS = {
    "c3po": {
        "voice_file": "c3po_short_30s_44k.wav",
        "voice_text": "I am C-3PO human cyborg relations",
        "reference_duration": 17.76,  # Actual duration of c3po reference
    },
    "hal": {
        "voice_file": "hal_combined_44k.wav",
        "voice_text": "I am a HAL 9000 computer",
        "reference_duration": 74.14,  # Actual duration of HAL reference
    },
    "aria": {
        "voice_file": "hal_combined_44k.wav",
        "voice_text": "I am a HAL 9000 computer",
        "reference_duration": 74.14,  # Same as HAL
    },
}


def create_f5_tts(persona: str = "c3po", speed: float = 1.0) -> F5TTS:
    """Create F5-TTS with voice preset and correct reference duration."""
    preset = VOICE_PRESETS.get(persona, VOICE_PRESETS["c3po"])
    return F5TTS(
        container_name="f5-tts-server",
        voice_file=preset["voice_file"],
        voice_text=preset["voice_text"],
        reference_duration=preset["reference_duration"],
        speed=speed,
    )
