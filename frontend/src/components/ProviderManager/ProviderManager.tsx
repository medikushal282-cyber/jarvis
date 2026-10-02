"use client";

import React, { useState, useEffect, useRef } from "react";
import { Key, CheckCircle, AlertCircle, RefreshCw, Trash2, Eye, EyeOff, ExternalLink, Cpu, Sliders, Check, X } from "lucide-react";
import { API_BASE } from "@/lib/runtime/client";

export interface ProviderModel {
  id: string;
  name: string;
  provider: string;
  provider_name: string;
  context_window: string;
  badge: string;
  tags: string[];
  description: string;
  available?: boolean;
  status_text?: string;
  priority?: number;
  enabled?: boolean;
}

export interface ProviderInfo {
  id: string;
  name: string;
  company: string;
  env_var: string;
  docs_url: string;
  description: string;
  badge: string;
  configured: boolean;
  key_hint: string;
  status: "connected" | "unconfigured" | "error" | "offline";
  models_count: number;
  enabled_models_count: number;
  models: ProviderModel[];
}

interface ProviderManagerProps {
  isOpen?: boolean;
  onClose?: () => void;
  standaloneTrigger?: boolean;
}

export default function ProviderManager({
  isOpen: controlledIsOpen,
  onClose: controlledOnClose,
  standaloneTrigger = true,
}: ProviderManagerProps) {
  const [internalIsOpen, setInternalIsOpen] = useState(false);
  const isOpen = controlledIsOpen !== undefined ? controlledIsOpen : internalIsOpen;
  
  const setIsOpen = React.useCallback((val: boolean) => {
    if (controlledOnClose && !val) {
      controlledOnClose();
    } else {
      setInternalIsOpen(val);
    }
  }, [controlledOnClose]);

  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState<string>("gemini");
  const [loading, setLoading] = useState(false);
  
  // Key form state
  const [inputKey, setInputKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [savingKey, setSavingKey] = useState(false);
  const [statusFeedback, setStatusFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);
  
  // Model search inside provider view
  const [modelSearch, setModelSearch] = useState("");

  const modalRef = useRef<HTMLDivElement>(null);

  const fetchProviders = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/providers`);
      if (res.ok) {
        const data = await res.json();
        setProviders(data.providers || []);
      }
    } catch (e) {
      console.error("Failed to load providers:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProviders();
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchProviders();
      setInputKey("");
      setStatusFeedback(null);
    }
  }, [isOpen]);

  // Click outside to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, setIsOpen]);

  const activeProvider = providers.find((p) => p.id === selectedProviderId) || providers[0];

  const handleSaveKey = async () => {
    if (!inputKey.trim() || !activeProvider) return;
    setSavingKey(true);
    setStatusFeedback(null);

    try {
      const res = await fetch(`${API_BASE}/api/providers/${activeProvider.id}/key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: inputKey.trim() }),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        setStatusFeedback({
          type: "success",
          message: `✓ Key saved! Found ${data.models_found || 0} models for ${activeProvider.name}.`,
        });
        setInputKey("");
        await fetchProviders();
      } else {
        setStatusFeedback({
          type: "error",
          message: data.detail || data.message || "Failed to validate API key.",
        });
      }
    } catch (err: any) {
      setStatusFeedback({
        type: "error",
        message: err.message || "Network error while saving key.",
      });
    } finally {
      setSavingKey(false);
    }
  };

  const handleDeleteKey = async () => {
    if (!activeProvider) return;
    if (!confirm(`Remove API key for ${activeProvider.name}?`)) return;

    try {
      const res = await fetch(`${API_BASE}/api/providers/${activeProvider.id}/key`, {
        method: "DELETE",
      });
      if (res.ok) {
        setStatusFeedback({
          type: "success",
          message: `Removed key for ${activeProvider.name}.`,
        });
        await fetchProviders();
      }
    } catch (e: any) {
      setStatusFeedback({
        type: "error",
        message: e.message || "Could not delete key.",
      });
    }
  };

  const handleToggleModel = async (modelId: string, currentEnabled: boolean) => {
    const nextEnabled = !currentEnabled;
    // Optimistic UI update
    setProviders((prev) =>
      prev.map((prov) => {
        if (prov.id === activeProvider?.id) {
          return {
            ...prov,
            enabled_models_count: nextEnabled
              ? prov.enabled_models_count + 1
              : Math.max(0, prov.enabled_models_count - 1),
            models: prov.models.map((m) => (m.id === modelId ? { ...m, enabled: nextEnabled } : m)),
          };
        }
        return prov;
      })
    );

    try {
      await fetch(`${API_BASE}/api/models/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: modelId, enabled: nextEnabled }),
      });
    } catch (e) {
      console.error("Failed to toggle model:", e);
      // Revert
      await fetchProviders();
    }
  };

  const handleToggleAll = async (enabled: boolean) => {
    if (!activeProvider) return;
    setProviders((prev) =>
      prev.map((prov) => {
        if (prov.id === activeProvider.id) {
          return {
            ...prov,
            enabled_models_count: enabled ? prov.models.length : 0,
            models: prov.models.map((m) => ({ ...m, enabled })),
          };
        }
        return prov;
      })
    );

    try {
      await fetch(`${API_BASE}/api/providers/${activeProvider.id}/toggle-all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
    } catch (e) {
      console.error("Failed to toggle all models:", e);
      await fetchProviders();
    }
  };

  const connectedCount = providers.filter((p) => p.configured && p.status === "connected").length;

  const filteredModels = (activeProvider?.models || []).filter((m) => {
    if (!modelSearch) return true;
    const q = modelSearch.toLowerCase();
    return (
      m.name.toLowerCase().includes(q) ||
      m.id.toLowerCase().includes(q) ||
      m.description.toLowerCase().includes(q) ||
      m.tags.some((t) => t.toLowerCase().includes(q))
    );
  });

  return (
    <>
      {standaloneTrigger && (
        <button
          type="button"
          onClick={() => setIsOpen(true)}
          className="flex items-center space-x-1.5 border-2 border-black bg-white px-2.5 py-1 text-xs font-bold font-mono shadow-brutal-sm hover:bg-yellow-100 transition-all active:scale-95"
          title="Manage Provider API Keys and Available Models"
        >
          <Key className="w-3.5 h-3.5 text-black" />
          <span className="hidden sm:inline">KEYS &amp; PROVIDERS</span>
          {connectedCount > 0 ? (
            <span className="ml-1 bg-fra-green text-white font-extrabold px-1.5 py-0.2 text-[9px] border border-black">
              {connectedCount} LIVE
            </span>
          ) : (
            <span className="ml-1 bg-neutral-200 text-neutral-700 px-1 py-0.2 text-[9px] border border-neutral-400">
              SETUP
            </span>
          )}
        </button>
      )}

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 select-none animate-in fade-in duration-150">
          <div
            ref={modalRef}
            className="bg-fra-cream border-3 border-black shadow-brutal-lg max-w-4xl w-full max-h-[90vh] flex flex-col font-mono text-black overflow-hidden"
          >
            {/* Modal Header */}
            <div className="bg-black text-white p-3.5 border-b-2 border-black flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <span className="bg-fra-yellow text-black font-extrabold px-1.5 py-0.5 text-xs">
                  PROVIDERS &amp; KEYS
                </span>
                <h2 className="font-extrabold text-sm tracking-tight">AI PROVIDER &amp; MODEL MANAGER</h2>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="text-neutral-400 hover:text-white font-bold text-sm px-2 py-0.5"
                title="Close (Esc)"
              >
                ✕
              </button>
            </div>

            {/* Main Content: 2-Column */}
            <div className="flex-1 grid grid-cols-1 md:grid-cols-12 overflow-hidden bg-neutral-50 min-h-[460px]">
              {/* Left Column: Providers List */}
              <div className="md:col-span-4 border-b-2 md:border-b-0 md:border-r-2 border-black bg-neutral-100 flex flex-col">
                <div className="p-2.5 bg-neutral-200 border-b border-black text-[11px] font-extrabold tracking-wide uppercase text-neutral-700 flex justify-between items-center">
                  <span>Supported Providers</span>
                  <button
                    onClick={fetchProviders}
                    className="hover:text-black p-0.5 text-neutral-500"
                    title="Refresh Provider Status"
                  >
                    <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
                  </button>
                </div>

                <div className="overflow-y-auto flex-1 p-2 space-y-1.5">
                  {providers.map((p) => {
                    const isSelected = p.id === selectedProviderId;
                    return (
                      <div
                        key={p.id}
                        onClick={() => {
                          setSelectedProviderId(p.id);
                          setInputKey("");
                          setStatusFeedback(null);
                        }}
                        className={`p-2.5 border-2 border-black cursor-pointer transition-all ${
                          isSelected
                            ? "bg-fra-yellow shadow-brutal-sm scale-[1.01]"
                            : "bg-white hover:bg-yellow-50/60 shadow-sm"
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-extrabold text-xs">{p.name}</span>
                          <span
                            className={`text-[8px] font-black px-1 py-0.2 border border-black uppercase ${
                              p.status === "connected"
                                ? "bg-fra-green text-white"
                                : p.status === "offline"
                                ? "bg-neutral-300 text-neutral-600"
                                : "bg-neutral-200 text-neutral-700"
                            }`}
                          >
                            {p.status === "connected" ? "CONNECTED" : p.configured ? "CONFIGURED" : "NO KEY"}
                          </span>
                        </div>

                        <div className="flex items-center justify-between text-[10px] text-neutral-600">
                          <span>{p.company}</span>
                          <span className="font-bold">
                            {p.enabled_models_count}/{p.models_count} active
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="p-2.5 bg-white border-t border-black text-[10px] text-neutral-600 leading-tight">
                  <p>
                    Keys are stored locally in <code className="bg-neutral-200 px-1 py-0.5">.env</code> &amp; synced across runs.
                  </p>
                </div>
              </div>

              {/* Right Column: Selected Provider Configuration & Model Toggles */}
              <div className="md:col-span-8 flex flex-col overflow-hidden bg-white">
                {activeProvider ? (
                  <div className="flex-1 flex flex-col overflow-hidden">
                    {/* Provider Info Banner */}
                    <div className="p-3.5 border-b-2 border-black bg-yellow-50/50">
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center space-x-2">
                            <h3 className="font-extrabold text-base">{activeProvider.name}</h3>
                            <span className="bg-black text-white text-[9px] font-extrabold px-1.5 py-0.5">
                              {activeProvider.badge}
                            </span>
                          </div>
                          <p className="text-xs text-neutral-600 mt-1">{activeProvider.description}</p>
                        </div>
                        {activeProvider.docs_url && (
                          <a
                            href={activeProvider.docs_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center space-x-1 text-[11px] font-bold text-black hover:underline border border-black px-2 py-1 bg-white shadow-brutal-sm"
                          >
                            <span>Get API Key</span>
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </div>
                    </div>

                    {/* API Key Input Section (if not local Ollama) */}
                    {activeProvider.id !== "ollama" && (
                      <div className="p-3.5 border-b-2 border-black bg-neutral-50 space-y-2.5">
                        <div className="flex items-center justify-between">
                          <label className="text-xs font-extrabold tracking-wide uppercase text-neutral-800 flex items-center space-x-1.5">
                            <Key className="w-3.5 h-3.5" />
                            <span>API Key ({activeProvider.env_var})</span>
                          </label>
                          {activeProvider.key_hint && (
                            <span className="text-[11px] font-bold text-neutral-600">
                              Configured: <code className="bg-neutral-200 px-1.5 py-0.5 border border-neutral-300">{activeProvider.key_hint}</code>
                            </span>
                          )}
                        </div>

                        <div className="flex items-center space-x-2">
                          <div className="relative flex-1">
                            <input
                              type={showKey ? "text" : "password"}
                              placeholder={
                                activeProvider.key_hint
                                  ? "Enter new API key to replace existing..."
                                  : `Paste your ${activeProvider.name} API Key here...`
                              }
                              value={inputKey}
                              onChange={(e) => setInputKey(e.target.value)}
                              className="w-full border-2 border-black px-3 py-1.5 text-xs font-mono focus:bg-white focus:outline-none placeholder-neutral-400 shadow-brutal-sm"
                            />
                            <button
                              type="button"
                              onClick={() => setShowKey(!showKey)}
                              className="absolute right-2.5 top-2 text-neutral-500 hover:text-black"
                              title={showKey ? "Hide key" : "Show key"}
                            >
                              {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                            </button>
                          </div>

                          <button
                            type="button"
                            onClick={handleSaveKey}
                            disabled={!inputKey.trim() || savingKey}
                            className={`border-2 border-black px-3 py-1.5 text-xs font-bold shadow-brutal-sm transition-all ${
                              inputKey.trim() && !savingKey
                                ? "bg-fra-yellow text-black hover:bg-yellow-400 cursor-pointer"
                                : "bg-neutral-200 text-neutral-400 cursor-not-allowed"
                            }`}
                          >
                            {savingKey ? (
                              <span className="flex items-center space-x-1">
                                <RefreshCw className="w-3 h-3 animate-spin" />
                                <span>Verifying...</span>
                              </span>
                            ) : (
                              <span>Save &amp; Discover</span>
                            )}
                          </button>

                          {activeProvider.configured && (
                            <button
                              type="button"
                              onClick={handleDeleteKey}
                              className="border-2 border-black bg-white text-red-600 hover:bg-red-50 p-1.5 shadow-brutal-sm"
                              title="Delete Key"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>

                        {statusFeedback && (
                          <div
                            className={`p-2 border border-black text-xs font-bold flex items-center space-x-2 ${
                              statusFeedback.type === "success"
                                ? "bg-green-100 text-green-900 border-green-800"
                                : "bg-red-100 text-red-900 border-red-800"
                            }`}
                          >
                            {statusFeedback.type === "success" ? (
                              <CheckCircle className="w-4 h-4 flex-shrink-0 text-green-700" />
                            ) : (
                              <AlertCircle className="w-4 h-4 flex-shrink-0 text-red-700" />
                            )}
                            <span>{statusFeedback.message}</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Models Discovery & Toggle List */}
                    <div className="p-3 border-b border-black bg-white flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center space-x-2">
                        <span className="font-extrabold text-xs tracking-wide uppercase">
                          Available Models ({activeProvider.enabled_models_count}/{activeProvider.models_count} active)
                        </span>
                      </div>

                      <div className="flex items-center space-x-2">
                        <input
                          type="text"
                          placeholder="Filter models..."
                          value={modelSearch}
                          onChange={(e) => setModelSearch(e.target.value)}
                          className="border border-black px-2 py-0.5 text-xs font-mono w-32 focus:w-44 transition-all focus:outline-none"
                        />
                        <button
                          type="button"
                          onClick={() => handleToggleAll(true)}
                          className="border border-black bg-white hover:bg-neutral-100 px-2 py-0.5 text-[10px] font-bold shadow-brutal-xs"
                        >
                          Enable All
                        </button>
                        <button
                          type="button"
                          onClick={() => handleToggleAll(false)}
                          className="border border-black bg-white hover:bg-neutral-100 px-2 py-0.5 text-[10px] font-bold shadow-brutal-xs"
                        >
                          Disable All
                        </button>
                      </div>
                    </div>

                    <div className="flex-1 overflow-y-auto p-3 space-y-2 bg-neutral-50">
                      {filteredModels.length === 0 ? (
                        <div className="py-10 text-center text-xs text-neutral-500 italic bg-white border border-neutral-300 p-4">
                          {activeProvider.models.length === 0
                            ? "No models discovered. Enter a valid API key above and click 'Save & Discover'."
                            : `No models matching "${modelSearch}".`}
                        </div>
                      ) : (
                        filteredModels.map((m) => {
                          const isEnabled = m.enabled !== false;
                          return (
                            <div
                              key={m.id}
                              className={`border-2 border-black p-2.5 transition-all ${
                                isEnabled
                                  ? "bg-white shadow-brutal-sm"
                                  : "bg-neutral-100 border-neutral-400 opacity-60 shadow-none"
                              }`}
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div className="flex-1">
                                  <div className="flex items-center space-x-2 mb-1">
                                    <span className="font-extrabold text-xs text-black">{m.name}</span>
                                    <span className="text-[9px] bg-black text-white px-1 font-bold">
                                      {m.context_window}
                                    </span>
                                    <span className="text-[9px] bg-neutral-200 px-1 border border-neutral-300 font-mono text-neutral-700">
                                      {m.id}
                                    </span>
                                  </div>
                                  <p className="text-[11px] text-neutral-600 leading-snug font-mono mb-1.5">
                                    {m.description}
                                  </p>
                                  <div className="flex flex-wrap gap-1">
                                    {m.tags.map((t) => (
                                      <span
                                        key={t}
                                        className="text-[8px] font-black uppercase bg-neutral-100 border border-neutral-400 px-1 py-0.2"
                                      >
                                        {t}
                                      </span>
                                    ))}
                                  </div>
                                </div>

                                {/* Toggle Switch */}
                                <button
                                  type="button"
                                  onClick={() => handleToggleModel(m.id, isEnabled)}
                                  className={`flex items-center space-x-1.5 border-2 border-black px-2.5 py-1 text-[11px] font-extrabold transition-all shadow-brutal-xs ${
                                    isEnabled
                                      ? "bg-fra-green text-white hover:bg-emerald-700"
                                      : "bg-white text-neutral-600 hover:bg-neutral-100"
                                  }`}
                                >
                                  {isEnabled ? (
                                    <>
                                      <Check className="w-3.5 h-3.5" />
                                      <span>ACTIVE</span>
                                    </>
                                  ) : (
                                    <>
                                      <X className="w-3.5 h-3.5" />
                                      <span>DISABLED</span>
                                    </>
                                  )}
                                </button>
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="p-12 text-center text-neutral-500 text-xs">
                    Select a provider from the left panel.
                  </div>
                )}
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-3 bg-white border-t-2 border-black flex items-center justify-between text-xs">
              <span className="text-[11px] text-neutral-600">
                Enabled models appear automatically in the <strong>Agentic Model Selector</strong>.
              </span>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="border-2 border-black bg-black text-white font-bold px-4 py-1.5 shadow-brutal-sm hover:bg-neutral-800 cursor-pointer"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
