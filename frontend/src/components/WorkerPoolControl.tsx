import React, { useState, useEffect } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_JARVIS_API || 'http://localhost:8006';

export default function WorkerPoolControl() {
  const [open, setOpen] = useState(false);
  const [workers, setWorkers] = useState<any[]>([]);
  const [showAddForm, setShowAddForm] = useState(false);

  const [provider, setProvider] = useState('groq');
  const [model, setModel] = useState('llama-3.1-8b-instant');
  const [apiKey, setApiKey] = useState('');
  const [priority, setPriority] = useState(1);
  const [testStatus, setTestStatus] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

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

  const handleTestConnection = async () => {
    if (!apiKey) return;
    setTesting(true);
    setTestStatus(null);
    try {
      const res = await fetch(`${API_BASE}/api/workers/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, model, api_key: apiKey }),
      });
      const data = await res.json();
      if (data.success) {
        setTestStatus('● Connection successful');
      } else {
        setTestStatus('× Connection failed');
      }
    } catch (e) {
      setTestStatus('× Connection failed');
    } finally {
      setTesting(false);
    }
  };

  const handleAddWorker = async () => {
    if (!apiKey) return;
    try {
      await fetch(`${API_BASE}/api/workers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, model, api_key: apiKey, priority: Number(priority) || 1 }),
      });
      setShowAddForm(false);
      setApiKey('');
      setTestStatus(null);
      fetchWorkers();
    } catch (e) {
      console.error(e);
    }
  };

  const handleRemoveWorker = async (id: string) => {
    try {
      await fetch(`${API_BASE}/api/workers/${id}`, { method: 'DELETE' });
      fetchWorkers();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="relative">
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
              <div key={w.worker_id} className="border-2 border-fra-black p-2 bg-white relative shadow-sm">
                <button 
                  onClick={() => handleRemoveWorker(w.worker_id)} 
                  className="absolute top-1.5 right-1.5 text-[9px] bg-red-500 text-white px-1.5 py-0.5 border border-black hover:bg-red-600 font-bold"
                >
                  DEL
                </button>
                <div className="flex items-center space-x-2 mb-1">
                  <span className={`w-2 h-2 rounded-full border border-black ${w.status === 'HEALTHY' || w.status === 'READY' ? 'bg-green-500' : w.status === 'COOLDOWN' ? 'bg-yellow-500' : 'bg-red-500'}`}></span>
                  <span className="font-bold text-[11px] uppercase">{w.provider}</span>
                  <span className="text-[9px] bg-neutral-100 border border-neutral-300 px-1 font-mono">P{w.priority ?? 1}</span>
                </div>
                <div className="text-[10px] font-mono font-bold truncate text-neutral-800">{w.model}</div>
                <div className="flex justify-between text-[9px] text-gray-600 mt-1 uppercase font-bold">
                  <span>{w.api_key_hint || "NO KEY"}</span>
                  <span className={w.status === 'COOLDOWN' ? 'text-amber-700' : w.status === 'HEALTHY' ? 'text-green-700' : ''}>
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
              onClick={() => setShowAddForm(true)}
              className="w-full bg-fra-yellow border-2 border-fra-black font-bold text-[11px] py-1.5 hover:bg-yellow-400 uppercase shadow-brutal-sm"
            >
              + Add Worker
            </button>
          ) : (
            <div className="border-2 border-fra-black bg-white p-2.5 flex flex-col space-y-2 text-[10px]">
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
                <label className="font-bold uppercase text-[9px] text-neutral-600">Priority</label>
                <input 
                  type="number" 
                  value={priority} 
                  onChange={e => setPriority(parseInt(e.target.value) || 1)} 
                  className="border-2 border-fra-black p-1 text-[10px] outline-none font-mono" 
                />
              </div>

              <div className="flex flex-col">
                <label className="font-bold uppercase text-[9px] text-neutral-600">API Key</label>
                <input 
                  type="password" 
                  value={apiKey} 
                  onChange={e => setApiKey(e.target.value)} 
                  placeholder="•••••••••••••••••" 
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
                  onClick={handleTestConnection} 
                  disabled={testing || !apiKey}
                  className="flex-1 border-2 border-fra-black bg-neutral-200 text-black font-bold py-1 text-[9px] hover:bg-neutral-300 disabled:opacity-50"
                >
                  {testing ? "Testing..." : "Test Connection"}
                </button>
                <button 
                  onClick={handleAddWorker} 
                  disabled={!apiKey}
                  className="flex-1 border-2 border-fra-black bg-fra-yellow text-black font-bold py-1 text-[9px] hover:bg-yellow-400 disabled:opacity-50"
                >
                  Save Worker
                </button>
              </div>

              <button 
                onClick={() => { setShowAddForm(false); setTestStatus(null); }} 
                className="w-full text-center text-[9px] text-neutral-500 hover:text-black mt-1"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
