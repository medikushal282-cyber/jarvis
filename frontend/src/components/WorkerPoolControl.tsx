'use client';

import React, { useState, useEffect, useRef } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_JARVIS_API || 'http://localhost:8006';

export default function WorkerPoolControl() {
  const [open, setOpen] = useState(false);
  const [workers, setWorkers] = useState<any[]>([]);
  const [showAddForm, setShowAddForm] = useState(false);
  
  // Add Form State
  const [provider, setProvider] = useState('groq');
  const [model, setModel] = useState('llama-3.1-8b-instant');
  const [credentialType, setCredentialType] = useState<'api_key' | 'env_var'>('api_key');
  const [credentialValue, setCredentialValue] = useState('');
  const [priority, setPriority] = useState(1);
  const [owner, setOwner] = useState('');
  
  const [testStatus, setTestStatus] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  
  // Detail View State
  const [selectedWorker, setSelectedWorker] = useState<any | null>(null);

  const panelRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  const fetchWorkers = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/workers`);
      if (res.ok) {
        setWorkers(await res.json());
      }
    } catch (e) {
      console.warn("Could not fetch workers", e);
    }
  };

  useEffect(() => {
    fetchWorkers();
  }, []);

  useEffect(() => {
    if (open) {
      fetchWorkers();
      const interval = setInterval(fetchWorkers, 3000);
      return () => clearInterval(interval);
    }
  }, [open]);

  // Click outside and ESC handling
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (selectedWorker) setSelectedWorker(null);
        else if (open) setOpen(false);
      }
    };
    const handleClickOutside = (e: MouseEvent) => {
      if (selectedWorker && modalRef.current && !modalRef.current.contains(e.target as Node)) {
        setSelectedWorker(null);
      } else if (open && !selectedWorker && panelRef.current && !panelRef.current.contains(e.target as Node)) {
        // We also need to check if they clicked the toggle button.
        // It's handled by stopping propagation or just not doing anything if it's inside panelRef (the wrapper).
        setOpen(false);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [open, selectedWorker]);

  const handleTestConnection = async (isNew: boolean, w: any = null) => {
    const body = isNew ? {
      provider, 
      model, 
      [credentialType === 'api_key' ? 'api_key' : 'credential_env']: credentialValue
    } : {
      provider: w.provider,
      model: w.model,
      worker_id: w.worker_id // Backend test endpoint might not support worker_id directly, but we can pass it if we update API or just skip testing existing without raw key
    };
    
    // Testing an existing worker from UI is hard if we don't have the API key! 
    // Usually test expects api_key. We will only support testing from the Add Form.
    if (!isNew) {
      alert("Test connection for existing workers requires backend support for testing by ID.");
      return;
    }

    if (!credentialValue) return;
    
    setTesting(true);
    setTestStatus(null);
    try {
      const res = await fetch(`${API_BASE}/api/workers/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.success) {
        setTestStatus('● Connection successful');
      } else {
        setTestStatus('× Connection failed: ' + (data.message || ''));
      }
    } catch (e: any) {
      setTestStatus('× Connection failed: ' + e.message);
    } finally {
      setTesting(false);
    }
  };

  const handleAddWorker = async () => {
    if (!credentialValue) return;
    try {
      await fetch(`${API_BASE}/api/workers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          provider, 
          model, 
          [credentialType === 'api_key' ? 'api_key' : 'credential_env']: credentialValue, 
          priority: Number(priority) || 1,
          owner: owner.trim()
        }),
      });
      setShowAddForm(false);
      setCredentialValue('');
      setTestStatus(null);
      fetchWorkers();
    } catch (e) {
      console.error(e);
    }
  };

  const handleRemoveWorker = async (id: string) => {
    try {
      await fetch(`${API_BASE}/api/workers/${id}`, { method: 'DELETE' });
      if (selectedWorker?.worker_id === id) setSelectedWorker(null);
      fetchWorkers();
    } catch (e) {
      console.error(e);
    }
  };

  const handleToggleEnable = async (id: string, currentStatus: boolean) => {
    try {
      const res = await fetch(`${API_BASE}/api/workers/${id}`, { 
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !currentStatus })
      });
      const updated = await res.json();
      if (selectedWorker?.worker_id === id) {
        setSelectedWorker((prev: any) => ({ ...prev, enabled: !currentStatus, status: updated.status }));
      }
      fetchWorkers();
    } catch (e) {
      console.error(e);
    }
  };

  const handleResetCooldown = async (id: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/workers/${id}`, { 
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reset_cooldown: true })
      });
      const updated = await res.json();
      if (selectedWorker?.worker_id === id) {
        setSelectedWorker((prev: any) => ({ ...prev, cooldown_until: 0, last_error: null, status: updated.status }));
      }
      fetchWorkers();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="relative" ref={panelRef}>
      <button 
        onClick={() => setOpen(!open)}
        className="flex items-center space-x-2 border-2 border-fra-black bg-fra-cream-card px-2.5 py-1 text-[11px] font-bold shadow-brutal hover:bg-fra-yellow transition-colors"
      >
        <span className="text-xs font-mono font-black">[WORKERS {workers.length} ●]</span>
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 border-2 border-fra-black bg-fra-cream-card shadow-brutal z-50 p-2 font-mono flex flex-col max-h-[85vh] overflow-y-auto">
          <div className="flex justify-between items-center mb-2 border-b-2 border-fra-black pb-1">
            <span className="font-bold text-xs uppercase tracking-tight">WORKER POOL</span>
            <button onClick={() => setOpen(false)} className="text-base leading-none font-bold hover:text-red-500">×</button>
          </div>

          <div className="flex flex-col space-y-2 mb-3">
            {workers.map(w => (
              <div 
                key={w.worker_id} 
                className="border-2 border-fra-black p-2 bg-white relative shadow-sm cursor-pointer hover:bg-neutral-50 transition-colors"
                onClick={() => setSelectedWorker(w)}
              >
                <div className="flex items-center space-x-2 mb-1">
                  <span className={`w-2 h-2 rounded-full border border-black ${w.status === 'HEALTHY' || w.status === 'READY' ? 'bg-green-500' : w.status === 'COOLDOWN' ? 'bg-yellow-500' : 'bg-red-500'}`}></span>
                  <span className="font-bold text-[11px] uppercase truncate flex-1">{w.owner ? `${w.owner}'s Node` : w.worker_id.substring(0,12)}</span>
                  <span className="text-[9px] bg-neutral-100 border border-neutral-300 px-1 font-mono">P{w.priority ?? 1}</span>
                </div>
                <div className="text-[10px] font-mono font-bold text-neutral-800">{w.provider.toUpperCase()} / {w.model}</div>
                <div className="flex justify-between text-[9px] text-gray-600 mt-1 uppercase font-bold">
                  <span>{w.api_key_hint ? `KEY: ${w.api_key_hint}` : 'ENV VAR'}</span>
                  <span className={w.status === 'COOLDOWN' ? 'text-amber-700' : w.status === 'HEALTHY' ? 'text-green-700' : w.status === 'DISABLED' ? 'text-neutral-500' : 'text-red-700'}>
                    {w.status}{w.cooldown_remaining ? ` — ${w.cooldown_remaining}S` : ''}
                  </span>
                </div>
              </div>
            ))}
            {workers.length === 0 && (
              <div className="text-[10px] text-gray-500 p-2 text-center font-bold border border-dashed border-neutral-400">
                No workers configured. Using default environment configuration.
              </div>
            )}
          </div>

          {!showAddForm ? (
            <button 
              onClick={(e) => { e.stopPropagation(); setShowAddForm(true); }}
              className="w-full bg-fra-yellow border-2 border-fra-black font-bold text-[11px] py-1.5 hover:bg-yellow-400 uppercase shadow-brutal-sm"
            >
              + Add Worker
            </button>
          ) : (
            <div className="border-2 border-fra-black bg-white p-2.5 flex flex-col space-y-2 text-[10px]" onClick={e => e.stopPropagation()}>
              <div className="flex flex-col">
                <label className="font-bold uppercase text-[9px] text-neutral-600">Provider</label>
                <select 
                  value={provider} 
                  onChange={e => {
                    const p = e.target.value;
                    setProvider(p);
                    if (p === 'groq') setModel('llama-3.1-8b-instant');
                    else if (p === 'openai') setModel('gpt-4o-mini');
                    else if (p === 'gemini') setModel('gemini-1.5-flash');
                    else if (p === 'anthropic') setModel('claude-3-5-haiku-20241022');
                  }} 
                  className="border-2 border-fra-black p-1 text-[10px] outline-none font-bold bg-fra-cream"
                >
                  <option value="groq">Groq</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </div>

              <div className="flex flex-col">
                <label className="font-bold uppercase text-[9px] text-neutral-600">Model</label>
                <input 
                  type="text" 
                  value={model} 
                  onChange={e => setModel(e.target.value)} 
                  className="border-2 border-fra-black p-1 text-[10px] outline-none font-mono" 
                />
              </div>

              <div className="flex flex-col">
                <label className="font-bold uppercase text-[9px] text-neutral-600">Owner (Optional)</label>
                <input 
                  type="text" 
                  value={owner} 
                  onChange={e => setOwner(e.target.value)} 
                  placeholder="e.g. member1"
                  className="border-2 border-fra-black p-1 text-[10px] outline-none font-mono" 
                />
              </div>

              <div className="flex flex-col">
                <label className="font-bold uppercase text-[9px] text-neutral-600">Priority (Higher = preferred)</label>
                <input 
                  type="number" 
                  value={priority} 
                  onChange={e => setPriority(parseInt(e.target.value) || 1)} 
                  className="border-2 border-fra-black p-1 text-[10px] outline-none font-mono" 
                />
              </div>

              <div className="flex flex-col mt-2">
                <div className="flex space-x-2 mb-1">
                  <label className="font-bold uppercase text-[9px] flex items-center space-x-1 cursor-pointer">
                    <input type="radio" checked={credentialType === 'api_key'} onChange={() => setCredentialType('api_key')} className="accent-black" />
                    <span>Raw API Key</span>
                  </label>
                  <label className="font-bold uppercase text-[9px] flex items-center space-x-1 cursor-pointer">
                    <input type="radio" checked={credentialType === 'env_var'} onChange={() => setCredentialType('env_var')} className="accent-black" />
                    <span>Env Var (e.g. GROQ_API_KEY)</span>
                  </label>
                </div>
                <input 
                  type={credentialType === 'api_key' ? "password" : "text"}
                  value={credentialValue} 
                  onChange={e => setCredentialValue(e.target.value)} 
                  placeholder={credentialType === 'api_key' ? "•••••••••••••••••" : "GROQ_API_KEY_MEMBER1"} 
                  className="border-2 border-fra-black p-1 text-[10px] outline-none font-mono" 
                />
              </div>

              {testStatus && (
                <div className={`text-[10px] font-bold p-1 border ${testStatus.includes('successful') ? 'bg-green-100 text-green-800 border-green-400' : 'bg-red-100 text-red-800 border-red-400'}`}>
                  {testStatus}
                </div>
              )}

              <div className="flex space-x-1.5 pt-1">
                <button 
                  onClick={() => handleTestConnection(true)} 
                  disabled={testing || !credentialValue}
                  className="flex-1 border-2 border-fra-black bg-neutral-200 text-black font-bold py-1 text-[9px] hover:bg-neutral-300 disabled:opacity-50"
                >
                  {testing ? "Testing..." : "Test Connection"}
                </button>
                <button 
                  onClick={handleAddWorker} 
                  disabled={!credentialValue}
                  className="flex-1 border-2 border-fra-black bg-fra-yellow text-black font-bold py-1 text-[9px] hover:bg-yellow-400 disabled:opacity-50"
                >
                  Save Worker
                </button>
              </div>

              <button 
                onClick={(e) => { e.stopPropagation(); setShowAddForm(false); setTestStatus(null); }} 
                className="w-full text-center text-[9px] text-neutral-500 hover:text-black mt-1"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}

      {/* Detail Modal Overlay */}
      {selectedWorker && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setSelectedWorker(null)}>
          <div 
            ref={modalRef}
            className="w-96 border-4 border-fra-black bg-fra-cream-card shadow-brutal p-4 font-mono"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex justify-between items-start mb-4 border-b-2 border-fra-black pb-2">
              <div>
                <h2 className="font-black text-lg uppercase tracking-tight">Worker Details</h2>
                <div className="text-[10px] text-neutral-600 font-bold">{selectedWorker.worker_id}</div>
              </div>
              <button onClick={() => setSelectedWorker(null)} className="text-xl leading-none font-bold hover:text-red-500 p-1">×</button>
            </div>

            <div className="space-y-3 text-xs mb-6">
              <div className="grid grid-cols-3 gap-2 border-b border-neutral-300 pb-2">
                <div className="font-bold uppercase text-neutral-500">Provider</div>
                <div className="col-span-2 font-bold">{selectedWorker.provider.toUpperCase()}</div>
              </div>
              
              <div className="grid grid-cols-3 gap-2 border-b border-neutral-300 pb-2">
                <div className="font-bold uppercase text-neutral-500">Model</div>
                <div className="col-span-2 font-mono font-bold break-all">{selectedWorker.model}</div>
              </div>
              
              <div className="grid grid-cols-3 gap-2 border-b border-neutral-300 pb-2">
                <div className="font-bold uppercase text-neutral-500">Owner</div>
                <div className="col-span-2 font-bold">{selectedWorker.owner || '—'}</div>
              </div>
              
              <div className="grid grid-cols-3 gap-2 border-b border-neutral-300 pb-2">
                <div className="font-bold uppercase text-neutral-500">Priority</div>
                <div className="col-span-2 font-bold">P{selectedWorker.priority}</div>
              </div>
              
              <div className="grid grid-cols-3 gap-2 border-b border-neutral-300 pb-2">
                <div className="font-bold uppercase text-neutral-500">Credential</div>
                <div className="col-span-2 font-mono font-bold">
                  {selectedWorker.api_key_hint ? `[API KEY] ${selectedWorker.api_key_hint}` : `[ENV VAR] Active`}
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 border-b border-neutral-300 pb-2 items-center">
                <div className="font-bold uppercase text-neutral-500">Status</div>
                <div className="col-span-2 flex items-center space-x-2">
                  <span className={`w-3 h-3 rounded-full border border-black ${selectedWorker.status === 'HEALTHY' || selectedWorker.status === 'READY' ? 'bg-green-500' : selectedWorker.status === 'COOLDOWN' ? 'bg-yellow-500' : selectedWorker.status === 'DISABLED' ? 'bg-neutral-400' : 'bg-red-500'}`}></span>
                  <span className="font-black tracking-wider uppercase">{selectedWorker.status}</span>
                </div>
              </div>

              {selectedWorker.status === 'COOLDOWN' && (
                <div className="bg-yellow-100 border-2 border-yellow-500 p-2 text-yellow-900 text-[10px] font-bold flex justify-between items-center">
                  <span>Rate Limit Cooldown ({selectedWorker.cooldown_remaining}s remaining)</span>
                  <button onClick={() => handleResetCooldown(selectedWorker.worker_id)} className="bg-white px-2 py-1 border border-black hover:bg-neutral-100 text-black">RESET</button>
                </div>
              )}
              
              {selectedWorker.last_error && selectedWorker.status !== 'COOLDOWN' && (
                <div className="bg-red-100 border-2 border-red-500 p-2 text-red-900 text-[10px] font-bold flex flex-col space-y-1">
                  <div className="flex justify-between">
                    <span className="uppercase">Last Error</span>
                    <button onClick={() => handleResetCooldown(selectedWorker.worker_id)} className="bg-white px-2 py-0.5 border border-black hover:bg-neutral-100 text-black text-[9px]">CLEAR</button>
                  </div>
                  <span className="font-mono break-all">{selectedWorker.last_error}</span>
                </div>
              )}

              <div className="text-[10px] text-neutral-500 pt-2 font-bold uppercase text-center">
                Last Used: {selectedWorker.last_used_at ? new Date(selectedWorker.last_used_at * 1000).toLocaleString() : 'Never'}
              </div>
            </div>

            <div className="flex space-x-2">
              <button 
                onClick={() => handleToggleEnable(selectedWorker.worker_id, selectedWorker.enabled)}
                className="flex-1 border-2 border-fra-black bg-neutral-200 hover:bg-neutral-300 font-black text-xs py-2 uppercase shadow-brutal-sm"
              >
                {selectedWorker.enabled ? 'Disable' : 'Enable'}
              </button>
              <button 
                onClick={() => {
                  if (confirm("Are you sure you want to delete this worker?")) {
                    handleRemoveWorker(selectedWorker.worker_id);
                  }
                }}
                className="flex-1 border-2 border-fra-black bg-red-500 hover:bg-red-600 text-white font-black text-xs py-2 uppercase shadow-brutal-sm"
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
