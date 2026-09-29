"use client";

import React, { useMemo } from "react";
import type { MicState } from "@/lib/runtime/useVoice";
import type { RunStatus } from "@/lib/runtime/types";

interface AgentOrbProps {
  micState: MicState;
  micLevel: number;
  runStatus: RunStatus | "idle" | "starting";
  currentTool?: string;
  activeAction?: string;
  className?: string;
  onClick?: () => void;
}

export const AgentOrb: React.FC<AgentOrbProps> = ({
  micState,
  micLevel,
  runStatus,
  currentTool,
  activeAction,
  className = "",
  onClick,
}) => {
  // Determine dominant visual mode
  const mode = useMemo(() => {
    if (micState === "listening") return "listening";
    if (micState === "transcribing") return "transcribing";
    if (micState === "speaking") return "speaking";
    if (runStatus === "running" || runStatus === "starting") return "executing";
    if (runStatus === "failed" || micState === "error") return "error";
    return "idle";
  }, [micState, runStatus]);

  // Audio level scaling
  const scaleLevel = Math.max(1, 1 + micLevel * 0.45);
  const glowIntensity = Math.min(1, 0.4 + micLevel * 0.6);

  const colors = useMemo(() => {
    switch (mode) {
      case "listening":
        return {
          core: "from-cyan-400 via-sky-500 to-blue-600",
          ring: "border-cyan-400/60 shadow-cyan-500/50",
          glow: "rgba(6, 182, 212, 0.45)",
          label: "LISTENING...",
          sublabel: "Speak naturally or release to send",
        };
      case "transcribing":
        return {
          core: "from-amber-400 via-orange-500 to-amber-600",
          ring: "border-amber-400/60 shadow-amber-500/50",
          glow: "rgba(245, 158, 11, 0.4)",
          label: "PROCESSING SPEECH...",
          sublabel: "Whisper STT transcription",
        };
      case "executing":
        return {
          core: "from-cyan-400 via-indigo-500 to-purple-600",
          ring: "border-cyan-400/80 shadow-cyan-500/60",
          glow: "rgba(99, 102, 241, 0.45)",
          label: currentTool ? `EXECUTING: ${currentTool.toUpperCase()}` : "AUTONOMOUS REASONING...",
          sublabel: activeAction || "Analyzing environment & invoking tools",
        };
      case "speaking":
        return {
          core: "from-emerald-400 via-teal-500 to-cyan-600",
          ring: "border-emerald-400/70 shadow-emerald-500/50",
          glow: "rgba(16, 185, 129, 0.45)",
          label: "JARVIS SPEAKING...",
          sublabel: "Audio voice synthesis active",
        };
      case "error":
        return {
          core: "from-rose-500 via-red-600 to-rose-700",
          ring: "border-rose-500/60 shadow-rose-500/40",
          glow: "rgba(244, 63, 94, 0.35)",
          label: "DIAGNOSTIC ALERT",
          sublabel: "Inspect telemetry stream",
        };
      default:
        return {
          core: "from-cyan-500/80 via-blue-600/70 to-indigo-800/80",
          ring: "border-cyan-500/30 shadow-cyan-500/20",
          glow: "rgba(6, 182, 212, 0.15)",
          label: "JARVIS ONLINE",
          sublabel: "Voice & Autonomous Agent Ready",
        };
    }
  }, [mode, currentTool, activeAction]);

  return (
    <div className={`relative flex flex-col items-center justify-center select-none ${className}`}>
      {/* Interactive Orb Canvas Container */}
      <div
        onClick={onClick}
        className="relative w-48 h-48 sm:w-56 sm:h-56 flex items-center justify-center cursor-pointer group"
        title="JARVIS Autonomous Core"
      >
        {/* Ambient Halo Glow */}
        <div
          className="absolute inset-0 rounded-full blur-2xl transition-all duration-300 pointer-events-none"
          style={{
            background: colors.glow,
            transform: `scale(${scaleLevel * 1.1})`,
            opacity: glowIntensity,
          }}
        />

        {/* Outer Rotating Cybernetic Ring */}
        <div
          className={`absolute inset-2 rounded-full border border-dashed ${colors.ring} transition-all duration-700 ${
            mode === "executing" || mode === "transcribing"
              ? "animate-spin"
              : "animate-[spin_12s_linear_infinite]"
          }`}
          style={{ transform: `scale(${scaleLevel})` }}
        />

        {/* Inner Counter-Rotating Ring */}
        <div
          className="absolute inset-6 rounded-full border border-cyan-500/20 animate-[spin_8s_linear_infinite_reverse]"
          style={{ transform: `scale(${scaleLevel * 0.95})` }}
        />

        {/* Core Reactor Sphere */}
        <div
          className={`relative w-28 h-28 sm:w-32 sm:h-32 rounded-full bg-gradient-to-tr ${colors.core} shadow-2xl flex items-center justify-center transition-all duration-200 group-hover:scale-105`}
          style={{
            transform: `scale(${scaleLevel})`,
            boxShadow: `0 0 35px ${colors.glow}`,
          }}
        >
          {/* Glass Specular Reflection Highlight */}
          <div className="absolute top-2 left-4 w-8 h-4 bg-white/30 rounded-full blur-[1px] transform -rotate-45" />

          {/* Core Status Symbol */}
          <div className="flex flex-col items-center justify-center text-white text-center font-mono">
            {mode === "listening" && (
              <div className="flex items-center space-x-1">
                <span className="w-1.5 h-4 bg-white rounded-full animate-[bounce_0.6s_infinite]" />
                <span className="w-1.5 h-6 bg-white rounded-full animate-[bounce_0.6s_infinite_0.15s]" />
                <span className="w-1.5 h-4 bg-white rounded-full animate-[bounce_0.6s_infinite_0.3s]" />
              </div>
            )}
            {mode === "transcribing" && (
              <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            )}
            {mode === "executing" && (
              <div className="text-xs font-black tracking-widest uppercase">ACT</div>
            )}
            {mode === "speaking" && (
              <div className="flex items-center space-x-1">
                <span className="w-1.5 h-5 bg-white rounded-full animate-pulse" />
                <span className="w-1.5 h-7 bg-white rounded-full animate-pulse" />
                <span className="w-1.5 h-3 bg-white rounded-full animate-pulse" />
              </div>
            )}
            {mode === "idle" && (
              <span className="text-sm font-black tracking-widest text-white/90">J_</span>
            )}
            {mode === "error" && (
              <span className="text-lg font-black text-white">!</span>
            )}
          </div>
        </div>
      </div>

      {/* Dynamic Status HUD Readout */}
      <div className="mt-3 flex flex-col items-center text-center space-y-0.5">
        <div className="flex items-center space-x-2 font-mono text-[11px] font-bold tracking-wider text-cyan-300">
          <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
          <span>{colors.label}</span>
        </div>
        <p className="text-[10px] font-mono text-zinc-400 max-w-xs truncate">
          {colors.sublabel}
        </p>
      </div>
    </div>
  );
};

export default AgentOrb;
