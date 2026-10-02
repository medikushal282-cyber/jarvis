"use client";

import React, { useState, useEffect, useRef } from "react";
import { Wrench } from "lucide-react";

interface ToolMetadata {
  name: string;
  description: string;
  category: string;
  risk: string;
  permissions: string[];
  parameters: any;
  enabled: boolean;
  explicitly_disabled: boolean;
}

export default function ToolExplorer() {
  const [isOpen, setIsOpen] = useState(false);
  const [tools, setTools] = useState<ToolMetadata[]>([]);
  const [categories, setCategories] = useState<{name: string, enabled: boolean}[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTool, setSelectedTool] = useState<ToolMetadata | null>(null);
  const [search, setSearch] = useState("");
  
  const dropdownRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current && 
        !dropdownRef.current.contains(event.target as Node) &&
        modalRef.current &&
        !modalRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    if (isOpen || selectedTool) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, selectedTool]);

  const fetchTools = async () => {
    setLoading(true);
    try {
      const [toolsRes, catsRes] = await Promise.all([
        fetch("http://localhost:8006/api/tools"),
        fetch("http://localhost:8006/api/tools/categories")
      ]);
      
      if (toolsRes.ok) {
        const data = await toolsRes.json();
        setTools(data.tools || []);
      }
      if (catsRes.ok) {
        const data = await catsRes.json();
        setCategories(data.categories || []);
      }
    } catch (err) {
      console.error("Failed to fetch tools", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchTools();
    }
  }, [isOpen]);

  const handleToggleTool = async (e: React.MouseEvent, toolName: string, currentlyEnabled: boolean) => {
    e.stopPropagation();
    try {
      await fetch(`http://localhost:8006/api/tools/${toolName}/toggle?enabled=${!currentlyEnabled}`, {
        method: "POST",
      });
      fetchTools();
      if (selectedTool && selectedTool.name === toolName) {
        setSelectedTool({...selectedTool, enabled: !currentlyEnabled});
      }
    } catch (err) {
      console.error("Failed to toggle tool", err);
    }
  };

  const handleToggleCategory = async (e: React.MouseEvent, catName: string, currentlyEnabled: boolean) => {
    e.stopPropagation();
    try {
      await fetch(`http://localhost:8006/api/tools/categories/${catName}/toggle?enabled=${!currentlyEnabled}`, {
        method: "POST",
      });
      fetchTools();
    } catch (err) {
      console.error("Failed to toggle category", err);
    }
  };

  const filteredTools = tools.filter(t => 
    t.name.toLowerCase().includes(search.toLowerCase()) || 
    t.description.toLowerCase().includes(search.toLowerCase())
  );

  const enabledCount = tools.filter(t => t.enabled).length;

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center space-x-1 border-2 border-black px-2 py-0.5 text-[10px] font-black uppercase shadow-brutal-sm transition-all ${
          isOpen ? 'bg-black text-white' : 'bg-fra-cream text-black hover:bg-neutral-200'
        }`}
        title="Tool Explorer"
      >
        <Wrench size={12} className="mr-1" />
        <span>TOOLS ({enabledCount}/{tools.length})</span>
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-80 origin-top-right border-4 border-fra-black bg-white shadow-brutal z-50 flex flex-col max-h-[80vh]">
          <div className="flex justify-between items-center border-b-4 border-fra-black p-2 bg-fra-cream">
            <h3 className="font-black text-sm uppercase tracking-tighter flex items-center">
              <Wrench size={14} className="mr-2" />
              Tool Explorer
            </h3>
            <button onClick={() => setIsOpen(false)} className="text-sm font-black hover:text-red-500">A-</button>
          </div>
          
          <div className="p-2 border-b-2 border-fra-black">
            <input 
              type="text" 
              placeholder="Search tools..." 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full border-2 border-fra-black p-1 text-xs font-mono outline-none focus:bg-yellow-50"
            />
          </div>
          
          <div className="flex-1 overflow-y-auto p-2 font-mono text-xs space-y-4">
            {loading ? (
              <div className="text-center p-4">Loading tools...</div>
            ) : (
              categories.map(cat => {
                const catTools = filteredTools.filter(t => t.category === cat.name);
                if (catTools.length === 0) return null;
                
                return (
                  <div key={cat.name} className="border-2 border-neutral-300">
                    <div className="flex justify-between items-center bg-neutral-100 p-1 border-b-2 border-neutral-300">
                      <span className="font-bold uppercase tracking-wider">{cat.name}</span>
                      <button 
                        onClick={(e) => handleToggleCategory(e, cat.name, cat.enabled)}
                        className={`px-1.5 py-0.5 text-[9px] font-bold border border-black ${cat.enabled ? 'bg-fra-green text-black' : 'bg-red-500 text-white'}`}
                      >
                        {cat.enabled ? 'ON' : 'OFF'}
                      </button>
                    </div>
                    <div>
                      {catTools.map(t => (
                        <div 
                          key={t.name} 
                          onClick={() => setSelectedTool(t)}
                          className={`flex items-center justify-between p-1.5 border-b border-dashed border-neutral-200 cursor-pointer hover:bg-yellow-50 ${t.enabled ? '' : 'opacity-60 grayscale'}`}
                        >
                          <div className="flex flex-col overflow-hidden">
                            <span className="font-bold truncate">{t.name}</span>
                            <span className="text-[9px] text-neutral-500 truncate">{t.description}</span>
                          </div>
                          <button
                            onClick={(e) => handleToggleTool(e, t.name, t.enabled)}
                            className={`ml-2 flex-shrink-0 w-8 h-4 border border-black rounded-full relative transition-colors ${t.enabled ? 'bg-fra-green' : 'bg-neutral-400'}`}
                          >
                            <span className={`absolute top-0 w-3.5 h-3.5 bg-white border border-black rounded-full transition-all ${t.enabled ? 'right-0' : 'left-0'}`}></span>
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Tool Detail Modal */}
      {selectedTool && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setSelectedTool(null)}>
          <div 
            ref={modalRef}
            className="w-[450px] max-h-[85vh] flex flex-col border-4 border-fra-black bg-fra-cream-card shadow-brutal p-4 font-mono overflow-y-auto"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex justify-between items-start mb-4 border-b-2 border-fra-black pb-2">
              <div>
                <h2 className="font-black text-lg uppercase tracking-tight">{selectedTool.name}</h2>
                <div className="text-[10px] text-neutral-600 font-bold uppercase">{selectedTool.category} | Risk: {selectedTool.risk}</div>
              </div>
              <button onClick={() => setSelectedTool(null)} className="text-xl leading-none font-bold hover:text-red-500 p-1">A-</button>
            </div>
            
            <p className="text-sm mb-4 font-sans">{selectedTool.description}</p>
            
            <div className="space-y-4 text-xs mb-6">
              <div>
                <h4 className="font-bold border-b border-fra-black mb-1 uppercase">Required Permissions</h4>
                {selectedTool.permissions.length > 0 ? (
                  <ul className="list-disc pl-4 space-y-1">
                    {selectedTool.permissions.map(p => <li key={p}>{p}</li>)}
                  </ul>
                ) : (
                  <span className="text-neutral-500">None required</span>
                )}
              </div>
              
              <div>
                <h4 className="font-bold border-b border-fra-black mb-1 uppercase">Parameters Schema</h4>
                <div className="bg-neutral-800 text-green-400 p-2 overflow-x-auto text-[10px]">
                  <pre>{JSON.stringify(selectedTool.parameters, null, 2)}</pre>
                </div>
              </div>
            </div>

            <div className="mt-auto">
              <button 
                onClick={(e) => { e.stopPropagation(); handleToggleTool(e, selectedTool.name, selectedTool.enabled); }}
                className={`w-full border-2 border-fra-black font-black text-xs py-2 uppercase shadow-brutal-sm transition-colors ${
                  selectedTool.enabled ? 'bg-red-500 text-white hover:bg-red-600' : 'bg-fra-green text-black hover:bg-green-500'
                }`}
              >
                {selectedTool.enabled ? 'Disable Tool' : 'Enable Tool'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
