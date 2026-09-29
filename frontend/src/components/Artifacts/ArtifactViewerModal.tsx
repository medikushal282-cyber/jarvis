'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { 
  X, Download, ExternalLink, FileText, Image as ImageIcon, 
  FileCode, Table, Film, FileQuestion, Copy, Check, ZoomIn, ZoomOut, RotateCcw
} from 'lucide-react';

export interface ArtifactData {
  artifact_id: string;
  filename: string;
  file_path?: string;
  mime_type: string;
  size: number;
  url: string;
  download_url: string;
  preview_supported?: boolean;
  viewer_type: 'image' | 'pdf' | 'markdown' | 'code' | 'csv' | 'json' | 'text' | 'video' | 'unsupported';
  created_at?: number;
  metadata?: Record<string, any>;
}

interface ArtifactViewerModalProps {
  artifact: ArtifactData | null;
  onClose: () => void;
}

export const ArtifactViewerModal: React.FC<ArtifactViewerModalProps> = ({ artifact, onClose }) => {
  const [textContent, setTextContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Fetch text/csv/json/code content for inline rendering
  useEffect(() => {
    if (!artifact) return;
    setZoomLevel(1);
    const textTypes = ['markdown', 'code', 'csv', 'json', 'text'];
    if (textTypes.includes(artifact.viewer_type)) {
      setLoading(true);
      fetch(`http://localhost:8006${artifact.url}`)
        .then(res => res.text())
        .then(text => {
          setTextContent(text);
          setLoading(false);
        })
        .catch(err => {
          console.error('Failed to fetch artifact content', err);
          setTextContent('Error loading artifact content.');
          setLoading(false);
        });
    } else {
      setTextContent(null);
    }
  }, [artifact]);

  const handleCopy = () => {
    if (textContent) {
      navigator.clipboard.writeText(textContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  // CSV parsing
  const csvData = useMemo(() => {
    if (!textContent || artifact?.viewer_type !== 'csv') return null;
    const lines = textContent.trim().split('\n');
    if (lines.length === 0) return null;
    const headers = lines[0].split(',').map(h => h.trim().replace(/^["']|["']$/g, ''));
    const rows = lines.slice(1).map(line => line.split(',').map(cell => cell.trim().replace(/^["']|["']$/g, '')));
    return { headers, rows };
  }, [textContent, artifact]);

  // JSON parsing
  const formattedJson = useMemo(() => {
    if (!textContent || artifact?.viewer_type !== 'json') return null;
    try {
      const parsed = JSON.parse(textContent);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return textContent;
    }
  }, [textContent, artifact]);

  if (!artifact) return null;

  const formatSize = (bytes: number) => {
    if (!bytes || bytes === 0) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getViewerIcon = () => {
    switch (artifact.viewer_type) {
      case 'image': return <ImageIcon className="w-5 h-5 text-emerald-400" />;
      case 'pdf': return <FileText className="w-5 h-5 text-rose-400" />;
      case 'csv': return <Table className="w-5 h-5 text-amber-400" />;
      case 'code':
      case 'json': return <FileCode className="w-5 h-5 text-sky-400" />;
      case 'markdown':
      case 'text': return <FileText className="w-5 h-5 text-indigo-400" />;
      case 'video': return <Film className="w-5 h-5 text-purple-400" />;
      default: return <FileQuestion className="w-5 h-5 text-zinc-400" />;
    }
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 md:p-8 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div 
        className="relative w-full max-w-5xl max-h-[90vh] bg-zinc-950 border border-zinc-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-zinc-100"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800/80 bg-zinc-900/50">
          <div className="flex items-center space-x-3 truncate mr-4">
            <div className="p-2 rounded-lg bg-zinc-800/60 border border-zinc-700/50">
              {getViewerIcon()}
            </div>
            <div className="truncate">
              <h3 className="text-sm font-semibold text-zinc-100 truncate tracking-tight">{artifact.filename}</h3>
              <div className="flex items-center space-x-2 text-xs text-zinc-400 font-mono mt-0.5">
                <span className="uppercase px-1.5 py-0.2 bg-zinc-800 rounded text-[10px] text-zinc-300 font-medium">
                  {artifact.viewer_type}
                </span>
                <span>•</span>
                <span>{formatSize(artifact.size)}</span>
                {artifact.metadata?.width && artifact.metadata?.height && (
                  <>
                    <span>•</span>
                    <span>{artifact.metadata.width} × {artifact.metadata.height}px</span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            {/* Zoom controls for images */}
            {artifact.viewer_type === 'image' && (
              <div className="flex items-center bg-zinc-800/60 rounded-lg p-1 mr-2 border border-zinc-700/40">
                <button
                  onClick={() => setZoomLevel(prev => Math.max(0.5, prev - 0.25))}
                  className="p-1 hover:bg-zinc-700/60 rounded text-zinc-400 hover:text-zinc-200 transition"
                  title="Zoom Out"
                >
                  <ZoomOut className="w-4 h-4" />
                </button>
                <span className="text-xs font-mono px-2 text-zinc-300">{Math.round(zoomLevel * 100)}%</span>
                <button
                  onClick={() => setZoomLevel(prev => Math.min(3, prev + 0.25))}
                  className="p-1 hover:bg-zinc-700/60 rounded text-zinc-400 hover:text-zinc-200 transition"
                  title="Zoom In"
                >
                  <ZoomIn className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setZoomLevel(1)}
                  className="p-1 hover:bg-zinc-700/60 rounded text-zinc-400 hover:text-zinc-200 transition ml-1"
                  title="Reset Zoom"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                </button>
              </div>
            )}

            {/* Copy button for code/text */}
            {textContent && (
              <button
                onClick={handleCopy}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-zinc-800/80 hover:bg-zinc-700 text-xs font-medium text-zinc-200 border border-zinc-700/60 transition"
                title="Copy content"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
            )}

            {/* Open in new tab */}
            <a
              href={`http://localhost:8006${artifact.url}`}
              target="_blank"
              rel="noreferrer"
              className="p-2 rounded-lg bg-zinc-800/80 hover:bg-zinc-700 text-zinc-300 hover:text-white border border-zinc-700/60 transition"
              title="Open raw content in new tab"
            >
              <ExternalLink className="w-4 h-4" />
            </a>

            {/* Download button */}
            <a
              href={`http://localhost:8006${artifact.download_url}`}
              download={artifact.filename}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-xs font-medium text-white shadow-sm transition"
              title="Download artifact"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download</span>
            </a>

            {/* Close button */}
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-zinc-800 text-zinc-400 hover:text-zinc-100 transition ml-1"
              title="Close (Esc)"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Viewer Content Area */}
        <div className="flex-1 overflow-auto bg-zinc-950 p-4 sm:p-6 flex items-center justify-center min-h-[300px]">
          {loading ? (
            <div className="flex flex-col items-center space-y-3 py-12 text-zinc-400">
              <div className="w-6 h-6 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-xs font-mono">Loading artifact...</span>
            </div>
          ) : (
            <>
              {/* IMAGE VIEWER */}
              {artifact.viewer_type === 'image' && (
                <div className="w-full h-full flex items-center justify-center overflow-auto p-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`http://localhost:8006${artifact.url}`}
                    alt={artifact.filename}
                    style={{ transform: `scale(${zoomLevel})`, transformOrigin: 'center center' }}
                    className="max-h-[70vh] max-w-full object-contain rounded-lg shadow-lg transition-transform duration-150"
                  />
                </div>
              )}

              {/* PDF VIEWER */}
              {artifact.viewer_type === 'pdf' && (
                <iframe
                  src={`http://localhost:8006${artifact.url}`}
                  title={artifact.filename}
                  className="w-full h-[75vh] rounded-lg border border-zinc-800 bg-white"
                />
              )}

              {/* CSV VIEWER */}
              {artifact.viewer_type === 'csv' && csvData && (
                <div className="w-full h-[70vh] overflow-auto border border-zinc-800 rounded-xl bg-zinc-900/40">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead className="sticky top-0 bg-zinc-800 text-zinc-200 uppercase font-mono text-[11px] shadow">
                      <tr>
                        {csvData.headers.map((h, i) => (
                          <th key={i} className="px-4 py-2.5 border-b border-zinc-700 font-semibold">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/80 font-mono text-zinc-300">
                      {csvData.rows.map((row, rIndex) => (
                        <tr key={rIndex} className="hover:bg-zinc-800/40 transition">
                          {row.map((cell, cIndex) => (
                            <td key={cIndex} className="px-4 py-2 truncate max-w-xs">{cell}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* JSON VIEWER */}
              {artifact.viewer_type === 'json' && formattedJson && (
                <pre className="w-full h-[70vh] overflow-auto p-4 rounded-xl bg-zinc-900/60 border border-zinc-800 font-mono text-xs text-sky-300 leading-relaxed">
                  {formattedJson}
                </pre>
              )}

              {/* CODE / MARKDOWN / TEXT VIEWER */}
              {(artifact.viewer_type === 'code' || artifact.viewer_type === 'markdown' || artifact.viewer_type === 'text') && textContent && (
                <div className="w-full h-[70vh] overflow-auto p-4 rounded-xl bg-zinc-900/60 border border-zinc-800 font-mono text-xs leading-relaxed">
                  <div className="whitespace-pre-wrap break-words text-zinc-200">
                    {textContent}
                  </div>
                </div>
              )}

              {/* VIDEO VIEWER */}
              {artifact.viewer_type === 'video' && (
                <video
                  controls
                  src={`http://localhost:8006${artifact.url}`}
                  className="max-h-[70vh] max-w-full rounded-xl shadow-lg border border-zinc-800"
                >
                  Your browser does not support HTML5 video preview.
                </video>
              )}

              {/* UNSUPPORTED / BINARY */}
              {artifact.viewer_type === 'unsupported' && (
                <div className="flex flex-col items-center justify-center p-12 text-center space-y-4">
                  <div className="p-4 rounded-2xl bg-zinc-900 border border-zinc-800 text-zinc-400">
                    <FileQuestion className="w-10 h-10" />
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-zinc-200">{artifact.filename}</h4>
                    <p className="text-xs text-zinc-400 mt-1">Direct in-browser preview is not available for this file type ({artifact.mime_type}).</p>
                  </div>
                  <a
                    href={`http://localhost:8006${artifact.download_url}`}
                    download={artifact.filename}
                    className="flex items-center space-x-2 px-4 py-2 bg-cyan-600 hover:bg-cyan-500 rounded-lg text-xs font-semibold text-white transition"
                  >
                    <Download className="w-4 h-4" />
                    <span>Download File ({formatSize(artifact.size)})</span>
                  </a>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

