"use client";

import type { WikilinkPreviewState } from "../_lib/types";

type WikilinkHoverCardProps = {
  preview: WikilinkPreviewState;
};

export function WikilinkHoverCard({ preview }: WikilinkHoverCardProps) {
  return (
    <div
      className="pointer-events-none fixed z-[80] w-80 overflow-hidden rounded-xl border border-teal-500/30 bg-black/95 shadow-2xl backdrop-blur-xl"
      style={{ left: preview.x, top: preview.y }}
    >
      <div className="border-b border-white/10 px-3 py-2">
        <p className="truncate text-sm font-medium text-teal-200">
          {preview.title}
        </p>
        {preview.missing && (
          <p className="text-[11px] text-teal-300/80">Click to create</p>
        )}
      </div>
      <div className="max-h-44 overflow-hidden px-3 py-2">
        <p className="whitespace-pre-wrap text-xs leading-relaxed text-white/70 line-clamp-[10]">
          {preview.missing
            ? "This note does not exist yet. Click the link to create it."
            : preview.content.slice(0, 600) || "Empty note"}
        </p>
      </div>
    </div>
  );
}
