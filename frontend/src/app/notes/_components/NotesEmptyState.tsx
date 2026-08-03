"use client";

import { FileText, Plus } from "lucide-react";

type NotesEmptyStateProps = {
  variant: "sidebar" | "editor";
  searchQuery?: string;
  isSaving?: boolean;
  onCreateNote?: () => void;
};

export function NotesEmptyState({
  variant,
  searchQuery,
  isSaving,
  onCreateNote,
}: NotesEmptyStateProps) {
  if (variant === "sidebar") {
    return (
      <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
        <FileText className="mb-2 h-8 w-8 text-white/20" />
        <p className="text-sm text-white/40">
          {searchQuery ? "No notes found" : "No notes yet"}
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <FileText className="mb-4 h-16 w-16 text-white/20" />
      <h2 className="mb-2 text-2xl font-bold text-white">No note selected</h2>
      <p className="mb-6 text-white/60">
        Select a note from the sidebar or create a new one
      </p>
      <button
        onClick={onCreateNote}
        disabled={isSaving}
        className="flex items-center gap-2 rounded-xl bg-linear-to-br from-purple-500 to-pink-500 px-6 py-3 text-white transition-all hover:scale-105 disabled:opacity-50"
      >
        <Plus className="h-5 w-5" />
        Create Note
      </button>
    </div>
  );
}
