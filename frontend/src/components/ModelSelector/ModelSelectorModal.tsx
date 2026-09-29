"use client";

import React, { useState, useEffect } from 'react';
import { API_BASE } from "@/lib/runtime/client";

export interface ModelItem {
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
}

interface ModelSelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedModel: string;
  selectedProvider: string;
  onSelect: (modelId: string, provider: string) => void;
}

export const ModelSelectorModal: React.FC<ModelSelectorModalProps> = ({
  isOpen,
  onClose,
  selectedModel,
  selectedProvider,
  onSelect
}) => {
  const [models, setModels] = useState<ModelItem[]>([]);
  const [activeTab, setActiveTab] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!isOpen) return;

    const fetchModels = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/models`);
        if (res.ok) {
          const data = await res.json();
          setModels(data.models || []);
        }
      } catch (e) {
        console.error("Failed to load models list", e);
      } finally {
        setLoading(false);
      }
    };
    fetchModels();
  }, [isOpen]);

  if (!isOpen) return null;

  const filteredModels = models.filter(m => {
    const matchesTab =
      activeTab === 'all' ||
      m.provider.toLowerCase() === activeTab.toLowerCase();

    const matchesSearch =
      m.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      m.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      m.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      m.tags.some(t => t.toLowerCase().includes(searchQuery.toLowerCase()));

    return matchesTab && matchesSearch;
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 select-none">
      <div className="bg-fra-cream border-3 border-black shadow-brutal-lg max-w-2xl w-full max-h-[85vh] flex flex-col font-mono text-black overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="bg-black text-white p-3.5 border-b-2 border-black flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="bg-fra-yellow text-black font-extrabold px-1.5 py-0.5 text-xs">MODELS</span>
            <h2 className="font-extrabold text-sm tracking-tight">AGENTIC MODEL SELECTOR</h2>
          </div>
          <button
            onClick={onClose}
            className="text-neutral-400 hover:text-white font-bold text-sm px-1.5"
          >
            ✕
          </button>
        </div>

        {/* Filters & Search Toolbar */}
        <div className="p-3 border-b-2 border-black bg-white space-y-2.5">
          {/* Search Input */}
          <div className="relative">
            <input
              type="text"
              placeholder="Search models (e.g. qwen coder, gpt-4o, llama 3.3, oss)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full border-2 border-black px-3 py-1.5 text-xs font-mono focus:bg-yellow-50/50 focus:outline-none placeholder-neutral-500 shadow-brutal-sm"
              autoFocus
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1.5 text-xs text-neutral-400 hover:text-black font-bold"
              >
                ✕
              </button>
            )}
          </div>

          {/* Provider Tabs */}
          <div className="flex flex-wrap gap-1.5 text-[11px] font-bold">
            {[
              { id: 'all', label: 'All Providers' },
              { id: 'groq', label: 'Groq Cloud' },
              { id: 'ollama', label: 'Ollama (Local OSS)' },
              { id: 'openai', label: 'OpenAI' },
              { id: 'anthropic', label: 'Anthropic' },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-2.5 py-1 border-2 border-black transition-all shadow-brutal-sm ${
                  activeTab === tab.id
                    ? 'bg-black text-white'
                    : 'bg-fra-cream-card text-black hover:bg-neutral-100'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Model Cards List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2.5 bg-neutral-50">
          {loading ? (
            <div className="py-12 flex flex-col items-center justify-center space-y-2 text-neutral-500 text-xs">
              <div className="w-5 h-5 border-2 border-black border-t-transparent rounded-full animate-spin"></div>
              <span>Querying live model providers...</span>
            </div>
          ) : filteredModels.length === 0 ? (
            <div className="py-12 text-center text-neutral-500 text-xs italic bg-white border-2 border-neutral-300 p-6">
              No models matching &quot;{searchQuery}&quot; found in {activeTab.toUpperCase()}.
            </div>
          ) : (
            filteredModels.map((m) => {
              const isSelected = selectedModel === m.id;
              return (
                <div
                  key={m.id}
                  onClick={() => onSelect(m.id, m.provider)}
                  className={`border-2 border-black p-3 cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-fra-yellow shadow-brutal'
                      : 'bg-white hover:bg-yellow-50/50 shadow-brutal-sm'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <div className="flex items-center space-x-2">
                      <span className="font-extrabold text-sm">{m.name}</span>
                      <span className="text-[10px] bg-neutral-200 px-1 border border-neutral-400 font-bold">
                        {m.provider_name}
                      </span>
                      <span className="text-[9px] bg-black text-white px-1 border border-black font-bold">
                        {m.context_window}
                      </span>
                    </div>

                    <div className="flex items-center space-x-2">
                      <span
                        className={`text-[9px] font-bold px-1.5 py-0.5 border border-black ${
                          m.available
                            ? 'bg-fra-green text-white'
                            : 'bg-neutral-200 text-neutral-600'
                        }`}
                      >
                        {m.status_text || (m.available ? 'Ready' : 'Unavailable')}
                      </span>
                      {isSelected && (
                        <span className="bg-black text-white font-black text-xs px-1.5 py-0.5 border border-black">
                          ACTIVE
                        </span>
                      )}
                    </div>
                  </div>

                  <p className="text-[11px] text-neutral-700 leading-relaxed mb-2 font-mono">
                    {m.description}
                  </p>

                  <div className="flex flex-wrap gap-1">
                    {m.tags.map((tag) => (
                      <span
                        key={tag}
                        className="text-[8px] font-black uppercase bg-white border border-black px-1.5 py-0.2"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="p-3 bg-white border-t-2 border-black flex items-center justify-between text-xs">
          <span className="text-[11px] text-neutral-600">
            Active: <strong className="text-black font-mono">{selectedModel}</strong> ({selectedProvider})
          </span>
          <button
            onClick={onClose}
            className="border-2 border-black bg-black text-white font-bold px-4 py-1.5 shadow-brutal-sm hover:bg-neutral-800"
          >
            Confirm Selection
          </button>
        </div>
      </div>
    </div>
  );
};

export default ModelSelectorModal;
