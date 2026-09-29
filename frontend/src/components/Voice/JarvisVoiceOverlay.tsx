"use client";

import React, { useEffect, useState } from "react";
import type { MicState } from "@/lib/runtime/useVoice";

interface JarvisVoiceOverlayProps {
  isOpen: boolean;
  state: MicState;
  level: number;
  transcriptText?: string;
  onClose?: () => void;
  onRelease?: () => void;
}

export const JarvisVoiceOverlay: React.FC<JarvisVoiceOverlayProps> = ({
  isOpen,
  state,
  level,
  transcriptText,
  onClose,
  onRelease,
}) => {
  if (!isOpen) return null;

  const audioScale = Math.max(1, 1 + level * 0.5);
  const glowOpacity = Math.min(1, 0.4 + level * 0.6);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-md animate-in fade-in duration-200 select-none"
      onMouseUp={onRelease}
      onTouchEnd={onRelease}
    >
      {/* Sci-Fi Grid Background */}
      <div
        className="absolute inset-0 opacity-20 pointer-events-none"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(255, 255, 255, 0.08) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(255, 255, 255, 0.08) 1px, transparent 1px)
          `,
          backgroundSize: "40px 40px",
        }}
      />

      {/* Radial Vignette */}
      <div className="absolute inset-0 bg-radial-gradient from-transparent via-black/50 to-black pointer-events-none" />

      {/* Central HUD Dial Container */}
      <div className="relative flex flex-col items-center justify-center">
        {/* Outer Dot Ring / Ticks */}
        <div className="relative w-80 h-80 sm:w-96 sm:h-96 flex items-center justify-center">
          {/* Outer Orbital Tick Dots */}
          <div className="absolute inset-0 rounded-full border border-zinc-800/60 animate-[spin_60s_linear_infinite]">
            {Array.from({ length: 24 }).map((_, i) => {
              const angle = (i * 360) / 24;
              return (
                <div
                  key={i}
                  className="absolute w-1.5 h-1.5 bg-zinc-400/80 rounded-full"
                  style={{
                    top: "50%",
                    left: "50%",
                    transform: `rotate(${angle}deg) translate(0, -180px)`,
                  }}
                />
              );
            })}
          </div>

          {/* Rotating Thin Arc 1 */}
          <div
            className="absolute inset-8 rounded-full border border-t-white border-r-transparent border-b-transparent border-l-transparent animate-[spin_8s_linear_infinite]"
            style={{ borderWidth: "2px" }}
          />

          {/* Rotating White Arc Segment (like user image) */}
          <div
            className="absolute inset-12 rounded-full border-l-4 border-l-white border-t-transparent border-r-transparent border-b-transparent animate-[spin_4s_linear_infinite_reverse]"
          />

          {/* Outer Cyan Ring 2 */}
          <div
            className="absolute inset-14 rounded-full border border-cyan-400/40 border-b-cyan-300 animate-[spin_6s_linear_infinite]"
          />

          {/* Glowing Cyan Halo Glow */}
          <div
            className="absolute w-44 h-44 sm:w-52 sm:h-52 rounded-full blur-xl bg-cyan-500/40 transition-all duration-100"
            style={{
              transform: `scale(${audioScale})`,
              opacity: glowOpacity,
            }}
          />

          {/* Main JARVIS Core Dial (Exact match to provided design) */}
          <div
            className="relative w-40 h-40 sm:w-48 sm:h-48 rounded-full bg-[#05070B] border-2 border-cyan-400 shadow-[0_0_30px_rgba(6,182,212,0.8)] flex items-center justify-center transition-transform duration-75"
            style={{
              transform: `scale(${audioScale})`,
            }}
          >
            {/* Inner Concentric Glow Ring */}
            <div className="absolute inset-1.5 rounded-full border border-cyan-300/60 shadow-[inset_0_0_15px_rgba(6,182,212,0.6)]" />

            {/* Glowing JARVIS Typography */}
            <span className="font-sans font-black text-2xl sm:text-3xl text-white tracking-[0.25em] pl-1 drop-shadow-[0_0_10px_rgba(255,255,255,0.9)]">
              JARVIS
            </span>
          </div>
        </div>

        {/* Live Status Readout */}
        <div className="mt-8 flex flex-col items-center text-center space-y-2 max-w-md px-4 z-10">
          <div className="flex items-center space-x-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-500/60 text-cyan-300 text-xs font-mono font-bold tracking-widest uppercase">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
            <span>
              {state === "listening"
                ? "LISTENING... (HOLD TO TALK)"
                : state === "transcribing"
                ? "WHISPER STT TRANSCRIBING..."
                : state === "speaking"
                ? "JARVIS SPEAKING..."
                : "VOICE SYSTEM ACTIVE"}
            </span>
          </div>

          <p className="text-xs font-mono text-zinc-300 max-w-sm">
            {state === "listening"
              ? "Release button to process speech and execute objective."
              : state === "transcribing"
              ? "Translating audio into autonomous agent plan..."
              : transcriptText || "Speak your goal clearly..."}
          </p>

          {/* Audio Waveform Meter */}
          {state === "listening" && (
            <div className="flex items-center space-x-1.5 pt-2">
              {Array.from({ length: 9 }).map((_, i) => {
                const h = Math.max(6, Math.min(32, (level * 100 * (1 + (i % 3) * 0.5))));
                return (
                  <div
                    key={i}
                    className="w-1 bg-cyan-400 rounded-full transition-all duration-75"
                    style={{ height: `${h}px` }}
                  />
                );
              })}
            </div>
          )}

          {/* Close hint */}
          <button
            onClick={onClose}
            className="text-[10px] font-mono text-zinc-500 hover:text-zinc-300 pt-3 underline underline-offset-4"
          >
            Cancel (Esc)
          </button>
        </div>
      </div>
    </div>
  );
};

export default JarvisVoiceOverlay;
