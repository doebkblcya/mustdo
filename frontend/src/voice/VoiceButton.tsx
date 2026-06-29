import type { PointerEvent } from "react";

import { MicIcon } from "../components/Icons";

interface VoiceButtonProps {
  recording: boolean;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
}

export function VoiceButton({ recording, onStart, onStop }: VoiceButtonProps) {
  async function handlePointerDown(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    await onStart();
  }

  async function handlePointerUp(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    await onStop();
  }

  return (
    <div className="voice-dock">
      <button
        className={`voice-button ${recording ? "recording" : ""}`}
        type="button"
        aria-label="按住说话"
        title="按住说话"
        onPointerDown={(event) => void handlePointerDown(event)}
        onPointerUp={(event) => void handlePointerUp(event)}
        onPointerCancel={() => void onStop()}
        onContextMenu={(event) => event.preventDefault()}
      >
        <MicIcon />
      </button>
    </div>
  );
}
