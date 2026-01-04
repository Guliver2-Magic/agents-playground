#!/usr/bin/env python3
"""
Test agent for LiveKit Agent Playground
Uses C-3PO's LocalVoiceAgent with 100% local stack

Requirements:
- Faster-Whisper running on http://faster-whisper:8000
- Ollama running on http://ollama:11434
- Chatterbox gRPC running on chatterbox-tts:50051
- LiveKit server running on ws://localhost:7880

Environment Variables:
- LIVEKIT_URL=ws://localhost:7880
- LIVEKIT_API_KEY=devkey
- LIVEKIT_API_SECRET=secret
"""
import asyncio
import logging
import os
import sys

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Add c3po-v3 pipecat-service to path
# Using local agents folder

from livekit.agents import JobContext, JobProcess, AutoSubscribe, AgentServer, cli
from livekit.agents import voice

# Import our LocalVoiceAgent
from agents.local_voice_agent import create_local_agent
from agents.rpc_handlers import register_rpc_methods
from agents.vision_module import get_proactive_context, get_vision
from agents.memory_module import get_memory, inject_memory_context

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create AgentServer instance
server = AgentServer()


@server.rtc_session(agent_name="voice-agent")
async def entrypoint(ctx: JobContext):
    """
    Entry point for LiveKit Agent jobs.

    This function is called whenever a participant joins a NEW room.
    The @server.rtc_session() decorator enables automatic dispatch.
    """
    logger.info(f"Connecting to room: {ctx.room.name}")

    # Connect to room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    logger.info("✓ Connected to room")

    # Register RPC methods for direct function tool invocation from frontend
    register_rpc_methods(ctx.room.local_participant)
    logger.info("✓ RPC methods registered")
    logger.info(f"🆔 Agent identity: {ctx.room.local_participant.identity}")

    # Get voice and TTS settings from job metadata (set via explicit dispatch)
    persona = os.getenv("VOICE_PERSONA", "aria")  # default Cartesia voice
    language = os.getenv("VOICE_LANGUAGE", "fr")  # fr, en, es, auto
    tts_provider = "cartesia"  # default
    kokoro_voice = "af_heart"  # default Kokoro voice

    # Read settings from job metadata (passed via RoomAgentDispatch)
    if ctx.job and ctx.job.metadata:
        try:
            import json
            job_meta = json.loads(ctx.job.metadata)
            if "voice" in job_meta:
                persona = job_meta["voice"]
                logger.info(f"🎤 Voice from job metadata: {persona}")
            if "ttsProvider" in job_meta:
                tts_provider = job_meta["ttsProvider"]
                logger.info(f"🔊 TTS provider from job metadata: {tts_provider}")
            if "kokoroVoice" in job_meta:
                kokoro_voice = job_meta["kokoroVoice"]
                logger.info(f"🎵 Kokoro voice from job metadata: {kokoro_voice}")
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: check participant attributes
    if persona == os.getenv("VOICE_PERSONA", "aria"):
        for participant in ctx.room.remote_participants.values():
            voice_attr = participant.attributes.get("voice")
            if voice_attr:
                persona = voice_attr
                logger.info(f"🎤 Voice from participant: {persona}")
            tts_attr = participant.attributes.get("ttsProvider")
            if tts_attr:
                tts_provider = tts_attr
                logger.info(f"🔊 TTS provider from participant: {tts_provider}")
            kokoro_attr = participant.attributes.get("kokoroVoice")
            if kokoro_attr:
                kokoro_voice = kokoro_attr
                logger.info(f"🎵 Kokoro voice from participant: {kokoro_voice}")
            break

    logger.info(f"Creating LocalVoiceAgent: persona={persona}, tts={tts_provider}, language={language}")

    # Create our local voice agent
    agent = create_local_agent(
        persona=persona,
        language=language,
        tts_provider=tts_provider,
        kokoro_voice=kokoro_voice
    )

    logger.info("✓ LocalVoiceAgent created")
    logger.info("  - STT: Faster-Whisper (large-v3)")

    # Log LLM source
    llm_model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    if os.getenv("OPENROUTER_API_KEY"):
        logger.info(f"  - LLM: {llm_model} (OpenRouter, ~100-200ms)")
    elif os.getenv("OPENAI_API_KEY"):
        logger.info("  - LLM: GPT-4o-mini (OpenAI, ~150ms)")
    else:
        logger.info("  - LLM: Llama 3.2 3B (Ollama local, ~400ms)")

    # Log TTS source
    if tts_provider == "kokoro":
        logger.info(f"  - TTS: Kokoro ({kokoro_voice}, local GPU, ~50ms TTFB)")
    elif os.getenv("CARTESIA_API_KEY"):
        logger.info(f"  - TTS: Cartesia Sonic-2 ({persona}, streaming, ~100ms TTFB)")
    else:
        logger.info("  - TTS: F5-TTS (local)")

    logger.info("  - VAD: Silero")
    logger.info("  - Functions: 10 tools (34 skills)")
    logger.info("  - Vision: YOLO + Face Recognition")
    logger.info("  - Memory: PostgreSQL (persistent)")

    # Initialize conversation memory
    memory = get_memory()
    await memory.connect()
    await memory.start_conversation(client_type="web", language=language)
    logger.info("  - Conversation started in database")

    # Get memory context from past conversations
    memory_context = await memory.get_memory_context()
    memory_prompt = memory_context.to_prompt()
    if memory_prompt:
        logger.info(f"  - Memory context: {memory_prompt[:50]}...")

    # Get proactive visual context (master greeting, Buddy alerts)
    proactive_context = await get_proactive_context()
    if proactive_context:
        logger.info(f"  - Proactive context: {proactive_context}")

    # Enhance instructions with memory and visual context
    enhanced_instructions = agent.instructions
    if memory_prompt:
        enhanced_instructions = f"{enhanced_instructions}\n\n[Memory Context] {memory_prompt}"
    if proactive_context:
        enhanced_instructions = f"{enhanced_instructions}\n\n[Visual Context] {proactive_context}"

    # Create voice.Agent configuration object with all nodes and instructions
    # The LocalVoiceAgent provides the nodes, but we need a voice.Agent for the session
    # CRITICAL: Pass tools so LLM has access to function calling
    voice_agent = voice.Agent(
        vad=agent.vad_node(),
        stt=agent.stt_node(),
        llm=agent.llm_node(),
        tts=agent.tts_node(),
        instructions=enhanced_instructions,
        tools=agent.tools,  # Propagate function tools to voice.Agent
    )

    # Create AgentSession and start with the Agent object
    session = voice.AgentSession()
    await session.start(voice_agent, room=ctx.room)

    logger.info("✓ Voice agent started successfully")
    logger.info("  Waiting for participant audio...")

    # Agent will run until the room is closed
    # The agent handles:
    # - Audio input from participant
    # - VAD (voice activity detection)
    # - STT (speech-to-text)
    # - LLM processing with function calling
    # - TTS (text-to-speech)
    # - Audio output to participant


if __name__ == "__main__":
    # Run the LiveKit agent server
    # The AgentServer with @server.rtc_session() decorator enables auto-dispatch
    # Without agent_name parameter, the agent automatically joins all new rooms
    cli.run_app(server)
