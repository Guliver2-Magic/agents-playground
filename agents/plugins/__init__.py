"""LiveKit Agents plugins for C-3PO."""
from .chatterbox_tts import ChatterboxTTS
from .fish_tts import FishTTS, create_fish_tts, VOICE_PRESETS

__all__ = ["ChatterboxTTS", "FishTTS", "create_fish_tts", "VOICE_PRESETS"]
