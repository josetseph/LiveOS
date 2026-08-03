"use client";

import type { RenameDialogState } from "../_lib/types";

type RenameDialogProps = {
  renameDialog: RenameDialogState;
  onNameChange: (name: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
};

export function RenameDialog({
  renameDialog,
  onNameChange,
  onSubmit,
  onCancel,
}: RenameDialogProps) {
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-sm rounded-2xl border border-white/10 bg-black/95 p-5 shadow-2xl">
        <h2 className="mb-1 text-lg font-semibold text-white">Rename file</h2>
        <p className="mb-4 truncate text-xs text-white/45">
          {renameDialog.rel_path}
        </p>
        <input
          autoFocus
          value={renameDialog.name}
          onChange={(e) => onNameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void onSubmit();
            if (e.key === "Escape") onCancel();
          }}
          placeholder="File name"
          className="mb-4 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-teal-500/40"
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg px-3 py-2 text-sm text-white/60 hover:bg-white/10"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void onSubmit()}
            className="rounded-lg bg-teal-500/25 px-3 py-2 text-sm font-medium text-teal-200 hover:bg-teal-500/35"
          >
            Rename
          </button>
        </div>
      </div>
    </div>
  );
}
