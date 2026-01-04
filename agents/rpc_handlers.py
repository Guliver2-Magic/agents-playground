"""
LiveKit RPC Handlers for Function Tools

All RPC handlers call c3po-router instead of function tools directly,
because function tools require a RunContext that RPC handlers don't have.

Author: C-3PO Team
Date: 2026-01-03
"""
import json
import logging
from livekit.rtc import RpcInvocationData, RpcError
from livekit.rtc.participant import LocalParticipant

logger = logging.getLogger(__name__)


async def _call_router(query: str, language: str = "en") -> str:
    """Helper to call c3po-router with a natural language query."""
    from agents.tools import router_client

    router_payload = {
        "text": query,
        "session_id": "rpc-session",
        "language": language,
        "client_type": "web",
        "skip_tts": True,  # RPC calls return text only, no TTS needed
    }

    result = await router_client.call_router(router_payload)
    return result.get("response", "")


def register_rpc_methods(local_participant: LocalParticipant) -> None:
    """
    Register all function tools as RPC methods on the local participant.

    All handlers use c3po-router for processing instead of calling
    function tools directly (which require RunContext).
    """

    @local_participant.register_rpc_method("get_weather")
    async def rpc_get_weather(data: RpcInvocationData) -> str:
        """Get weather for a location."""
        try:
            payload = json.loads(data.payload)
            location = payload.get("location")
            language = payload.get("language", "en")

            if not location:
                raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'location' parameter")

            query = f"Quelle est la météo à {location}" if language == "fr" else f"What's the weather in {location}"
            response = await _call_router(query, language)

            logger.info(f"⚡ RPC Weather: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC get_weather error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    @local_participant.register_rpc_method("find_restaurant")
    async def rpc_find_restaurant(data: RpcInvocationData) -> str:
        """Find restaurants by cuisine or filters."""
        try:
            payload = json.loads(data.payload)
            cuisine = payload.get("cuisine") or payload.get("query")
            location = payload.get("location", "")
            language = payload.get("language", "en")

            if not cuisine:
                raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'cuisine' parameter")

            if language == "fr":
                query = f"Trouve-moi un restaurant {cuisine}" + (f" à {location}" if location else "")
            else:
                query = f"Find me a {cuisine} restaurant" + (f" in {location}" if location else "")

            response = await _call_router(query, language)

            logger.info(f"⚡ RPC Restaurant: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC find_restaurant error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    @local_participant.register_rpc_method("get_news")
    async def rpc_get_news(data: RpcInvocationData) -> str:
        """Get latest news headlines."""
        try:
            payload = json.loads(data.payload) if data.payload else {}
            topic = payload.get("topic", "")
            language = payload.get("language", "en")

            if language == "fr":
                query = f"Quelles sont les dernières nouvelles" + (f" sur {topic}" if topic else "")
            else:
                query = f"What's the latest news" + (f" about {topic}" if topic else "")

            response = await _call_router(query, language)

            logger.info(f"⚡ RPC News: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC get_news error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    @local_participant.register_rpc_method("search_calendar")
    async def rpc_search_calendar(data: RpcInvocationData) -> str:
        """Search calendar events."""
        try:
            payload = json.loads(data.payload)
            query = payload.get("query")
            language = payload.get("language", "en")

            if not query:
                raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'query' parameter")

            if language == "fr":
                nl_query = f"Qu'est-ce que j'ai au calendrier pour {query}"
            else:
                nl_query = f"What's on my calendar for {query}"

            response = await _call_router(nl_query, language)

            logger.info(f"⚡ RPC Calendar: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC search_calendar error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    @local_participant.register_rpc_method("control_home")
    async def rpc_control_home(data: RpcInvocationData) -> str:
        """Control home automation."""
        try:
            payload = json.loads(data.payload)
            action = payload.get("action")
            device = payload.get("device") or payload.get("target", "")
            language = payload.get("language", "en")

            if not action:
                raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'action' parameter")

            # Build natural language command
            query = f"{action}" + (f" {device}" if device else "")

            response = await _call_router(query, language)

            logger.info(f"⚡ RPC Home: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC control_home error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    @local_participant.register_rpc_method("make_phone_call")
    async def rpc_make_phone_call(data: RpcInvocationData) -> str:
        """Make a phone call."""
        try:
            payload = json.loads(data.payload)
            contact = payload.get("contact")
            number = payload.get("number")
            language = payload.get("language", "en")

            if not contact and not number:
                raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'contact' or 'number'")

            target = contact or number
            if language == "fr":
                query = f"Appelle {target}"
            else:
                query = f"Call {target}"

            response = await _call_router(query, language)

            logger.info(f"⚡ RPC Phone: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC make_phone_call error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    @local_participant.register_rpc_method("control_music")
    async def rpc_control_music(data: RpcInvocationData) -> str:
        """Control music playback."""
        try:
            payload = json.loads(data.payload)
            action = payload.get("action")
            language = payload.get("language", "en")

            if not action:
                raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'action' parameter")

            response = await _call_router(action, language)

            logger.info(f"⚡ RPC Music: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC control_music error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    @local_participant.register_rpc_method("ask_about_buddy")
    async def rpc_ask_about_buddy(data: RpcInvocationData) -> str:
        """Ask about Buddy the dog."""
        try:
            payload = json.loads(data.payload)
            question = payload.get("question")
            language = payload.get("language", "en")

            if not question:
                raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'question' parameter")

            response = await _call_router(question, language)

            logger.info(f"⚡ RPC Buddy: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC ask_about_buddy error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    @local_participant.register_rpc_method("get_expert_advice")
    async def rpc_get_expert_advice(data: RpcInvocationData) -> str:
        """Get expert advice on specialized topics."""
        try:
            payload = json.loads(data.payload)
            domain = payload.get("domain")
            question = payload.get("question")
            language = payload.get("language", "en")

            if not domain or not question:
                raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'domain' or 'question'")

            # Include domain context in the question
            if language == "fr":
                query = f"En tant qu'expert en {domain}, {question}"
            else:
                query = f"As a {domain} expert, {question}"

            response = await _call_router(query, language)

            logger.info(f"⚡ RPC Expert: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC get_expert_advice error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    @local_participant.register_rpc_method("order_delivery")
    async def rpc_order_delivery(data: RpcInvocationData) -> str:
        """Order delivery (food, groceries, packages)."""
        try:
            payload = json.loads(data.payload)
            item_type = payload.get("item_type") or payload.get("restaurant")
            details = payload.get("details") or payload.get("items", "")
            language = payload.get("language", "en")

            if not item_type:
                raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'item_type' parameter")

            # Convert list to string if needed
            if isinstance(details, list):
                details = ", ".join(str(item) for item in details)

            if language == "fr":
                query = f"Commander {item_type}" + (f": {details}" if details else "")
            else:
                query = f"Order {item_type}" + (f": {details}" if details else "")

            response = await _call_router(query, language)

            logger.info(f"⚡ RPC Delivery: {response[:80]}...")
            return json.dumps({"success": True, "data": response})

        except json.JSONDecodeError as e:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"RPC order_delivery error: {e}", exc_info=True)
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))

    logger.info("✓ Registered 10 RPC methods (all using router): get_weather, find_restaurant, get_news, search_calendar, control_home, make_phone_call, control_music, ask_about_buddy, get_expert_advice, order_delivery")
