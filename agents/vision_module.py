"""
Vision Module for C-3PO Agent

Connects to the Vision Service (port 8006) for:
- Object detection (YOLOv8 - Buddy tracking)
- Face recognition with Master detection
- UniFi camera integration
- System status monitoring (GPU, memory)

Personalization Features:
- Master Recognition: Greet known persons by name
- Buddy Alerts: Contextual warnings when dog is near equipment
- System Status: Report GPU temperature and system health

Author: C-3PO Team
Date: 2026-01-03
"""
import asyncio
import aiohttp
import logging
import subprocess
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)

VISION_SERVICE_URL = "http://localhost:8006"

# Known masters/family members (names must match Vision Service face database)
KNOWN_MASTERS = {
    "Patrick": {"title": "Master Patrick", "role": "owner"},
    "Sophie": {"title": "Madame Sophie", "role": "family"},
    "Alexandre": {"title": "Young Master Alexandre", "role": "family"},
    "Olivier": {"title": "Master Olivier", "role": "family"},
}

# Locations with expensive/sensitive equipment
DANGER_ZONES = {
    "office": ["expensive equipment", "computer setup", "cables"],
    "studio": ["recording equipment", "microphones", "cameras"],
    "kitchen": ["food", "garbage", "counter"],
    "basement": ["electrical panels", "server rack", "networking equipment"],
}

# Buddy behavior warnings based on location
BUDDY_WARNINGS = {
    "office": "Oh dear, Buddy is near the expensive equipment again!",
    "studio": "I must warn you, Buddy appears to be in the studio. The microphones!",
    "kitchen": "Buddy is in the kitchen. I do hope he's not eyeing the counter.",
    "basement": "Sir, Buddy has ventured into the basement near the servers!",
    "garage": "Buddy is in the garage. Do ensure the door is secure.",
    "default": "Buddy is {status} in the {location}.",
}


class AlertSeverity(Enum):
    """Severity levels for visual alerts."""
    INFO = "info"
    WARNING = "warning"
    URGENT = "urgent"


@dataclass
class SystemStatus:
    """System hardware status for C-3PO self-awareness."""
    gpu_temp: Optional[float] = None
    gpu_util: Optional[float] = None
    gpu_memory_used: Optional[float] = None
    gpu_memory_total: Optional[float] = None
    cpu_temp: Optional[float] = None

    def to_prompt(self) -> str:
        """Convert system status to C-3PO style prompt."""
        if self.gpu_temp is None:
            return ""

        # Temperature-based personality responses
        if self.gpu_temp < 50:
            temp_comment = "functioning at optimal temperatures"
        elif self.gpu_temp < 70:
            temp_comment = "operating within normal parameters"
        elif self.gpu_temp < 80:
            temp_comment = "running a bit warm but still within acceptable limits"
        else:
            temp_comment = "running quite hot! I do hope we don't overheat"

        return f"My processing units are currently at {self.gpu_temp:.0f} degrees, {temp_comment}."


@dataclass
class VisualContext:
    """Current visual context for the agent."""
    timestamp: datetime
    buddy_location: Optional[str] = None
    buddy_status: Optional[str] = None
    buddy_alert: Optional[str] = None
    buddy_severity: AlertSeverity = AlertSeverity.INFO
    persons_detected: List[str] = field(default_factory=list)
    masters_detected: List[Dict[str, str]] = field(default_factory=list)
    objects_detected: List[str] = field(default_factory=list)
    system_status: Optional[SystemStatus] = None
    scene_description: str = "No visual context available"

    def get_master_greeting(self) -> Optional[str]:
        """Generate personalized greeting for detected masters."""
        if not self.masters_detected:
            return None

        greetings = []
        for master in self.masters_detected:
            title = master.get("title", master.get("name", "Sir"))
            if master.get("role") == "owner":
                greetings.append(f"Hello, {title}! I am at your service.")
            else:
                greetings.append(f"Good to see you, {title}.")

        return " ".join(greetings)

    def get_buddy_alert(self) -> Optional[str]:
        """Get contextual Buddy alert based on location."""
        if not self.buddy_location:
            return None

        location_lower = self.buddy_location.lower()

        # Check for danger zones
        if location_lower in BUDDY_WARNINGS:
            return BUDDY_WARNINGS[location_lower]

        # Default message
        return BUDDY_WARNINGS["default"].format(
            status=self.buddy_status or "present",
            location=self.buddy_location
        )

    def to_prompt(self) -> str:
        """Convert visual context to C-3PO style LLM prompt."""
        parts = []

        # Master greeting (highest priority)
        master_greeting = self.get_master_greeting()
        if master_greeting:
            parts.append(master_greeting)

        # Buddy status with contextual warnings
        buddy_alert = self.get_buddy_alert()
        if buddy_alert:
            parts.append(buddy_alert)

        # Other persons (non-masters)
        other_persons = [p for p in self.persons_detected
                        if p not in [m.get("name") for m in self.masters_detected]]
        if other_persons:
            if len(other_persons) == 1:
                parts.append(f"I also detect {other_persons[0]} nearby.")
            else:
                parts.append(f"I also detect: {', '.join(other_persons)}.")

        # System status
        if self.system_status:
            status_prompt = self.system_status.to_prompt()
            if status_prompt:
                parts.append(status_prompt)

        return " ".join(parts) if parts else self.scene_description


class C3POVision:
    """
    Vision integration for C-3PO agent.

    Uses the existing Vision Service (port 8006) for all CV operations.
    This avoids loading YOLO/face_recognition in the agent process.

    Features:
    - Master recognition with personalized greetings
    - Buddy tracking with contextual alerts
    - System status monitoring (GPU temperature)
    """

    def __init__(self, base_url: str = VISION_SERVICE_URL):
        self.base_url = base_url
        self.last_context = VisualContext(timestamp=datetime.now())
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_system_check: Optional[datetime] = None
        self._cached_system_status: Optional[SystemStatus] = None
        self._system_check_interval = timedelta(seconds=30)  # Cache for 30s

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        return self._session

    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def get_system_status(self) -> SystemStatus:
        """
        Get GPU and system status via nvidia-smi.

        Returns:
            SystemStatus with GPU temperature, utilization, memory
        """
        # Use cached value if recent enough
        now = datetime.now()
        if (self._last_system_check and self._cached_system_status and
            now - self._last_system_check < self._system_check_interval):
            return self._cached_system_status

        try:
            # Query nvidia-smi for GPU stats
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2
            )

            if result.returncode == 0:
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 4:
                    self._cached_system_status = SystemStatus(
                        gpu_temp=float(parts[0]),
                        gpu_util=float(parts[1]),
                        gpu_memory_used=float(parts[2]),
                        gpu_memory_total=float(parts[3])
                    )
                    self._last_system_check = now
                    logger.debug(f"GPU Status: {self._cached_system_status}")
                    return self._cached_system_status

        except subprocess.TimeoutExpired:
            logger.warning("nvidia-smi timed out")
        except FileNotFoundError:
            logger.debug("nvidia-smi not found (no GPU)")
        except Exception as e:
            logger.error(f"Failed to get GPU status: {e}")

        return SystemStatus()

    def identify_masters(self, persons: List[str]) -> Tuple[List[Dict[str, str]], List[str]]:
        """
        Identify known masters from detected persons.

        Args:
            persons: List of detected person names

        Returns:
            Tuple of (masters_list, other_persons_list)
        """
        masters = []
        others = []

        for name in persons:
            if name in KNOWN_MASTERS:
                master_info = KNOWN_MASTERS[name].copy()
                master_info["name"] = name
                masters.append(master_info)
            else:
                others.append(name)

        return masters, others

    async def get_buddy_status(self) -> Dict[str, Any]:
        """
        Get Buddy's current location and status from Vision Service.

        Returns:
            Dict with status, location, lastSeen, etc.
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/buddy/status") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.debug(f"Buddy status: {data}")
                    return data
                else:
                    logger.warning(f"Vision service returned {resp.status}")
                    return {}
        except Exception as e:
            logger.error(f"Failed to get Buddy status: {e}")
            return {}

    async def get_recent_sightings(self, hours: int = 1) -> List[Dict[str, Any]]:
        """
        Get recent pet sightings.

        Args:
            hours: Number of hours to look back

        Returns:
            List of sighting records
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/buddy/sightings", params={"hours": hours}) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
        except Exception as e:
            logger.error(f"Failed to get sightings: {e}")
            return []

    async def get_persons_in_view(self) -> List[str]:
        """
        Get list of recognized persons currently visible.

        Returns:
            List of person names
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/faces/current") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [p.get("name", "Unknown") for p in data.get("persons", [])]
                return []
        except Exception as e:
            logger.debug(f"Face detection not available: {e}")
            return []

    async def update_context(self, include_system_status: bool = False) -> VisualContext:
        """
        Update and return current visual context with personalization.

        Fetches latest data from Vision Service and builds context with:
        - Master recognition and greetings
        - Buddy location with contextual warnings
        - Optional system status

        Args:
            include_system_status: Include GPU temperature info

        Returns:
            VisualContext with personalized data
        """
        # Get Buddy status
        buddy_data = await self.get_buddy_status()

        # Get persons and identify masters
        persons = await self.get_persons_in_view()
        masters, other_persons = self.identify_masters(persons)

        # Determine Buddy alert severity based on location
        buddy_location = buddy_data.get("location")
        severity = AlertSeverity.INFO
        if buddy_location and buddy_location.lower() in DANGER_ZONES:
            severity = AlertSeverity.WARNING

        # Get system status if requested
        system_status = None
        if include_system_status:
            system_status = self.get_system_status()

        # Build context
        self.last_context = VisualContext(
            timestamp=datetime.now(),
            buddy_location=buddy_location,
            buddy_status=buddy_data.get("status", "unknown"),
            buddy_severity=severity,
            persons_detected=persons,
            masters_detected=masters,
            objects_detected=[],
            system_status=system_status,
            scene_description=f"Last update: {datetime.now().strftime('%H:%M:%S')}"
        )

        logger.info(f"Visual context updated: masters={[m['name'] for m in masters]}, "
                   f"buddy={buddy_location}, gpu_temp={system_status.gpu_temp if system_status else 'N/A'}")

        return self.last_context

    async def describe_scene(self, include_system_status: bool = False) -> str:
        """
        Get a natural language description of the current scene.

        Args:
            include_system_status: Include GPU temperature in description

        Returns:
            Human-readable scene description for the LLM
        """
        await self.update_context(include_system_status=include_system_status)
        return self.last_context.to_prompt()

    def should_check_vision(self, text: str) -> Tuple[bool, bool]:
        """
        Determine if the user's query requires visual or system context.

        Args:
            text: User's speech text

        Returns:
            Tuple of (needs_vision, needs_system_status)
        """
        text_lower = text.lower()

        # Vision-related keywords
        vision_keywords = [
            # English - People
            "who is", "who's", "anyone", "somebody", "someone",
            # English - Seeing
            "look", "see", "watch", "camera", "what do you see",
            # English - Buddy
            "buddy", "dog", "where is", "where's", "puppy",
            # French - People
            "qui est", "quelqu'un", "personne",
            # French - Seeing
            "regarde", "vois", "caméra", "tu vois",
            # French - Buddy
            "buddy", "chien", "où est", "toutou",
        ]

        # System status keywords
        system_keywords = [
            # English
            "temperature", "gpu", "how are you", "status", "health",
            "processing", "system", "running hot", "overheating",
            # French
            "température", "état", "comment vas-tu", "ça va",
            "système", "santé", "chaud",
        ]

        needs_vision = any(keyword in text_lower for keyword in vision_keywords)
        needs_system = any(keyword in text_lower for keyword in system_keywords)

        return needs_vision, needs_system


# Singleton instance
_vision_instance: Optional[C3POVision] = None


def get_vision() -> C3POVision:
    """Get or create the vision module singleton."""
    global _vision_instance
    if _vision_instance is None:
        _vision_instance = C3POVision()
    return _vision_instance


async def inject_visual_context(chat_ctx, user_text: str) -> bool:
    """
    Inject visual context into chat if needed.

    Automatically detects if the user's query requires:
    - Vision context (face recognition, Buddy tracking)
    - System status (GPU temperature, health)

    Args:
        chat_ctx: The agent's chat context
        user_text: User's speech text

    Returns:
        True if context was injected
    """
    vision = get_vision()

    needs_vision, needs_system = vision.should_check_vision(user_text)

    if needs_vision or needs_system:
        description = await vision.describe_scene(include_system_status=needs_system)
        if description and description != "No visual context available":
            chat_ctx.append(
                role="system",
                text=f"[Visual Context] {description}"
            )
            logger.info(f"Injected visual context: {description}")
            return True

    return False


async def get_proactive_context() -> Optional[str]:
    """
    Get proactive visual context without user query.

    Called at conversation start to greet masters or warn about Buddy.

    Returns:
        Context string if there's something proactive to say, None otherwise
    """
    vision = get_vision()
    await vision.update_context(include_system_status=False)
    context = vision.last_context

    parts = []

    # Greet masters proactively
    greeting = context.get_master_greeting()
    if greeting:
        parts.append(greeting)

    # Warn about Buddy in danger zones proactively
    if context.buddy_severity == AlertSeverity.WARNING:
        alert = context.get_buddy_alert()
        if alert:
            parts.append(alert)

    return " ".join(parts) if parts else None
