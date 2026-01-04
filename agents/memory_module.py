"""
Memory Module for C-3PO/ARIA Voice Agents

Provides persistent conversation memory using PostgreSQL.
Enables the agent to remember past conversations and provide
contextual responses based on history.

Features:
- Save conversation messages to database
- Retrieve relevant past conversations
- Generate memory summaries for context injection
- Track conversation topics and user preferences

Author: C-3PO Team
Date: 2026-01-03
"""
import asyncio
import asyncpg
import logging
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import uuid

logger = logging.getLogger(__name__)

# Database connection settings
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:0fLyI1ZIRn9NNensLGIZxoqQC0Ta9bxG3@localhost:5432/aistack"
)


@dataclass
class ConversationMessage:
    """A message in a conversation."""
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: datetime
    language: str = "en"
    emotion: Optional[str] = None
    vision_context: Optional[Dict[str, Any]] = None


@dataclass
class ConversationMemory:
    """Summary of past conversations for context injection."""
    recent_topics: List[str]
    user_preferences: Dict[str, Any]
    last_interaction: Optional[datetime]
    conversation_count: int
    notable_events: List[str]

    def to_prompt(self) -> str:
        """Convert memory to LLM-friendly prompt."""
        if self.conversation_count == 0:
            return ""

        parts = []

        # Time since last interaction
        if self.last_interaction:
            delta = datetime.now() - self.last_interaction
            if delta.days > 0:
                parts.append(f"It has been {delta.days} days since we last spoke.")
            elif delta.seconds > 3600:
                hours = delta.seconds // 3600
                parts.append(f"It has been {hours} hours since our last conversation.")

        # Recent topics
        if self.recent_topics:
            topics_str = ", ".join(self.recent_topics[:5])
            parts.append(f"Recent topics we discussed: {topics_str}.")

        # Notable events from past conversations
        if self.notable_events:
            parts.append(f"Things to remember: {'; '.join(self.notable_events[:3])}.")

        return " ".join(parts)


class C3POMemory:
    """
    Persistent memory for C-3PO and ARIA voice agents.

    Uses PostgreSQL to store and retrieve conversation history.
    """

    def __init__(self, database_url: str = DATABASE_URL):
        self.database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None
        self._current_conversation_id: Optional[int] = None
        self._current_session_id: Optional[str] = None
        self._message_order: int = 0

    async def connect(self) -> bool:
        """
        Create connection pool to PostgreSQL.

        Returns:
            True if connection successful
        """
        try:
            self._pool = await asyncpg.create_pool(
                self.database_url,
                min_size=1,
                max_size=5,
                command_timeout=10
            )
            logger.info("✓ Connected to PostgreSQL for conversation memory")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return False

    async def close(self):
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
            logger.info("Database connection closed")

    async def start_conversation(
        self,
        client_type: str = "web",
        language: str = "en",
        family_member_id: Optional[int] = None
    ) -> str:
        """
        Start a new conversation session.

        Args:
            client_type: Type of client (pi, web, phone, telegram)
            language: Language code (en, fr, es)
            family_member_id: Optional family member ID

        Returns:
            Conversation session ID
        """
        self._current_session_id = str(uuid.uuid4())[:8]
        self._message_order = 0

        if not self._pool:
            await self.connect()

        try:
            async with self._pool.acquire() as conn:
                conversation_id = f"livekit-{self._current_session_id}"
                result = await conn.fetchrow(
                    """
                    INSERT INTO ai_conversations
                    (conversation_id, client_type, language, family_member_id, started_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    RETURNING id
                    """,
                    conversation_id, client_type, language, family_member_id
                )
                self._current_conversation_id = result['id']
                logger.info(f"Started conversation {conversation_id} (id={self._current_conversation_id})")
                return conversation_id

        except Exception as e:
            logger.error(f"Failed to start conversation: {e}")
            return self._current_session_id

    async def save_message(
        self,
        role: str,
        content: str,
        language: str = "en",
        emotion: Optional[str] = None,
        vision_context: Optional[Dict] = None,
        llm_model: Optional[str] = None,
        llm_latency_ms: Optional[int] = None
    ) -> bool:
        """
        Save a message to the current conversation.

        Args:
            role: Message role (user, assistant, system)
            content: Message content
            language: Language code
            emotion: Detected emotion
            vision_context: Vision context dict
            llm_model: LLM model used
            llm_latency_ms: LLM response latency

        Returns:
            True if saved successfully
        """
        if not self._current_conversation_id or not self._pool:
            logger.warning("No active conversation - message not saved")
            return False

        self._message_order += 1

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO ai_messages
                    (conversation_id, role, content, language, message_order,
                     detected_emotion, vision_context, llm_model, llm_latency_ms)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    self._current_conversation_id, role, content, language,
                    self._message_order, emotion,
                    vision_context if vision_context else None,
                    llm_model, llm_latency_ms
                )
                logger.debug(f"Saved message: {role} ({len(content)} chars)")
                return True

        except Exception as e:
            logger.error(f"Failed to save message: {e}")
            return False

    async def end_conversation(self, skill_detected: Optional[str] = None):
        """
        End the current conversation.

        Args:
            skill_detected: Primary skill used in conversation
        """
        if not self._current_conversation_id or not self._pool:
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE ai_conversations
                    SET ended_at = NOW(), skill_detected = $2
                    WHERE id = $1
                    """,
                    self._current_conversation_id, skill_detected
                )
                logger.info(f"Ended conversation {self._current_conversation_id}")

        except Exception as e:
            logger.error(f"Failed to end conversation: {e}")

        self._current_conversation_id = None
        self._message_order = 0

    async def get_recent_conversations(
        self,
        client_type: Optional[str] = None,
        family_member_id: Optional[int] = None,
        limit: int = 10,
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Get recent conversations for context.

        Args:
            client_type: Filter by client type
            family_member_id: Filter by family member
            limit: Maximum conversations to return
            days: Look back period in days

        Returns:
            List of conversation summaries
        """
        if not self._pool:
            await self.connect()

        try:
            async with self._pool.acquire() as conn:
                query = """
                    SELECT
                        c.id, c.conversation_id, c.client_type, c.language,
                        c.skill_detected, c.started_at, c.ended_at,
                        COUNT(m.id) as message_count,
                        STRING_AGG(
                            CASE WHEN m.role = 'user' THEN m.content END,
                            ' | ' ORDER BY m.message_order
                        ) as user_messages
                    FROM ai_conversations c
                    LEFT JOIN ai_messages m ON m.conversation_id = c.id
                    WHERE c.started_at > NOW() - INTERVAL '%s days'
                """
                params = []
                param_idx = 1

                if client_type:
                    query += f" AND c.client_type = ${param_idx}"
                    params.append(client_type)
                    param_idx += 1

                if family_member_id:
                    query += f" AND c.family_member_id = ${param_idx}"
                    params.append(family_member_id)
                    param_idx += 1

                query += f"""
                    GROUP BY c.id
                    ORDER BY c.started_at DESC
                    LIMIT ${param_idx}
                """
                params.append(limit)

                # Execute with proper parameter substitution
                full_query = query % days
                rows = await conn.fetch(full_query, *params)

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get recent conversations: {e}")
            return []

    async def get_memory_context(
        self,
        family_member_id: Optional[int] = None,
        days: int = 30
    ) -> ConversationMemory:
        """
        Get memory context for LLM injection.

        Analyzes past conversations to extract:
        - Recent topics discussed
        - User preferences
        - Notable events mentioned

        Args:
            family_member_id: Filter by family member
            days: Look back period

        Returns:
            ConversationMemory with context for the agent
        """
        if not self._pool:
            await self.connect()

        try:
            async with self._pool.acquire() as conn:
                # Get recent conversations stats
                stats = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as conv_count,
                        MAX(started_at) as last_interaction,
                        ARRAY_AGG(DISTINCT skill_detected) FILTER (WHERE skill_detected IS NOT NULL) as skills
                    FROM ai_conversations
                    WHERE started_at > NOW() - INTERVAL '%s days'
                    AND ($1::int IS NULL OR family_member_id = $1)
                    """ % days,
                    family_member_id
                )

                # Get recent user messages for topic extraction
                messages = await conn.fetch(
                    """
                    SELECT content
                    FROM ai_messages m
                    JOIN ai_conversations c ON c.id = m.conversation_id
                    WHERE m.role = 'user'
                    AND c.started_at > NOW() - INTERVAL '%s days'
                    AND ($1::int IS NULL OR c.family_member_id = $1)
                    ORDER BY m.timestamp DESC
                    LIMIT 20
                    """ % days,
                    family_member_id
                )

                # Extract topics from skills used
                skills = stats['skills'] or []
                topics = [s for s in skills if s]

                # Look for notable events in messages (travel, appointments, etc.)
                notable_events = []
                event_keywords = {
                    "travel": ["voyage", "trip", "vacation", "flight", "airport"],
                    "appointment": ["appointment", "meeting", "rendez-vous", "doctor"],
                    "event": ["birthday", "anniversary", "party", "fête"],
                }

                for msg in messages:
                    content_lower = msg['content'].lower()
                    for event_type, keywords in event_keywords.items():
                        if any(kw in content_lower for kw in keywords):
                            # Extract a short snippet
                            notable_events.append(
                                f"{event_type}: {msg['content'][:100]}"
                            )
                            break

                return ConversationMemory(
                    recent_topics=topics[:5],
                    user_preferences={},
                    last_interaction=stats['last_interaction'],
                    conversation_count=stats['conv_count'] or 0,
                    notable_events=notable_events[:3]
                )

        except Exception as e:
            logger.error(f"Failed to get memory context: {e}")
            return ConversationMemory(
                recent_topics=[],
                user_preferences={},
                last_interaction=None,
                conversation_count=0,
                notable_events=[]
            )


# Singleton instance
_memory_instance: Optional[C3POMemory] = None


def get_memory() -> C3POMemory:
    """Get or create the memory module singleton."""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = C3POMemory()
    return _memory_instance


async def inject_memory_context(chat_ctx, family_member_id: Optional[int] = None) -> bool:
    """
    Inject memory context into chat at session start.

    Args:
        chat_ctx: The agent's chat context
        family_member_id: Optional family member ID for personalization

    Returns:
        True if memory was injected
    """
    memory = get_memory()

    try:
        context = await memory.get_memory_context(family_member_id=family_member_id)
        prompt = context.to_prompt()

        if prompt:
            chat_ctx.append(
                role="system",
                text=f"[Memory Context] {prompt}"
            )
            logger.info(f"Injected memory context: {prompt[:100]}...")
            return True

    except Exception as e:
        logger.error(f"Failed to inject memory context: {e}")

    return False
