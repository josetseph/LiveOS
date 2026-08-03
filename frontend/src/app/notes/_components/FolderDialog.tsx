"use client";

import type { FolderDialogState } from "../_lib/types";

type FolderDialogProps = {
  folderDialog: FolderDialogState;
  vaultName: string;
  onNameChange: (name: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
};

export function FolderDialog({
  folderDialog,
  vaultName,
  onNameChange,
  onSubmit,
  onCancel,
}: FolderDialogProps) {
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-sm rounded-2xl border border-white/10 bg-black/95 p-5 shadow-2xl">
        <h2 className="mb-1 text-lg font-semibold text-white">New folder</h2>
        <p className="mb-4 text-xs text-white/45">
          {folderDialog.parent
            ? `Inside ${folderDialog.parent}`
            : `Inside ${vaultName}`}
        </p>
        <input
          autoFocus
          value={folderDialog.name}
          onChange={(e) => onNameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void onSubmit();
            if (e.key === "Escape") onCancel();
          }}
          placeholder="Folder name"
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
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
