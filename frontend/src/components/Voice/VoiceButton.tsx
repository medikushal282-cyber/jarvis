"use client";

/**
 * Talk button for the composer toolbar.
 *
 * Two ways to use it, both ending the same way:
 * - hold (mouse, touch or Space), speak, release to send;
 * - click once, speak, and the silence detector sends it -- or click again.
 * Pressing it while JARVIS is speaking interrupts the reply.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

import type { MicState } from "@/lib/runtime/useVoice";

interface VoiceButtonProps {
  state: MicState;
  level: number;
  error: string | null;
  supported: boolean;
  /** Block new utterances, e.g. while a run is in flight. */
  disabled?: boolean;
  onStart: () => void;
  onStop: () => void;
  onDismissError?: () => void;
  className?: string;
}

const BARS = 4;
/** A press shorter than this is a click (toggle), longer is a hold. */
const CLICK_MS = 350;

export const VoiceButton: React.FC<VoiceButtonProps> = ({
  state,
  level,
  error,
  supported,
  disabled = false,
  onStart,
  onStop,
  onDismissError,
  className = "",
}) => {
  const [held, setHeld] = useState(false);
  const holdRef = useRef(false);
  const pressedAtRef = useRef(0);

  const unavailable = !supported || state === "unsupported" || state === "denied";
  const listening = state === "listening";
  const busy = state === "transcribing";
  const blocked = unavailable || busy || (disabled && !listening);

  const begin = useCallback(() => {
    if (blocked) return;
    // Second click while listening in toggle mode: send now.
    if (listening && !holdRef.current) {
      onStop();
      return;
    }
    holdRef.current = true;
    pressedAtRef.current = performance.now();
    setHeld(true);
    onStart();
  }, [blocked, listening, onStart, onStop]);

  const end = useCallback(() => {
    if (!holdRef.current) return;
    holdRef.current = false;
    setHeld(false);
    // A quick click keeps listening; the silence detector or a second click ends it.
    if (performance.now() - pressedAtRef.current < CLICK_MS) return;
    onStop();
  }, [onStop]);

  // Space is push-to-talk, unless the user is typing somewhere.
  useEffect(() => {
    if (unavailable) return;

    const isTyping = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      return (
        !!el &&
        (el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" ||
          el.tagName === "SELECT" ||
          el.isContentEditable)
      );
    };

    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || isTyping(e.target)) return;
      e.preventDefault();
      begin();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || isTyping(e.target)) return;
      e.preventDefault();
      end();
    };

    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [begin, end, unavailable]);

  const normalized = Math.min(1, level / 0.08);

  let label: string;
  if (state === "unsupported") label = "No mic";
  else if (state === "denied") label = "Mic blocked";
  else if (busy) label = "Transcribing...";
  else if (listening) label = held ? "Release to send" : "Listening - click to send";
  else if (state === "speaking") label = "Speaking - press to interrupt";
  else if (disabled) label = "Voice";
  else label = "Talk";

  const tone = unavailable
    ? "border-neutral-400 bg-neutral-200 text-neutral-400 cursor-not-allowed"
    : listening
      ? "border-black bg-red-500 text-white"
      : busy
        ? "border-black bg-fra-yellow text-black animate-pulse cursor-wait"
        : state === "speaking"
          ? "border-black bg-black text-fra-yellow"
          : disabled
            ? "border-neutral-400 bg-white text-neutral-400 cursor-not-allowed"
            : "border-black bg-white text-black hover:bg-fra-yellow";

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <button
        type="button"
        disabled={blocked}
        onMouseDown={begin}
        onMouseUp={end}
        onMouseLeave={end}
        onTouchStart={(e) => {
          e.preventDefault();
          begin();
        }}
        onTouchEnd={(e) => {
          e.preventDefault();
          end();
        }}
        aria-label={label}
        aria-pressed={listening}
        title={
          unavailable
            ? "Voice unavailable - use the text box"
            : "Click or hold to talk (or hold Space)"
        }
        className={`relative flex h-7 w-7 shrink-0 items-center justify-center border-2 shadow-brutal-sm transition-colors ${tone}`}
      >
        {listening && (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 border-2 border-red-500"
            style={{
              transform: `scale(${1.1 + normalized * 0.5})`,
              opacity: 0.9 - normalized * 0.5,
              transition: "transform 80ms linear, opacity 80ms linear",
            }}
          />
        )}
        <MicGlyph muted={unavailable} />
      </button>

      {listening && (
        <div className="flex h-4 items-end gap-[2px]" aria-hidden="true">
          {Array.from({ length: BARS }).map((_, i) => (
            <span
              key={i}
              className={`w-[3px] transition-all duration-75 ${
                normalized >= ((i + 1) / BARS) * 0.55 ? "bg-red-500" : "bg-neutral-300"
              }`}
              style={{ height: `${5 + i * 3}px` }}
            />
          ))}
        </div>
      )}

      <span
        className={`font-mono text-[10px] font-bold uppercase tracking-wide ${
          listening ? "text-red-600" : "text-neutral-500"
        }`}
      >
        {label}
      </span>

      {error && (
        <button
          type="button"
          onClick={onDismissError}
          title="Dismiss"
          className="max-w-[220px] truncate font-mono text-[10px] text-red-600 hover:underline"
        >
          {error}
        </button>
      )}
    </div>
  );
};

const MicGlyph: React.FC<{ muted?: boolean }> = ({ muted }) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
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
