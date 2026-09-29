"use client";

/**
 * A compact card for something JARVIS produced: what it is, how big, and
 * two actions -- open it here, or download it. Built from `ArtifactView`,
 * which never carries a filesystem path.
 */

import React from "react";

import { API_BASE } from "@/lib/runtime/client";
import type { ArtifactView } from "@/lib/runtime/runReducer";

const absolute = (url: string) => (url.startsWith("/") ? `${API_BASE}${url}` : url);

export function formatBytes(n: number): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const KIND_BY_EXT: Record<string, string> = {
  html: "HTML", htm: "HTML", png: "IMG", jpg: "IMG", jpeg: "IMG", gif: "IMG", svg: "IMG", webp: "IMG",
  pdf: "PDF", csv: "CSV", json: "JSON", md: "MD", txt: "TXT",
  py: "CODE", js: "CODE", ts: "CODE", tsx: "CODE", jsx: "CODE", css: "CODE", java: "CODE", go: "CODE",
  pptx: "DECK", docx: "DOC", xlsx: "SHEET", zip: "ZIP",
};

function kindOf(a: ArtifactView): string {
  if (!a.downloadUrl && a.url && /^https?:/i.test(a.url)) return "LINK";
  const ext = a.filename.split(".").pop()?.toLowerCase() ?? "";
  if (KIND_BY_EXT[ext]) return KIND_BY_EXT[ext];
  if (a.mimeType?.startsWith("image/")) return "IMG";
  if (a.mimeType?.startsWith("text/")) return "TXT";
  return "FILE";
}

const ACTION_TEXT: Record<string, string> = {
  created: "created",
  modified: "edited",
  deleted: "deleted",
};

interface ArtifactCardProps {
  artifact: ArtifactView;
  onOpen: (artifact: ArtifactView) => void;
}

const ArtifactCard: React.FC<ArtifactCardProps> = ({ artifact, onOpen }) => {
  const kind = kindOf(artifact);
  const deleted = artifact.action === "deleted";
  const meta = [formatBytes(artifact.size), artifact.action ? ACTION_TEXT[artifact.action] ?? artifact.action : ""]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      className={`inline-flex w-60 flex-col gap-1.5 border-2 border-black bg-white p-2 font-mono shadow-brutal-sm ${
        deleted ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="flex-shrink-0 border border-black bg-fra-yellow px-1 text-[9px] font-extrabold">{kind}</span>
        <span className="truncate text-[12px] font-bold text-black" title={artifact.filename}>
          {artifact.filename}
        </span>
      </div>
      {meta && <div className="text-[10px] text-neutral-500">{meta}</div>}
      {!deleted && (
        <div className="flex gap-1.5">
          {artifact.previewable && artifact.url && (
            <button
              type="button"
              onClick={() => onOpen(artifact)}
              className="border border-black bg-black px-2 py-0.5 text-[10px] font-bold text-white hover:bg-neutral-800"
            >
              Open
            </button>
          )}
          {artifact.downloadUrl && (
            <a
              href={absolute(artifact.downloadUrl)}
              download={artifact.filename}
              className="border border-black bg-white px-2 py-0.5 text-[10px] font-bold text-black hover:bg-fra-yellow"
            >
              Download
            </a>
          )}
          {!artifact.previewable && !artifact.downloadUrl && artifact.url && (
            <a
              href={absolute(artifact.url)}
              target="_blank"
              rel="noreferrer noopener"
              className="border border-black bg-white px-2 py-0.5 text-[10px] font-bold text-black hover:bg-fra-yellow"
            >
              Visit
            </a>
          )}
        </div>
      )}
    </div>
  );
};

export default ArtifactCard;
