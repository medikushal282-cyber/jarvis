"use client";

/**
 * Push-to-talk control with a live level meter.
 *
 * Hold to talk, release to send -- or click to toggle, since holding a mouse
 * button while watching a demo is awkward. The VAD ends the utterance on
 * silence either way.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

import type { MicState } from "@/lib/runtime/useVoice";

interface VoiceButtonProps {
  state: MicState;
  level: number;
  error: string | null;
  supported: boolean;
  onStart: () => void;
  onStop: () => void;
  onDismissError?: () => void;
  className?: string;
}

const BARS = 5;

const LABEL: Record<MicState, string> = {
  unsupported: "Voice unavailable",
  denied: "Mic blocked",
  idle: "Click to talk",
  listening: "Listening...",
  transcribing: "Transcribing...",
  speaking: "JARVIS speaking",
  error: "Voice error",
};

export const VoiceButton: React.FC<VoiceButtonProps> = ({
  state,
  level,
  error,
  supported,
  onStart,
  onStop,
  onDismissError,
  className = "",
}) => {
  const [held, setHeld] = useState(false);
  const holdRef = useRef(false);

  const disabled = !supported || state === "unsupported" || state === "denied";
  const active = state === "listening";
  const busy = state === "transcribing";

  const toggle = useCallback(() => {
    if (disabled || busy) return;
    if (active) {
      setHeld(false);
      holdRef.current = false;
      onStop();
    } else {
      holdRef.current = true;
      setHeld(true);
      onStart();
    }
  }, [disabled, busy, active, onStart, onStop]);

  // Space is push-to-talk, unless the user is typing.
  useEffect(() => {
    if (disabled) return;

    const isTyping = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      return (
        !!el &&
        (el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" ||
          el.isContentEditable)
      );
    };

    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || isTyping(e.target)) return;
      e.preventDefault();
      if (!holdRef.current) {
        holdRef.current = true;
        setHeld(true);
        onStart();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || isTyping(e.target)) return;
      e.preventDefault();
      if (holdRef.current) {
        holdRef.current = false;
        setHeld(false);
        onStop();
      }
    };

    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [onStart, onStop, disabled]);

  const normalized = Math.min(1, level / 0.08);

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={disabled || busy}
          onClick={(e) => {
            e.preventDefault();
            toggle();
          }}
          aria-label={LABEL[state]}
          aria-pressed={active}
          title={disabled ? "Voice unavailable - use the text box" : "Click to talk (or hold Space)"}
          className={[
            "relative flex h-11 w-11 items-center justify-center rounded-full border-2 transition-all",
            disabled
              ? "cursor-not-allowed border-neutral-700 bg-neutral-900 text-neutral-600"
              : active
                ? "border-red-500 bg-red-500/20 text-red-400 scale-105"
                : busy
                  ? "border-amber-500 bg-amber-500/10 text-amber-400 animate-pulse"
                  : "border-neutral-600 bg-neutral-900 text-neutral-300 hover:border-cyan-400 hover:text-cyan-300",
          ].join(" ")}
        >
          {active && (
            <span
              className="absolute inset-0 rounded-full border-2 border-red-500/60"
              style={{
                transform: `scale(${1 + normalized * 0.45})`,
                opacity: 1 - normalized * 0.6,
                transition: "transform 80ms linear, opacity 80ms linear",
              }}
            />
          )}
          <MicGlyph muted={disabled} />
        </button>

        <div className="flex h-6 items-end gap-[3px]" aria-hidden="true">
          {Array.from({ length: BARS }).map((_, i) => {
            const threshold = (i + 1) / BARS;
            const lit = active && normalized >= threshold * 0.55;
            return (
              <span
                key={i}
                className={`w-[3px] rounded-sm transition-all duration-75 ${
                  lit ? "bg-red-400" : "bg-neutral-700"
                }`}
                style={{ height: `${6 + i * 3}px` }}
              />
            );
          })}
        </div>

        <span
          className={`text-[11px] uppercase tracking-wider ${
            active ? "text-red-400" : busy ? "text-amber-400" : "text-neutral-500"
          }`}
        >
          {active ? "Click to stop" : LABEL[state]}
        </span>
      </div>

      {error && (
        <button
          type="button"
          onClick={onDismissError}
          className="self-start text-left text-[11px] text-amber-400/90 hover:text-amber-300"
        >
          {error} <span className="text-neutral-600">(dismiss)</span>
        </button>
      )}
    </div>
  );
};

const MicGlyph: React.FC<{ muted?: boolean }> = ({ muted }) => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
    {muted && <line x1="3" y1="3" x2="21" y2="21" />}
  </svg>
);

export default VoiceButton;
