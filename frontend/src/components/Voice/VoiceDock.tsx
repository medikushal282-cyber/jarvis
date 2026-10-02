"use client";

/**
 * The composer's voice controls: push-to-talk, the HUD overlay while you
 * speak, and a stop button while JARVIS speaks.
 *
 * Owns the microphone state so the level meter (updated every animation
 * frame) re-renders only this component, not the whole workspace. The page
 * asks it to speak through a ref: `voiceRef.current?.speak(text)`.
 */

import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import type { Transcript } from "@/lib/runtime/types";
import { useVoice } from "@/lib/runtime/useVoice";

import JarvisVoiceOverlay from "./JarvisVoiceOverlay";

export interface VoiceDockHandle {
  speak: (text: string) => Promise<void>;
  stopSpeaking: () => void;
}

interface VoiceDockProps {
  sessionId?: string | null;
  workspaceId?: string | null;
  /** Blocks new utterances while a run is in flight. */
  disabled?: boolean;
  /** A run is in flight: shown as EXECUTING between listening and speaking. */
  executing?: boolean;
  onTranscript: (transcript: Transcript) => void;
}

type Phase = "LISTENING" | "TRANSCRIBING" | "EXECUTING" | "SPEAKING" | "IDLE";

const PHASE_STYLE: Record<Phase, string> = {
  LISTENING: "border-red-600 bg-red-500 text-white animate-pulse",
  TRANSCRIBING: "border-black bg-amber-300 text-black animate-pulse",
  EXECUTING: "border-black bg-fra-yellow text-black",
  SPEAKING: "border-black bg-black text-fra-yellow",
  IDLE: "border-neutral-300 bg-white text-neutral-400",
};

export const VoiceDock = forwardRef<VoiceDockHandle, VoiceDockProps>(function VoiceDock(
  { sessionId, workspaceId, disabled = false, executing = false, onTranscript },
  ref,
) {
  const [overlayOpen, setOverlayOpen] = useState(false);

  const voice = useVoice({
    sessionId,
    workspaceId,
    onTranscript: (t) => {
      setOverlayOpen(false);
      onTranscript(t);
    },
  });

  useImperativeHandle(
    ref,
    () => ({ speak: voice.speak, stopSpeaking: voice.stopSpeaking }),
    [voice.speak, voice.stopSpeaking],
  );

  // Close the overlay when listening ends without a transcript (silence,
  // an error, a denied mic) instead of leaving it stuck open.
  const wasBusy = useRef(false);
  useEffect(() => {
    if (voice.state === "listening" || voice.state === "transcribing") {
      wasBusy.current = true;
    } else {
      if (wasBusy.current) {
        setOverlayOpen(false);
        wasBusy.current = false;
      }
    }
  }, [voice.state]);

  const unavailable = !voice.supported || voice.state === "unsupported" || voice.state === "denied";
  const blocked = disabled || unavailable || voice.state === "transcribing";

  const mouseDownTime = useRef<number>(0);
  const autoStopTimer = useRef<NodeJS.Timeout | null>(null);
  const [tapMode, setTapMode] = useState(false);

  const phase: Phase =
    voice.state === "listening"
      ? "LISTENING"
      : voice.state === "transcribing"
        ? "TRANSCRIBING"
        : voice.state === "speaking"
          ? "SPEAKING"
          : executing
            ? "EXECUTING"
            : "IDLE";

  const begin = () => {
    if (blocked) return;
    mouseDownTime.current = Date.now();
    setTapMode(false);
    if (autoStopTimer.current) clearTimeout(autoStopTimer.current);
    
    setOverlayOpen(true);
    void voice.start();
  };

  const end = () => {
    if (blocked) return;
    const duration = Date.now() - mouseDownTime.current;
    
    if (duration < 300) {
      // Tap mode: stay open for 10s
      setTapMode(true);
      autoStopTimer.current = setTimeout(() => {
        voice.stop();
        setTapMode(false);
      }, 10000);
    } else {
      // Hold mode: stop immediately
      voice.stop();
      setTapMode(false);
    }
  };

  return (
    <>
      <span
        role="status"
        aria-live="polite"
        title="Voice status"
        className={`hidden border px-1.5 py-0.5 font-mono text-[9px] font-extrabold tracking-wide sm:inline ${PHASE_STYLE[phase]}`}
      >
        {phase}
      </span>
      {voice.error && (
        <button
          type="button"
          onClick={voice.clearError}
          title="Dismiss"
          className="hidden max-w-[200px] truncate font-mono text-[10px] text-red-600 hover:underline md:inline"
        >
          {voice.error}
        </button>
      )}

      {voice.state === "speaking" && (
        <button
          type="button"
          onClick={() => voice.stopSpeaking()}
          className="flex items-center space-x-1.5 border-2 border-black bg-red-500 px-3 py-1.5 font-mono text-xs font-bold text-white shadow-brutal-sm transition-transform hover:bg-red-600 active:scale-95"
          title="Stop JARVIS speaking"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
            <line x1="23" y1="9" x2="17" y2="15" />
            <line x1="17" y1="9" x2="23" y2="15" />
          </svg>
          <span>STOP AUDIO</span>
        </button>
      )}

      <button
        type="button"
        disabled={blocked}
        onMouseDown={begin}
        onMouseUp={end}
        onTouchStart={(e) => {
          e.preventDefault();
          begin();
        }}
        onTouchEnd={(e) => {
          e.preventDefault();
          end();
        }}
        className={`flex items-center space-x-1.5 border-2 border-fra-black px-3 py-1.5 font-mono text-xs font-bold shadow-brutal-sm transition-transform active:scale-95 ${
          blocked
            ? "cursor-not-allowed bg-neutral-300 text-neutral-500"
            : "cursor-pointer bg-fra-yellow text-black hover:bg-fra-yellow-hover"
        }`}
        title={
          unavailable
            ? "Voice unavailable - use the text box"
            : "Click and speak, or hold to talk"
        }
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="22" />
        </svg>
        <span>VOICE</span>
      </button>

      <JarvisVoiceOverlay
        isOpen={overlayOpen}
        state={voice.state}
        level={voice.level}
        transcriptText={voice.transcript?.text}
        onClose={() => {
          voice.stop();
          setTapMode(false);
          setOverlayOpen(false);
          if (autoStopTimer.current) clearTimeout(autoStopTimer.current);
        }}
        onRelease={() => {
          if (!tapMode) {
             end();
          }
        }}
      />
    </>
  );
});

export default VoiceDock;
