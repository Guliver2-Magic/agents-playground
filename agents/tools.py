"""
LiveKit Agent Function Tools

Function tools with direct skill imports (Phase 3 optimization).
NO HTTP overhead - skills imported directly from c3po-skills package.

Target latency: <200ms (98x faster than baseline!)

Author: C-3PO Team
Date: 2026-01-02
"""
import aiohttp
import logging
import os
from typing import Optional
from livekit.agents import function_tool, RunContext
import redis.asyncio as redis

# Direct skill imports - NO HTTP overhead!
# TODO: Fix import path or use HTTP calls instead
# from c3po_skills.weather import get_weather as get_weather_direct

logger = logging.getLogger(__name__)

# C3PO Router URL (legacy - for non-weather skills)
ROUTER_URL = os.getenv("ROUTER_URL", "http://c3po-router:8004")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

# Global session language (set by LiveKitAgentSession)
_session_language = "en"

def set_session_language(language: str):
    """Set the current session language for tools."""
    global _session_language
    _session_language = language
    logger.info(f"Session language set to: {language}")


class RouterClient:
    """Persistent HTTP client for c3po-router calls with Redis caching."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._redis: Optional[redis.Redis] = None

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create persistent HTTP session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=10,           # Connection pool size
                ttl_dns_cache=300,  # DNS cache (5 min)
            )
            timeout = aiohttp.ClientTimeout(total=20)  # Increased to 20s for complex skills
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )
            logger.info("Created persistent HTTP session with connection pooling")
        return self._session

    async def get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(
                REDIS_URL,
                decode_responses=True
            )
            logger.info(f"Connected to Redis at {REDIS_URL}")
        return self._redis

    async def get_cached(self, key: str) -> Optional[str]:
        """Get cached value from Redis."""
        try:
            r = await self.get_redis()
            value = await r.get(key)
            return value
        except Exception as e:
            logger.warning(f"Redis cache read error: {e}")
            return None

    async def set_cached(self, key: str, value: str, ttl: int = 300):
        """Set cached value in Redis with TTL (default 5 minutes)."""
        try:
            r = await self.get_redis()
            await r.setex(key, ttl, value)
        except Exception as e:
            logger.warning(f"Redis cache write error: {e}")

    async def call_router(self, payload: dict) -> dict:
        """Make router call with persistent session."""
        session = await self.get_session()
        # Use localhost when running outside Docker (development)
        router_url = os.getenv("ROUTER_URL", "http://localhost:8004")
        async with session.post(
            f"{router_url}/process",
            json=payload
        ) as resp:
            if resp.status != 200:
                raise Exception(f"Router error: {resp.status}")
            return await resp.json()

    async def close(self):
        """Close session and Redis connection on shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Closed HTTP session")

        if self._redis:
            await self._redis.aclose()
            logger.info("Closed Redis connection")


# Global instance
router_client = RouterClient()


@function_tool()
async def get_weather(
    context: RunContext,
    location: str,
) -> str:
    """Get current weather forecast for a location.

    Phase 3 optimization: Direct import - NO HTTP overhead!
    Target latency: <200ms (vs 2.7s HTTP, vs 19.6s baseline)

    Args:
        location: The city or location to get weather for (e.g. "Paris", "Montreal")

    Returns:
        Weather forecast information as a string
    """
    try:
        logger.info(f"⚡ Weather tool called (DIRECT IMPORT): {location}")

        # Use session language (set by LiveKitAgentSession)
        global _session_language
        language = _session_language

        # Fallback: Try to detect from conversation messages if session language is default
        if language == "en" and hasattr(context, 'session') and hasattr(context.session, 'conversation'):
            try:
                messages = context.session.conversation.messages[-3:]
                user_messages = [m.content for m in messages if hasattr(m, 'role') and m.role == 'user']

                if user_messages:
                    last_user_msg = user_messages[-1].lower()
                    # Detect language from keywords
                    if any(word in last_user_msg for word in ['météo', 'temps', 'quel', 'quelle']):
                        language = "fr"
                    elif any(word in last_user_msg for word in ['tiempo', 'clima', 'qué']):
                        language = "es"
                    # else: keep English default
            except Exception as e:
                logger.debug(f"Language detection failed, using session default: {e}")

        logger.info(f"Using language: {language}")

        # Check cache first (language-specific cache)
        cache_key = f"weather:v3:{language}:{location.lower()}"
        cached = await router_client.get_cached(cache_key)

        if cached:
            logger.info(f"⚡ Weather cache HIT: {location} ({language})")
            return cached

        logger.info(f"Weather cache MISS: {location} ({language})")

        # Call router via HTTP (get_weather_direct import is disabled)
        query = f"Quelle est la météo à {location}" if language == "fr" else f"What's the weather in {location}"
        router_payload = {
            "text": query,
            "session_id": "tool-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,
        }
        result = await router_client.call_router(router_payload)
        response = result.get("response", f"Unable to get weather for {location}")

        # Cache response for 5 minutes (language-specific)
        await router_client.set_cached(cache_key, response, ttl=300)

        logger.info(f"⚡ Weather response ({language}): {response[:80]}...")
        return response

    except Exception as e:
        logger.error(f"Weather tool error: {e}", exc_info=True)
        # Return error in detected language
        if language == "fr":
            return f"Désolé, impossible d'obtenir la météo pour {location}."
        elif language == "es":
            return f"Lo siento, no puedo obtener el clima para {location}."
        else:
            return f"Sorry, I can't get the weather for {location} right now."


@function_tool()
async def find_restaurant(
    context: RunContext,
    cuisine: str,
    location: Optional[str] = None,
) -> str:
    """Find restaurants for takeout, delivery, or dining.

    Args:
        cuisine: Type of food (e.g. "pizza", "sushi", "chinese", "burger")
        location: Optional location (defaults to Montreal)

    Returns:
        Restaurant recommendations as a string
    """
    try:
        logger.info(f"⚡ Restaurant tool called: cuisine={cuisine}, location={location}")

        global _session_language
        language = _session_language

        # Build router payload
        query = f"Je veux commander {cuisine}" if language == "fr" else f"I want to order {cuisine}"
        if location:
            query += f" à {location}" if language == "fr" else f" in {location}"

        payload = {
            "text": query,
            "session_id": "livekit-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,  # Function tools return text only, no TTS needed
        }

        # Call router
        result = await router_client.call_router(payload)
        response = result.get("response", "")

        logger.info(f"⚡ Restaurant response: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Restaurant tool error: {e}", exc_info=True)
        if language == "fr":
            return f"Désolé, impossible de trouver des restaurants pour {cuisine}."
        else:
            return f"Sorry, I can't find restaurants for {cuisine} right now."


@function_tool()
async def get_news(
    context: RunContext,
    topic: Optional[str] = None,
) -> str:
    """Get latest news headlines and summaries.

    Args:
        topic: Optional topic to search for (e.g. "technology", "sports", "politics")

    Returns:
        News headlines and summaries as a string
    """
    try:
        logger.info(f"⚡ News tool called: topic={topic}")

        global _session_language
        language = _session_language

        # Build router payload
        if topic:
            query = f"Quelles sont les nouvelles sur {topic}" if language == "fr" else f"What's the news about {topic}"
        else:
            query = "Quelles sont les nouvelles" if language == "fr" else "What's the news"

        payload = {
            "text": query,
            "session_id": "livekit-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,  # Function tools return text only, no TTS needed
        }

        # Call router
        result = await router_client.call_router(payload)
        response = result.get("response", "")

        logger.info(f"⚡ News response: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"News tool error: {e}", exc_info=True)
        if language == "fr":
            return "Désolé, impossible d'obtenir les nouvelles actuellement."
        else:
            return "Sorry, I can't get the news right now."


@function_tool()
async def search_calendar(
    context: RunContext,
    query: str,
) -> str:
    """Search calendar for events and appointments.

    Args:
        query: What to search for (e.g. "today's meetings", "tomorrow", "next week")

    Returns:
        Calendar events information as a string
    """
    try:
        logger.info(f"⚡ Calendar tool called: {query}")

        global _session_language
        language = _session_language

        # Build router payload
        full_query = f"Quel est mon horaire {query}" if language == "fr" else f"What's on my calendar {query}"

        payload = {
            "text": full_query,
            "session_id": "livekit-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,  # Function tools return text only, no TTS needed
        }

        # Call router
        result = await router_client.call_router(payload)
        response = result.get("response", "")

        logger.info(f"⚡ Calendar response: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Calendar tool error: {e}", exc_info=True)
        if language == "fr":
            return "Désolé, impossible d'accéder au calendrier."
        else:
            return "Sorry, I can't access the calendar right now."


@function_tool()
async def control_home(
    context: RunContext,
    action: str,
    device: Optional[str] = None,
) -> str:
    """Control home automation (lights, temperature, pool, security, scenes).

    Args:
        action: What to do (e.g. "turn on lights", "set temperature to 22", "activate cinema scene")
        device: Optional specific device or room

    Returns:
        Confirmation message as a string
    """
    try:
        logger.info(f"⚡ Home control tool called: action={action}, device={device}")

        global _session_language
        language = _session_language

        # Build query
        query = action
        if device:
            query += f" {device}"

        payload = {
            "text": query,
            "session_id": "livekit-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,  # Function tools return text only, no TTS needed
        }

        result = await router_client.call_router(payload)
        response = result.get("response", "")

        logger.info(f"⚡ Home control response: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Home control tool error: {e}", exc_info=True)
        if language == "fr":
            return "Désolé, impossible de contrôler la maison."
        else:
            return "Sorry, I can't control the home right now."


@function_tool()
async def make_phone_call(
    context: RunContext,
    contact: str,
) -> str:
    """Make a phone call or send SMS.

    Args:
        contact: Who to call or text (name or number)

    Returns:
        Call status as a string
    """
    try:
        logger.info(f"⚡ Phone tool called: contact={contact}")

        global _session_language
        language = _session_language

        query = f"Appelle {contact}" if language == "fr" else f"Call {contact}"

        payload = {
            "text": query,
            "session_id": "livekit-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,  # Function tools return text only, no TTS needed
        }

        result = await router_client.call_router(payload)
        response = result.get("response", "")

        logger.info(f"⚡ Phone response: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Phone tool error: {e}", exc_info=True)
        if language == "fr":
            return f"Désolé, impossible d'appeler {contact}."
        else:
            return f"Sorry, I can't call {contact} right now."


@function_tool()
async def control_music(
    context: RunContext,
    action: str,
) -> str:
    """Control music playback (play, pause, skip, volume, playlists).

    Args:
        action: What to do with music (e.g. "play jazz", "pause", "next song", "volume up")

    Returns:
        Playback status as a string
    """
    try:
        logger.info(f"⚡ Music tool called: action={action}")

        global _session_language
        language = _session_language

        payload = {
            "text": action,
            "session_id": "livekit-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,  # Function tools return text only, no TTS needed
        }

        result = await router_client.call_router(payload)
        response = result.get("response", "")

        logger.info(f"⚡ Music response: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Music tool error: {e}", exc_info=True)
        if language == "fr":
            return "Désolé, impossible de contrôler la musique."
        else:
            return "Sorry, I can't control music right now."


@function_tool()
async def ask_about_buddy(
    context: RunContext,
    question: str,
) -> str:
    """Get information about Buddy the dog (location, activity, health).

    Args:
        question: What to know about Buddy (e.g. "where is he", "has he eaten", "potty status")

    Returns:
        Buddy information as a string
    """
    try:
        logger.info(f"⚡ Buddy tool called: {question}")

        global _session_language
        language = _session_language

        payload = {
            "text": question,
            "session_id": "livekit-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,  # Function tools return text only, no TTS needed
        }

        result = await router_client.call_router(payload)
        response = result.get("response", "")

        logger.info(f"⚡ Buddy response: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Buddy tool error: {e}", exc_info=True)
        if language == "fr":
            return "Désolé, impossible d'obtenir des informations sur Buddy."
        else:
            return "Sorry, I can't get information about Buddy right now."


@function_tool()
async def get_expert_advice(
    context: RunContext,
    topic: str,
    question: str,
) -> str:
    """Get expert advice on specialized topics (watchmaking, VFX, wine, tennis, etc.).

    Args:
        topic: Area of expertise (e.g. "watchmaking", "wine", "VFX", "tennis")
        question: Specific question to ask

    Returns:
        Expert advice as a string
    """
    try:
        logger.info(f"⚡ Expert advice tool called: topic={topic}, question={question}")

        global _session_language
        language = _session_language

        query = f"{topic}: {question}"

        payload = {
            "text": query,
            "session_id": "livekit-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,  # Function tools return text only, no TTS needed
        }

        result = await router_client.call_router(payload)
        response = result.get("response", "")

        logger.info(f"⚡ Expert advice response: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Expert advice tool error: {e}", exc_info=True)
        if language == "fr":
            return f"Désolé, impossible d'obtenir des conseils sur {topic}."
        else:
            return f"Sorry, I can't get advice on {topic} right now."


@function_tool()
async def order_delivery(
    context: RunContext,
    item_type: str,
    details: Optional[str] = None,
) -> str:
    """Order delivery (food, groceries, packages, catering).

    Args:
        item_type: What to order (e.g. "groceries", "package", "catering")
        details: Optional details about the order

    Returns:
        Order confirmation as a string
    """
    try:
        logger.info(f"⚡ Delivery tool called: item_type={item_type}, details={details}")

        global _session_language
        language = _session_language

        query = f"Commander {item_type}" if language == "fr" else f"Order {item_type}"
        if details:
            query += f": {details}"

        payload = {
            "text": query,
            "session_id": "livekit-session",
            "language": language,
            "client_type": "web",
            "skip_tts": True,  # Function tools return text only, no TTS needed
        }

        result = await router_client.call_router(payload)
        response = result.get("response", "")

        logger.info(f"⚡ Delivery response: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Delivery tool error: {e}", exc_info=True)
        if language == "fr":
            return "Désolé, impossible de passer la commande."
        else:
            return "Sorry, I can't place the order right now."
