"use client";

/**
 * Where the user tells JARVIS what to do: text, attachments, voice.
 *
 * Voice lives in its own component (passed in as `voice`) so the mic's
 * per-frame state never re-renders this one.
 */

import React, { useRef, useState } from "react";

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  busy: boolean;
  attachments: File[];
  onAttach: (files: File[]) => void;
  onRemoveAttachment: (index: number) => void;
  model: string;
  provider: string;
  onOpenModelPicker: () => void;
  voice: React.ReactNode;
  /** Extra controls for the settings row (Turbo arrives in Phase 2). */
  settings?: React.ReactNode;
}

const Composer: React.FC<ComposerProps> = ({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  attachments,
  onAttach,
  onRemoveAttachment,
  model,
  provider,
  onOpenModelPicker,
  voice,
  settings,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  return (
    <div
      className={`flex-shrink-0 border-t-2 border-fra-black bg-fra-cream p-3 transition-colors ${
        dragging ? "bg-fra-yellow/20 ring-2 ring-inset ring-fra-yellow" : ""
      }`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const files = Array.from(e.dataTransfer.files);
        if (files.length) onAttach(files);
      }}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files || []);
          if (files.length) onAttach(files);
          e.target.value = "";
        }}
      />

      {dragging && (
        <div className="mb-2 border-2 border-dashed border-fra-yellow bg-fra-yellow/10 px-3 py-3 text-center font-mono text-[11px] font-bold text-neutral-700">
          Drop files here to attach
        </div>
      )}

      {attachments.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {attachments.map((file, idx) => (
            <div
              key={`${file.name}-${idx}`}
              className="flex items-center space-x-1 border border-neutral-300 bg-neutral-100 px-2 py-1 font-mono text-[10px] font-bold"
            >
              <span className="max-w-[140px] truncate">{file.name}</span>
              <button
                type="button"
                onClick={() => onRemoveAttachment(idx)}
                className="ml-1 font-black text-red-400 hover:text-red-600"
                aria-label={`Remove ${file.name}`}
              >
                &#10005;
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="mb-2 border-2 border-fra-black bg-white p-2 shadow-brutal">
        <textarea
          className="w-full resize-none border-0 p-1 font-mono text-xs text-black placeholder-neutral-500 focus:ring-0"
          placeholder="Tell JARVIS what to do..."
          rows={2}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
        />
        <div className="mt-1 flex items-center justify-between border-t border-neutral-200 pt-1">
          <div className="flex items-center space-x-3 pl-1 text-sm text-neutral-600">
            <button
              type="button"
              className="transition-colors hover:text-black"
              onClick={() => fileInputRef.current?.click()}
              title="Attach files"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            </button>
            <button
              type="button"
              className="font-mono text-xs font-bold hover:text-black"
              title="Insert a code block"
              onClick={() => onChange(`${value}${value && !value.endsWith("\n") ? "\n" : ""}\`\`\`\n\n\`\`\``)}
            >
              &lt;/&gt;
            </button>
          </div>

          <div className="flex items-center space-x-2">
            <span className="hidden font-mono text-[10px] text-neutral-500 sm:inline">
              Enter to send · Shift+Enter for newline
            </span>
            {voice}
            {busy ? (
              <button
                type="button"
                onClick={onStop}
                className="flex items-center space-x-1.5 border-2 border-red-600 bg-red-500 px-4 py-1.5 text-xs font-bold text-white shadow-brutal-sm transition-colors hover:bg-red-600"
                title="Stop this run"
              >
                <span>Stop</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={onSubmit}
                disabled={!value.trim()}
                className="flex items-center space-x-1.5 border-2 border-black bg-black px-4 py-1.5 text-xs font-bold text-white shadow-brutal-sm hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <span>Send</span>
                <span>-&gt;</span>
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 font-mono text-[10px]">
        <button
          type="button"
          className="flex items-center space-x-1.5 border-2 border-fra-black bg-white px-2.5 py-1 font-bold shadow-brutal-sm transition-colors hover:bg-yellow-50"
          onClick={onOpenModelPicker}
        >
          <span>Model</span>
          <span className="border border-black bg-fra-yellow px-1 font-bold text-black">{model}</span>
          <span className="bg-black px-1 text-[9px] uppercase text-white">{provider}</span>
        </button>
        {settings}
      </div>
    </div>
  );
};

export default Composer;
