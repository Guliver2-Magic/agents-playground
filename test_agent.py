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

# Add c3po-v3 pipecat-service to path
sys.path.insert(0, '/opt/stacks/c3po-v3/pipecat-service')

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.worker import WorkerType
from livekit.agents import voice

# Import our LocalVoiceAgent
from app.agents.local_voice_agent import create_local_agent
from app.agents.rpc_handlers import register_rpc_methods

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def entrypoint(ctx: JobContext):
    """
    Entry point for LiveKit Agent jobs.

    This function is called whenever a participant joins a room.
    It creates and starts our LocalVoiceAgent.
    """
    logger.info(f"Connecting to room: {ctx.room.name}")

    # Connect to room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    logger.info("✓ Connected to room")

    # Register RPC methods for direct function tool invocation from frontend
    register_rpc_methods(ctx.room.local_participant)
    logger.info("✓ RPC methods registered")

    # Get configuration from environment or use defaults
    persona = os.getenv("VOICE_PERSONA", "aria")  # aria, c3po, barry
    language = os.getenv("VOICE_LANGUAGE", "fr")  # fr, en, es, auto

    logger.info(f"Creating LocalVoiceAgent: persona={persona}, language={language}")

    # Create our local voice agent
    agent = create_local_agent(
        persona=persona,
        language=language
    )

    logger.info("✓ LocalVoiceAgent created")
    logger.info("  - STT: Faster-Whisper (large-v3)")
    logger.info("  - LLM: Mistral Nemo (12B)")
    logger.info("  - TTS: Chatterbox gRPC (streaming)")
    logger.info("  - VAD: Silero")
    logger.info("  - Functions: 10 tools (34 skills)")

    # Create voice.Agent configuration object with all nodes and instructions
    # The LocalVoiceAgent provides the nodes, but we need a voice.Agent for the session
    # CRITICAL: Pass tools so LLM has access to function calling
    voice_agent = voice.Agent(
        vad=agent.vad_node(),
        stt=agent.stt_node(),
        llm=agent.llm_node(),
        tts=agent.tts_node(),
        instructions=agent.instructions,
        tools=agent.tools,  # FIX: Propagate function tools to voice.Agent
    )

    # Create AgentSession and start with the Agent object
    # Signature: start(self, agent: 'Agent', *, room=..., ...)
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
    # Run the LiveKit agent worker
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            # Worker will handle room-based jobs (participant connections)
            worker_type=WorkerType.ROOM,
        )
    )
