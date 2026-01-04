import { useState, useEffect } from "react";
import type { Participant, Room } from "livekit-client";

/**
 * Hook to reliably discover and track the agent participant in a LiveKit room.
 *
 * This hook handles the race condition where the agent may not have published
 * audio tracks yet, making `agent.internal.agentParticipant` undefined.
 *
 * It implements a fallback strategy:
 * 1. First, check agent.internal.agentParticipant
 * 2. If not found, search existing remote participants
 * 3. Listen for new participants joining the room
 *
 * @param room - LiveKit Room instance
 * @param internalAgentParticipant - agent.internal.agentParticipant
 * @returns The agent participant, or null if not found yet
 */
export function useAgentParticipant(
  room: Room,
  internalAgentParticipant?: Participant
): Participant | null {
  const [agentParticipant, setAgentParticipant] = useState<Participant | null>(
    null
  );

  useEffect(() => {
    // Primary: use internalAgentParticipant if available
    if (internalAgentParticipant) {
      setAgentParticipant(internalAgentParticipant);
      return;
    }

    // Fallback: Search existing participants for agent
    const findAgentParticipant = (): Participant | null => {
      const remoteParticipants = Array.from(room.remoteParticipants.values());
      return (
        remoteParticipants.find((p) => p.identity.startsWith("agent-")) || null
      );
    };

    // Check existing participants
    const existing = findAgentParticipant();
    if (existing) {
      setAgentParticipant(existing);
      return;
    }

    // Listen for new participants joining
    const handleParticipantConnected = (participant: Participant) => {
      if (participant.identity.startsWith("agent-")) {
        setAgentParticipant(participant);
      }
    };

    // Listen for participant disconnections
    const handleParticipantDisconnected = (participant: Participant) => {
      if (
        participant.identity.startsWith("agent-") &&
        agentParticipant?.identity === participant.identity
      ) {
        // Agent disconnected, reset
        setAgentParticipant(null);
      }
    };

    room.on("participantConnected", handleParticipantConnected);
    room.on("participantDisconnected", handleParticipantDisconnected);

    return () => {
      room.off("participantConnected", handleParticipantConnected);
      room.off("participantDisconnected", handleParticipantDisconnected);
    };
  }, [room, internalAgentParticipant, agentParticipant]);

  return agentParticipant;
}
