"""
Local Voice Agent - Optimized Stack with LiveKit Agents SDK

Architecture:
- STT: Faster-Whisper via OpenAI plugin (local, GPU, HTTP)
- LLM: Groq LPU (cloud, ultra-fast ~50ms TTFT) or OpenRouter/Ollama fallback
- TTS: Cartesia Sonic (cloud, streaming ~100ms TTFB, voice cloning)
- VAD: Silero (built-in LiveKit)
- Function Tools: 10 skills (34 capabilities)

Author: C-3PO Team
Date: 2026-01-03
"""
import logging
from typing import Optional
import os
from livekit.agents import Agent, tts
from livekit.plugins import silero, openai, cartesia

# Cartesia voice IDs (create at https://play.cartesia.ai/voices)
CARTESIA_VOICES = {
    "c3po": "b0f6a796-3828-44c0-a74e-7008c2718ce2",  # Clone C-3PO
    "aria": "794f9389-aac1-45b6-b726-9d9369183238",  # Default female
    "british_male": "a167e0f3-df7e-4d52-a9c3-f949145efdab",  # Blake
    "barry": "a167e0f3-df7e-4d52-a9c3-f949145efdab",  # Barry (Blake male voice)
    "hannah": "6ccbfb76-1fc6-48f7-b71d-91ac6298247b",  # Hannah
    "sarah": "a8a1eb38-5f15-4c1d-8722-7ac0f329727d",  # Sarah
    "leo": "ce74c4da-4aee-435d-bc6d-81d1a9367e12",  # Leo
}

# Function tools (skills)
from agents.tools import (
    get_weather,
    find_restaurant,
    get_news,
    search_calendar,
    control_home,
    make_phone_call,
    control_music,
    ask_about_buddy,
    get_expert_advice,
    order_delivery
)

logger = logging.getLogger(__name__)


class LocalVoiceAgent(Agent):
    """
    Voice agent with 100% local processing.

    Pipeline:
        Audio In → Silero VAD → Faster-Whisper STT → Ollama LLM → F5-TTS → Audio Out

    Features:
    - Zero external API costs ($0/month vs $15/month OpenAI)
    - Complete privacy (100% local processing)
    - Function calling (10 tools covering 34 skills)
    - Automatic interruption (barge-in)
    - Trilingual (FR/EN/ES)
    - GPU efficient: ~7GB total (STT 2GB + LLM 2GB + TTS 3GB)
    """

    def __init__(
        self,
        *,
        instructions: str,
        voice: str = "hal_combined_44k.wav",
        persona: str = "aria",
        language: str = "fr",
        sample_rate: int = 44100
    ):
        """
        Initialize local voice agent.

        Args:
            instructions: System prompt for LLM
            voice: Voice file for TTS (hal_combined_44k.wav, c3po_short_30s_44k.wav)
            persona: Voice persona (aria, c3po, barry)
            language: Language code (fr, en, es)
            sample_rate: Audio sample rate (22050 or 44100)
        """
        # Pass tools to Agent (they're already decorated with @function_tool)
        super().__init__(
            instructions=instructions,
            tools=[
                get_weather,
                get_news,
                search_calendar,
                find_restaurant,
                order_delivery,
                control_home,
                control_music,
                make_phone_call,
                ask_about_buddy,
                get_expert_advice
            ]
        )

        self.voice = voice
        self.persona = persona
        self.language = language
        self.sample_rate = sample_rate

        logger.info(
            f"LocalVoiceAgent initialized: persona={persona}, voice={voice}, "
            f"language={language}, sample_rate={sample_rate}Hz, tools=10"
        )

    def stt_node(self):
        """
        Override STT node with Faster-Whisper via OpenAI-compatible API.

        Uses livekit-plugins-openai pointing to local Faster-Whisper server
        (compatible OpenAI API). This is more stable than custom plugin.

        Returns:
            openai.STT instance configured for local transcription
        """
        # Don't pass language to Whisper - let it auto-detect
        # This allows English/French/Spanish to be transcribed correctly
        return openai.STT(
            base_url="http://localhost:8000/v1",
            model="whisper-1",  # Standard OpenAI model name (ignored by Faster-Whisper)
        )

    def llm_node(self):
        """
        Override LLM node - supports Groq, OpenRouter, OpenAI, or Ollama.

        Priority:
        1. GROQ_API_KEY -> Groq LPU (fastest, ~50ms TTFT)
        2. OPENROUTER_API_KEY -> OpenRouter (access to all LLMs)
        3. OPENAI_API_KEY -> OpenAI direct
        4. Fallback -> Ollama local

        Returns:
            openai.LLM instance
        """
        groq_key = os.getenv("GROQ_API_KEY")
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        if groq_key:
            # Groq LPU: Fastest inference, ~50ms TTFT, 280 tokens/s
            model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
            logger.info(f"⚡ LLM node: {model} via Groq LPU (~50ms TTFT)")
            return openai.LLM(
                model=model,
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key,
                temperature=0.7,
            )
        elif openrouter_key:
            # OpenRouter: Access to all LLMs via unified API
            llm_model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
            logger.info(f"✓ LLM node: {llm_model} via OpenRouter (~100-200ms)")
            return openai.LLM(
                model=llm_model,
                base_url="https://openrouter.ai/api/v1",
                api_key=openrouter_key,
                temperature=0.7,
            )
        elif openai_key:
            # OpenAI direct
            logger.info("✓ LLM node: GPT-4o-mini (OpenAI direct, ~150ms)")
            return openai.LLM(
                model="gpt-4o-mini",
                temperature=0.7,
            )
        else:
            # Ollama local: Free, ~400ms after warmup
            logger.info("✓ LLM node: Llama 3.2 3B (local, ~400ms)")
            return openai.LLM.with_ollama(
                model="llama3.2:3b",
                base_url="http://localhost:11434/v1",
                temperature=0.7,
            )

    def tts_node(self):
        """
        Override TTS node with Cartesia (ultra-fast streaming TTS).

        Cartesia Sonic:
        - Streaming (first byte in ~100ms)
        - RTF ~0.1x (10x faster than real-time)
        - Voice cloning support
        - Cloud-based (no local GPU needed for TTS)

        Returns:
            cartesia.TTS instance
        """
        cartesia_key = os.getenv("CARTESIA_API_KEY")

        if not cartesia_key:
            raise ValueError("CARTESIA_API_KEY environment variable is required")

        # Use persona set in __init__ (from participant attributes or env)
        voice_id = CARTESIA_VOICES.get(self.persona, CARTESIA_VOICES["aria"])

        logger.info(f"⚡ TTS node: Cartesia Sonic ({self.persona}, voice_id={voice_id})")

        return cartesia.TTS(
            model="sonic-2",
            voice=voice_id,
            language=self.language,
        )

    def vad_node(self):
        """
        Override VAD node with Silero (tuned for conversation).

        Tuning:
        - min_silence_duration: 500ms (avoid cutting off user mid-sentence)
        - min_speech_duration: 100ms (quick response to short utterances)

        Returns:
            Silero VAD instance for voice activity detection
        """
        return silero.VAD.load(
            min_silence_duration=0.4,  # 400ms - faster end-of-speech detection
            min_speech_duration=0.25,  # 250ms - filter out noise, detect real speech
        )


# Helper function to create agent instances
def create_local_agent(
    persona: str = "aria",
    language: str = "fr",
    system_prompt: Optional[str] = None
) -> LocalVoiceAgent:
    """
    Create a LocalVoiceAgent instance with persona configuration.

    Args:
        persona: Voice persona (aria, c3po, barry)
        language: Language code (fr, en, es, auto)
        system_prompt: Custom system prompt (optional)

    Returns:
        Configured LocalVoiceAgent instance
    """
    # Voice mapping
    voice_files = {
        "c3po": {
            "fr": "c3po_fr_native_22k.wav",
            "en": "c3po_en_native_22k.wav",
            "default": "c3po_bilingue_pro_44k.wav"  # Bilingual for auto-detection
        },
        "aria": {
            "fr": "hal_combined_44k.wav",  # HAL 9000 voice (44.1kHz)
            "en": "hal_combined_44k.wav",
            "default": "hal_combined_44k.wav"  # HAL 9000
        },
        "barry": {
            "default": "barry_combined_44k.wav"
        }
    }

    # Sample rate mapping
    sample_rates = {
        "c3po_fr_native_22k.wav": 22050,
        "c3po_en_native_22k.wav": 22050,
        "c3po_short_30s_44k.wav": 44100,
        "hal_combined_44k.wav": 44100,
        "barry_combined_44k.wav": 44100
    }

    # Select voice file
    if persona in voice_files:
        voice_config = voice_files[persona]
        if language in voice_config:
            voice_file = voice_config[language]
        else:
            voice_file = voice_config["default"]
    else:
        voice_file = "hal_combined_44k.wav"  # Default to ARIA

    # Get sample rate
    sample_rate = sample_rates.get(voice_file, 44100)

    # Use default system prompt if not provided
    if system_prompt is None:
        from agents.agent_config import get_system_prompt
        system_prompt = get_system_prompt(persona, language)

    return LocalVoiceAgent(
        instructions=system_prompt,
        voice=voice_file,
        persona=persona,
        language=language,
        sample_rate=sample_rate
    )
