import React from 'react';
import { 
  FileText, ImageIcon, FileCode, Table, 
  Film, FileQuestion, Download, Eye 
} from './Icons';
import { ArtifactData } from './ArtifactViewerModal';

interface ArtifactCardProps {
  artifact: ArtifactData;
  onPreview: (artifact: ArtifactData) => void;
  compact?: boolean;
}

export const ArtifactCard: React.FC<ArtifactCardProps> = ({ artifact, onPreview, compact = false }) => {
  const getIcon = () => {
    switch (artifact.viewer_type) {
      case 'image': return <ImageIcon className="w-4 h-4 text-emerald-400" />;
      case 'pdf': return <FileText className="w-4 h-4 text-rose-400" />;
      case 'csv': return <Table className="w-4 h-4 text-amber-400" />;
      case 'code':
      case 'json': return <FileCode className="w-4 h-4 text-sky-400" />;
      case 'markdown':
      case 'text': return <FileText className="w-4 h-4 text-indigo-400" />;
      case 'video': return <Film className="w-4 h-4 text-purple-400" />;
      default: return <FileQuestion className="w-4 h-4 text-zinc-400" />;
    }
  };

  const formatSize = (bytes: number) => {
    if (!bytes || bytes === 0) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div
      onClick={() => onPreview(artifact)}
      className="group inline-flex items-center space-x-2.5 px-3 py-1.5 bg-zinc-900/90 hover:bg-zinc-800/90 border border-zinc-800 hover:border-zinc-700 rounded-xl cursor-pointer transition-all duration-150 shadow-sm select-none"
      title={`Click to preview ${artifact.filename}`}
    >
      <div className="p-1 rounded-md bg-zinc-800/80 border border-zinc-700/40 group-hover:scale-105 transition">
        {getIcon()}
      </div>

      <div className="flex flex-col text-left truncate">
        <span className="text-xs font-semibold text-zinc-200 group-hover:text-cyan-400 transition truncate max-w-[200px] sm:max-w-xs">
          {artifact.filename}
        </span>
        <span className="text-[10px] font-mono text-zinc-400">
          {formatSize(artifact.size)}
        </span>
      </div>

      <div className="flex items-center space-x-1 pl-1 text-zinc-400 group-hover:text-zinc-200">
        <div className="p-1 rounded hover:bg-zinc-700/60 transition" title="Preview">
          <Eye className="w-3.5 h-3.5" />
        </div>
        <a
          href={`http://localhost:8006${artifact.download_url}`}
          download={artifact.filename}
          onClick={(e) => e.stopPropagation()}
          className="p-1 rounded hover:bg-zinc-700/60 text-zinc-400 hover:text-cyan-400 transition"
          title="Download"
        >
          <Download className="w-3.5 h-3.5" />
        </a>
      </div>
    </div>
  );
};
