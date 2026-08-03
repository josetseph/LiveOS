"use client";

import { Loader2, Trash2 } from "lucide-react";

type NotesBatchBarProps = {
  noteCount: number;
  selectedCount: number;
  batchDeleting: boolean;
  onToggleSelectAll: () => void;
  onBatchDelete: () => void;
};

export function NotesBatchBar({
  noteCount,
  selectedCount,
  batchDeleting,
  onToggleSelectAll,
  onBatchDelete,
}: NotesBatchBarProps) {
  if (noteCount === 0) return null;

  return (
    <div className="mt-2 flex items-center gap-2 px-2">
      <button
        type="button"
        onClick={onToggleSelectAll}
        className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/60 hover:bg-white/10 hover:text-white"
      >
        {selectedCount === noteCount ? "Clear selection" : "Select all"}
      </button>
      {selectedCount > 0 && (
        <button
          type="button"
          disabled={batchDeleting}
          onClick={() => void onBatchDelete()}
          className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1 text-[11px] text-red-300 hover:bg-red-500/20 disabled:opacity-50"
        >
          {batchDeleting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Trash2 className="h-3 w-3" />
          )}
          Delete {selectedCount}
        </button>
      )}
    </div>
  );
}
