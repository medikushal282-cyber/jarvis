"use client";

/**
 * Self-contained voice control: owns the mic, the level meter and playback.
 *
 * The level meter updates every animation frame while listening. Keeping
 * that state here, instead of in the page, means only this small component
 * re-renders at 60fps -- not the whole workspace. The page talks to it
 * through a ref: `voiceRef.current?.speak(text)`.
 */

import React, { forwardRef, useImperativeHandle } from "react";

import type { Transcript } from "@/lib/runtime/types";
import { useVoice } from "@/lib/runtime/useVoice";

import VoiceButton from "./VoiceButton";

export interface VoiceControlHandle {
  speak: (text: string) => Promise<void>;
  stopSpeaking: () => void;
}

interface VoiceControlProps {
  sessionId?: string | null;
  workspaceId?: string | null;
  disabled?: boolean;
  onTranscript: (transcript: Transcript) => void;
  className?: string;
}

export const VoiceControl = forwardRef<VoiceControlHandle, VoiceControlProps>(
  function VoiceControl({ sessionId, workspaceId, disabled, onTranscript, className }, ref) {
    const voice = useVoice({ sessionId, workspaceId, onTranscript });

    useImperativeHandle(
      ref,
      () => ({ speak: voice.speak, stopSpeaking: voice.stopSpeaking }),
      [voice.speak, voice.stopSpeaking],
    );

    return (
      <VoiceButton
        state={voice.state}
        level={voice.level}
        error={voice.error}
        supported={voice.supported}
        disabled={disabled}
        onStart={() => void voice.start()}
        onStop={voice.stop}
        onDismissError={voice.clearError}
        className={className}
      />
    );
  },
);

export default VoiceControl;
