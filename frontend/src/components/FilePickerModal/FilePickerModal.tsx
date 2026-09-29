"use client";

import React, { useState, useEffect } from 'react';
import { API_BASE } from "@/lib/runtime/client";

interface FileEntry {
  name: string;
  path: string;
  is_directory: boolean;
  size: number;
}

interface FilePickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (files: { path: string; name: string }[]) => void;
  workspaceId: string;
}

const DOCUMENT_EXTS = ['.pdf', '.odf', '.md', '.docx', '.doc', '.txt', '.csv', '.xlsx', '.json', '.yaml', '.yml'];

export const FilePickerModal: React.FC<FilePickerModalProps> = ({ isOpen, onClose, onSelect, workspaceId }) => {
  const [currentPath, setCurrentPath] = useState('');
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [pathHistory, setPathHistory] = useState<string[]>(['']);

  const fetchFiles = async (path: string) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/workspace/files?path=${encodeURIComponent(path)}`, {
        headers: {
          'X-Workspace-Id': workspaceId || 'default'
        }
      });
      if (!res.ok) throw new Error('Failed to load files');
      const data = await res.json();
      if (data.success && data.entries) {
        // Sort: directories first, then files alphabetically
        const sorted = data.entries.sort((a: FileEntry, b: FileEntry) => {
          if (a.is_directory && !b.is_directory) return -1;
          if (!a.is_directory && b.is_directory) return 1;
          return a.name.localeCompare(b.name);
        });
        setEntries(sorted);
      } else {
        setError(data.error || 'Failed to load directory');
      }
    } catch (e: any) {
      setError(e.message || 'Network error');
    }
    setLoading(false);
  };

  useEffect(() => {
    if (isOpen) {
      setSelected(new Set());
      setCurrentPath('');
      setPathHistory(['']);
      fetchFiles('');
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const navigateInto = (dirPath: string) => {
    setCurrentPath(dirPath);
    setPathHistory(prev => [...prev, dirPath]);
    fetchFiles(dirPath);
  };

  const navigateBack = () => {
    if (pathHistory.length > 1) {
      const newHistory = [...pathHistory];
      newHistory.pop();
      const prev = newHistory[newHistory.length - 1];
      setCurrentPath(prev);
      setPathHistory(newHistory);
      fetchFiles(prev);
    }
  };

  const toggleSelect = (path: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const handleConfirm = () => {
    const files = Array.from(selected).map(p => {
      const name = p.split('/').pop() || p;
      return { path: p, name };
    });
    onSelect(files);
    onClose();
  };

  const getFileIcon = (entry: FileEntry) => {
    if (entry.is_directory) return '📁';
    const ext = entry.name.substring(entry.name.lastIndexOf('.')).toLowerCase();
    if (['.html', '.htm'].includes(ext)) return '🌐';
    if (['.py'].includes(ext)) return '🐍';
    if (['.js', '.ts', '.jsx', '.tsx'].includes(ext)) return '⚡';
    if (['.css'].includes(ext)) return '🎨';
    if (['.json', '.yaml', '.yml'].includes(ext)) return '📋';
    if (['.md'].includes(ext)) return '📝';
    if (['.pdf'].includes(ext)) return '📄';
    if (['.png', '.jpg', '.svg', '.gif'].includes(ext)) return '🖼️';
    return '📄';
  };

  const isDocumentType = (name: string) => {
    return DOCUMENT_EXTS.some(ext => name.toLowerCase().endsWith(ext));
  };

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '—';
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg border-2 border-fra-black bg-fra-cream shadow-brutal-lg font-mono flex flex-col max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between border-b-2 border-fra-black p-3">
          <div className="flex items-center space-x-2">
            <span className="bg-black text-white px-1.5 py-0.5 text-[10px] font-bold">FILE PICKER</span>
            <span className="text-[11px] font-bold">Add Files to Artifacts</span>
          </div>
          <button className="font-black text-sm px-1.5 hover:bg-neutral-200" onClick={onClose}>✕</button>
        </div>

        {/* Breadcrumb / Path */}
        <div className="flex items-center space-x-2 px-3 py-2 border-b border-neutral-300 bg-white text-[10px]">
          <button
            onClick={() => { setCurrentPath(''); setPathHistory(['']); fetchFiles(''); }}
            className="font-bold text-black hover:text-fra-green"
          >
            ROOT
          </button>
          {currentPath && currentPath.split('/').filter(Boolean).map((seg, i, arr) => {
            const partial = arr.slice(0, i + 1).join('/');
            return (
              <React.Fragment key={partial}>
                <span className="text-neutral-400">/</span>
                <button
                  onClick={() => navigateInto(partial)}
                  className="font-bold text-neutral-700 hover:text-black"
                >
                  {seg}
                </button>
              </React.Fragment>
            );
          })}
          {pathHistory.length > 1 && (
            <button
              onClick={navigateBack}
              className="ml-auto text-[10px] border border-black px-1.5 py-0.5 bg-neutral-100 hover:bg-fra-yellow font-bold"
            >
              ← Back
            </button>
          )}
        </div>

        {/* File List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-0.5 min-h-[200px]">
          {loading ? (
            <div className="flex items-center justify-center py-8 text-[11px] text-neutral-500">
              <span className="animate-pulse">Loading files...</span>
            </div>
          ) : error ? (
            <div className="text-red-600 text-[11px] font-bold p-2">{error}</div>
          ) : entries.length === 0 ? (
            <div className="text-neutral-400 text-[11px] italic text-center py-8">Empty directory</div>
          ) : (
            entries.map(entry => (
              <div
                key={entry.path}
                className={`flex items-center justify-between p-1.5 border transition-colors cursor-pointer ${
                  selected.has(entry.path)
                    ? 'bg-fra-yellow border-black'
                    : 'border-transparent hover:bg-neutral-100 hover:border-neutral-300'
                }`}
                onClick={() => {
                  if (entry.is_directory) {
                    navigateInto(entry.path);
                  } else {
                    toggleSelect(entry.path);
                  }
                }}
              >
                <div className="flex items-center space-x-2 min-w-0 flex-1">
                  <span className="text-sm flex-shrink-0">{getFileIcon(entry)}</span>
                  <span className={`text-[11px] truncate ${entry.is_directory ? 'font-bold text-black' : 'text-neutral-800'}`}>
                    {entry.name}
                  </span>
                  {!entry.is_directory && isDocumentType(entry.name) && (
                    <span className="text-[8px] bg-blue-100 text-blue-800 border border-blue-300 px-1 font-bold flex-shrink-0">
                      DOCUMENT
                    </span>
                  )}
                </div>
                <div className="flex items-center space-x-2 flex-shrink-0">
                  {!entry.is_directory && (
                    <span className="text-[9px] text-neutral-400">{formatSize(entry.size)}</span>
                  )}
                  {entry.is_directory ? (
                    <span className="text-[10px] text-neutral-400 font-bold">→</span>
                  ) : (
                    <span className={`w-3 h-3 border-2 border-black flex items-center justify-center text-[8px] font-bold ${
                      selected.has(entry.path) ? 'bg-black text-white' : 'bg-white'
                    }`}>
                      {selected.has(entry.path) ? '✓' : ''}
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t-2 border-fra-black p-3 bg-white">
          <span className="text-[10px] text-neutral-600 font-bold">
            {selected.size} file{selected.size !== 1 ? 's' : ''} selected
          </span>
          <div className="flex items-center space-x-2">
            <button
              onClick={onClose}
              className="border-2 border-black bg-white text-black px-3 py-1.5 text-[11px] font-bold hover:bg-neutral-100"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirm}
              disabled={selected.size === 0}
              className={`border-2 border-black px-3 py-1.5 text-[11px] font-bold shadow-brutal-sm ${
                selected.size > 0
                  ? 'bg-fra-yellow text-black hover:bg-yellow-400'
                  : 'bg-neutral-200 text-neutral-500 cursor-not-allowed'
              }`}
            >
              Attach {selected.size > 0 ? `(${selected.size})` : ''}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default FilePickerModal;
