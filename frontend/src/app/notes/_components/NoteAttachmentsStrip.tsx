"use client";

import { X } from "lucide-react";
import { parseNoteAttachments } from "../_lib/parse-note-attachments";

type NoteAttachmentsStripProps = {
  content: string;
  onFileClick: (url: string, filename: string) => void;
  onDeleteFile: (fileUrl: string, markdownText: string) => void;
};

export function NoteAttachmentsStrip({
  content,
  onFileClick,
  onDeleteFile,
}: NoteAttachmentsStripProps) {
  const attachments = parseNoteAttachments(content);
  if (attachments.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-white/5 bg-white/[0.02] px-6 py-2">
      <span className="text-xs text-white/30">Attachments:</span>
      {attachments.map((att) => (
        <span
          key={att.url}
          className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/60"
        >
          <button
            onClick={() =>
              onFileClick(att.url, att.label.replace(/^[📎🎤]\s*/, ""))
            }
            className="hover:text-white/90 transition-colors"
          >
            {att.label}
          </button>
          <button
            onClick={() => onDeleteFile(att.url, att.raw)}
            className="ml-1 rounded text-white/30 hover:text-red-400 transition-colors"
            title="Delete file"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
    </div>
  );
}
