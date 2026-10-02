import React, { useState } from "react";
import type { RunView } from "@/lib/runtime/runReducer";
import { Activity, ChevronDown, ChevronRight, Cpu } from "lucide-react";

interface ContextInspectorProps {
  run: RunView;
}

export default function ContextInspector({ run }: ContextInspectorProps) {
  const [isOpen, setIsOpen] = useState(false);

  const t = run.telemetry;
  const memoryEst = run.memoryTokensEst || 0;

  if (!t && memoryEst === 0) {
    return null; // No telemetry to show yet
  }

  // Assuming 128k context for most modern models if not specified
  const maxContext = 128000;
  const total = t ? t.total_tokens : memoryEst;
  const percentage = Math.min(100, Math.round((total / maxContext) * 100));

  // Determine a color based on usage
  let usageColor = "bg-fra-green";
  if (percentage > 70) usageColor = "bg-yellow-500";
  if (percentage > 90) usageColor = "bg-red-500";

  return (
    <div className="mt-4 border-2 border-fra-black bg-fra-cream font-mono text-xs shadow-brutal-sm">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center justify-between bg-neutral-200 p-2 font-black uppercase transition-colors hover:bg-neutral-300"
      >
        <div className="flex items-center space-x-2">
          <Cpu size={14} />
          <span>Context Telemetry</span>
          {t && (
            <span className="ml-2 inline-flex items-center space-x-1 rounded-full border border-black bg-white px-2 py-0.5 text-[9px]">
              <span className={`h-2 w-2 rounded-full ${usageColor}`}></span>
              <span>{t.total_tokens.toLocaleString()} TOKENS</span>
            </span>
          )}
        </div>
        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>

      {isOpen && (
        <div className="p-3">
          {t ? (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2 border-2 border-dashed border-neutral-300 p-2">
                <h4 className="border-b border-neutral-300 pb-1 font-bold uppercase text-neutral-500">Provider & Model</h4>
                <div className="grid grid-cols-2 gap-1">
                  <span className="font-bold">Provider:</span> <span>{t.provider}</span>
                  <span className="font-bold">Model:</span> <span className="truncate" title={t.model}>{t.model}</span>
                  <span className="font-bold">Worker ID:</span> <span>{t.worker_id || "default"}</span>
                </div>
              </div>

              <div className="space-y-2 border-2 border-dashed border-neutral-300 p-2">
                <h4 className="border-b border-neutral-300 pb-1 font-bold uppercase text-neutral-500">Authoritative Usage</h4>
                <div className="grid grid-cols-2 gap-1">
                  <span className="font-bold">Prompt:</span> <span>{t.prompt_tokens.toLocaleString()}</span>
                  <span className="font-bold">Completion:</span> <span>{t.completion_tokens.toLocaleString()}</span>
                  <span className="font-bold text-fra-green">Total:</span> <span className="font-bold text-fra-green">{t.total_tokens.toLocaleString()}</span>
                </div>
              </div>

              <div className="col-span-1 space-y-2 border-2 border-dashed border-neutral-300 p-2 md:col-span-2">
                <h4 className="border-b border-neutral-300 pb-1 font-bold uppercase text-neutral-500">Payload Estimates</h4>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div>
                    <div className="text-[10px] text-neutral-500">SYSTEM</div>
                    <div className="text-sm font-black">{t.system_tokens_est.toLocaleString()}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-neutral-500">MEMORY (OKF/Hindsight)</div>
                    <div className="text-sm font-black">{memoryEst.toLocaleString()}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-neutral-500">TOOLS SCHEMA</div>
                    <div className="text-sm font-black">{t.tool_tokens_est.toLocaleString()}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-neutral-500">USER / CONVERSATION</div>
                    <div className="text-sm font-black">{t.user_tokens_est.toLocaleString()}</div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center space-x-2 text-neutral-500">
              <Activity size={12} className="animate-pulse" />
              <span>Waiting for LLM response...</span>
              {memoryEst > 0 && <span>(Memory loaded: ~{memoryEst} tokens)</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
