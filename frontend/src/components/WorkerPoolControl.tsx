import React, { useState, useEffect } from 'react';

export default function WorkerPoolControl() {
  const [open, setOpen] = useState(false);
  const [workers, setWorkers] = useState<any[]>([]);
  const [showAddForm, setShowAddForm] = useState(false);

  const [provider, setProvider] = useState('groq');
  const [model, setModel] = useState('llama-3.1-8b-instant');
  const [apiKey, setApiKey] = useState('');

  const fetchWorkers = async () => {
    try {
      const res = await fetch('http://localhost:8006/api/workers');
      if (res.ok) {
        setWorkers(await res.json());
      }
    } catch (e) {
      console.warn("Could not fetch workers", e);
    }
  };

  useEffect(() => {
    if (open) {
      fetchWorkers();
      const interval = setInterval(fetchWorkers, 3000);
      return () => clearInterval(interval);
    }
  }, [open]);

  const handleAddWorker = async () => {
    if (!apiKey) return;
    try {
      await fetch('http://localhost:8006/api/workers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, model, api_key: apiKey })
      });
      setShowAddForm(false);
      setApiKey('');
      fetchWorkers();
    } catch (e) {
      console.error(e);
    }
  };

  const handleRemoveWorker = async (id: string) => {
    try {
      await fetch(`http://localhost:8006/api/workers/${id}`, { method: 'DELETE' });
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
        <span className="text-xs font-mono font-black">[WORKERS {workers.length} \u25CF]</span>
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-72 border-2 border-fra-black bg-fra-cream-card shadow-brutal z-50 p-2 font-mono flex flex-col max-h-[80vh] overflow-y-auto">
          <div className="flex justify-between items-center mb-2 border-b-2 border-fra-black pb-1">
            <span className="font-bold text-xs uppercase">Worker Pool</span>
            <button onClick={() => setOpen(false)} className="text-lg leading-none font-bold hover:text-red-500">\u00d7</button>
          </div>

          <div className="flex flex-col space-y-2 mb-3">
            {workers.map(w => (
              <div key={w.worker_id} className="border-2 border-fra-black p-2 bg-white relative">
                <button onClick={() => handleRemoveWorker(w.worker_id)} className="absolute top-1 right-1 text-[10px] bg-red-500 text-white px-1 border border-black hover:bg-red-600">DEL</button>
                <div className="flex items-center space-x-2 mb-1">
                  <span className={`w-2 h-2 rounded-full border border-black ${w.status === 'HEALTHY' || w.status === 'READY' ? 'bg-green-500' : w.status === 'COOLDOWN' ? 'bg-yellow-500' : 'bg-red-500'}`}></span>
                  <span className="font-bold text-[10px] uppercase">{w.provider}</span>
                </div>
                <div className="text-[10px] font-bold truncate">{w.model}</div>
                <div className="flex justify-between text-[9px] text-gray-500 mt-1 uppercase font-bold">
                  <span>{w.api_key_hint || "NO KEY"}</span>
                  <span>{w.status}{w.cooldown_remaining ? ` - ${w.cooldown_remaining}S` : ''}</span>
                </div>
              </div>
            ))}
            {workers.length === 0 && <div className="text-[10px] text-gray-500 p-2 text-center font-bold">No workers configured</div>}
          </div>

          {!showAddForm ? (
            <button 
              onClick={() => setShowAddForm(true)}
              className="w-full bg-fra-yellow border-2 border-fra-black font-bold text-[11px] py-1 hover:bg-yellow-400 uppercase"
            >
              + Add Worker
            </button>
          ) : (
            <div className="border-2 border-fra-black bg-gray-100 p-2 flex flex-col space-y-2 text-[10px]">
              <div className="flex flex-col">
                <label className="font-bold uppercase">Provider</label>
                <select value={provider} onChange={e => setProvider(e.target.value)} className="border-2 border-fra-black p-1 text-[10px] outline-none">
                  <option value="groq">Groq</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </div>
              <div className="flex flex-col">
                <label className="font-bold uppercase">Model</label>
                <input type="text" value={model} onChange={e => setModel(e.target.value)} className="border-2 border-fra-black p-1 text-[10px] outline-none" />
              </div>
              <div className="flex flex-col">
                <label className="font-bold uppercase">API Key</label>
                <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="•••••••••••••••••" className="border-2 border-fra-black p-1 text-[10px] outline-none" />
              </div>
              <div className="flex space-x-2 mt-2">
                <button onClick={() => setShowAddForm(false)} className="flex-1 border-2 border-fra-black bg-white font-bold py-1 hover:bg-gray-200">CANCEL</button>
                <button onClick={handleAddWorker} className="flex-1 border-2 border-fra-black bg-black text-white font-bold py-1 hover:bg-gray-800">SAVE</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
