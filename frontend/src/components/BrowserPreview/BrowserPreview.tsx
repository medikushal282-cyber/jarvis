"use client";

import React, { useState, useRef } from 'react';
import { API_BASE } from "@/lib/runtime/client";

interface BrowserPreviewProps {
  url: string;
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  embedded?: boolean; // When true, renders without fixed height for split-view embedding
}

export const BrowserPreview: React.FC<BrowserPreviewProps> = ({
  url,
  isOpen,
  onClose,
  title = "JARVIS Live Browser Preview",
  embedded = false,
}) => {
  const [deviceMode, setDeviceMode] = useState<'desktop' | 'tablet' | 'mobile'>('desktop');
  const [iframeKey, setIframeKey] = useState<number>(1);
  const [currentUrl, setCurrentUrl] = useState<string>(url);
  const [inputUrl, setInputUrl] = useState<string>(url);
  const [zoom, setZoom] = useState<number>(100);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  React.useEffect(() => {
    setCurrentUrl(url);
    setInputUrl(url);
  }, [url]);

  if (!isOpen) return null;

  const handleNavigate = (e: React.FormEvent) => {
    e.preventDefault();
    let dest = inputUrl.trim();
    if (!dest) return;
    if (!dest.startsWith('http://') && !dest.startsWith('https://')) {
      let wsId = 'default';
      try {
        const urlObj = new URL(currentUrl);
        const parts = urlObj.pathname.split('/');
        if (parts.length >= 4 && parts[1] === 'api' && parts[2] === 'preview') {
          wsId = parts[3];
        }
      } catch (e) {}
      dest = `${API_BASE}/api/preview/${wsId}/${dest}`;
    }
    setCurrentUrl(dest);
    setInputUrl(dest);
    setIframeKey(prev => prev + 1);
  };

  const handleReload = () => {
    setIframeKey(prev => prev + 1);
  };

  const handleOpenNewTab = () => {
    window.open(currentUrl, '_blank', 'noopener,noreferrer');
  };

  const getContainerWidth = () => {
    switch (deviceMode) {
      case 'mobile':
        return 'max-w-[390px]';
      case 'tablet':
        return 'max-w-[768px]';
      default:
        return 'w-full';
    }
  };

  const zoomLevels = [50, 75, 100, 125, 150];

  return (
    <div className={`border-2 border-fra-black bg-white shadow-brutal flex flex-col overflow-hidden select-none ${embedded ? 'h-full' : 'h-[560px] mb-4'}`}>
      {/* Browser Chrome Header */}
      <div className="bg-[#0A0A0A] text-white px-3 py-2 border-b-2 border-black flex items-center justify-between gap-2 flex-shrink-0">
        {/* Left Window Controls & Title */}
        <div className="flex items-center space-x-2 flex-shrink-0">
          <div className="flex items-center space-x-1.5 mr-1">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500 inline-block"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-yellow-500 inline-block"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block"></span>
          </div>
          <span className="font-mono font-bold text-[10px] text-neutral-300 hidden lg:inline">
            {title}
          </span>
        </div>

        {/* Center URL Address Bar */}
        <form onSubmit={handleNavigate} className="flex-1 max-w-md mx-auto flex items-center bg-[#171717] border border-neutral-700 px-2 py-1 rounded text-xs font-mono text-neutral-200">
          <span className="text-neutral-500 mr-1.5 text-[10px]">🔒</span>
          <input
            type="text"
            value={inputUrl}
            onChange={(e) => setInputUrl(e.target.value)}
            className="flex-1 bg-transparent text-[10px] text-fra-yellow focus:outline-none font-mono"
            placeholder="Type file name or URL..."
          />
          <button type="submit" className="text-[10px] text-neutral-400 hover:text-white ml-1 px-1 font-bold">
            GO
          </button>
          <div className="flex items-center space-x-1.5 ml-2 border-l border-neutral-800 pl-2">
            <span className="w-2 h-2 rounded-full bg-fra-green animate-pulse" title="Live Auto-Sync Active"></span>
            <span className="text-[9px] text-fra-green font-bold uppercase hidden md:inline">SYNC</span>
          </div>
        </form>

        {/* Right Action Tools */}
        <div className="flex items-center space-x-1 text-xs font-mono flex-shrink-0">
          {/* Reload */}
          <button onClick={handleReload} className="border border-neutral-700 bg-neutral-900 hover:bg-neutral-800 text-white px-1.5 py-0.5 text-[10px]" title="Reload">↻</button>

          {/* Zoom Controls */}
          <div className="hidden md:flex items-center border border-neutral-700 bg-neutral-900 text-[9px]">
            <button
              onClick={() => setZoom(prev => Math.max(50, prev - 25))}
              className="px-1 py-0.5 text-neutral-400 hover:text-white"
              title="Zoom Out"
            >−</button>
            <span className="px-1 py-0.5 text-fra-yellow font-bold border-x border-neutral-700 min-w-[36px] text-center">{zoom}%</span>
            <button
              onClick={() => setZoom(prev => Math.min(150, prev + 25))}
              className="px-1 py-0.5 text-neutral-400 hover:text-white"
              title="Zoom In"
            >+</button>
          </div>

          {/* Device Switcher */}
          <div className="hidden lg:flex items-center border border-neutral-700 bg-neutral-900 text-[9px]">
            <button onClick={() => setDeviceMode('desktop')} className={`px-1.5 py-0.5 ${deviceMode === 'desktop' ? 'bg-fra-yellow text-black font-bold' : 'text-neutral-400'}`}>🖥</button>
            <button onClick={() => setDeviceMode('tablet')} className={`px-1.5 py-0.5 ${deviceMode === 'tablet' ? 'bg-fra-yellow text-black font-bold' : 'text-neutral-400'}`}>📱</button>
            <button onClick={() => setDeviceMode('mobile')} className={`px-1.5 py-0.5 ${deviceMode === 'mobile' ? 'bg-fra-yellow text-black font-bold' : 'text-neutral-400'}`}>📲</button>
          </div>

          {/* Open in Tab */}
          <button
            onClick={handleOpenNewTab}
            className="border-2 border-black bg-fra-yellow text-black font-bold text-[9px] px-2 py-0.5 flex items-center space-x-1 shadow-brutal-sm hover:bg-yellow-400 uppercase"
          >
            <span>Tab</span><span>↗</span>
          </button>

          {/* Close */}
          <button onClick={onClose} className="text-neutral-400 hover:text-white px-1 text-sm font-bold" title="Close Preview">✕</button>
        </div>
      </div>

      {/* Frame Container */}
      <div className="flex-1 bg-neutral-100 flex items-start justify-center overflow-auto p-1">
        <div
          className={`${getContainerWidth()} mx-auto bg-white shadow-md flex flex-col overflow-hidden`}
          style={{
            zoom: zoom / 100,
            height: '100%',
            minHeight: embedded ? '100%' : '500px',
          }}
        >
          <iframe
            key={iframeKey}
            ref={iframeRef}
            src={currentUrl}
            title="Live Preview"
            className="w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-popups allow-top-navigation"
          />
        </div>
      </div>
    </div>
  );
};

export default BrowserPreview;

