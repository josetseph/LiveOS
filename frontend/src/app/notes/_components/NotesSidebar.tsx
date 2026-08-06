"use client";

import { useRef } from "react";
import {
  FolderPlus,
  Loader2,
  Plus,
  RotateCcw,
  Search,
} from "lucide-react";
import type { Note } from "@/lib/types";
import { isActiveProcessingNote } from "../_lib/processing-status";
import type { ProcessedFilter, VaultFileEntry } from "../_lib/types";
import { NotesBatchBar } from "./NotesBatchBar";
import { NotesEmptyState } from "./NotesEmptyState";
import { NotesFilterBar } from "./NotesFilterBar";
import { VaultFolderTree } from "./VaultFolderTree";

type NotesSidebarProps = {
  currentKB: string;
  currentKBName: string;
  notes: Note[];
  searchQuery: string;
  processedFilter: ProcessedFilter;
  isLoading: boolean;
  isSaving: boolean;
  selectedFolder: string;
  vaultName: string;
  vaultFolders: string[];
  mediaFiles: VaultFileEntry[];
  attachmentFiles: VaultFileEntry[];
  collapsedFolders: Set<string>;
  selectedNoteId: string | null;
  selectedNoteIds: Set<string>;
  batchDeleting: boolean;
  dragNoteId: string | null;
  dragFileRel: string | null;
  onSearchChange: (query: string) => void;
  onFilterChange: (filter: ProcessedFilter) => void;
  onReingestVault: () => void;
  onOpenFolderDialog: (parent: string) => void;
  onCreateNote: (folderOverride?: string) => void;
  onToggleSelectAll: () => void;
  onBatchDelete: () => void;
  onToggleFolder: (path: string) => void;
  onSelectFolder: (path: string) => void;
  onNoteSelect: (note: Note) => void;
  onToggleNoteSelected: (noteId: string) => void;
  onMoveNoteToFolder: (noteId: string, folder: string) => void;
  onMoveVaultFile: (fromRel: string, folder: string) => void;
  onDragNoteStart: (noteId: string) => void;
  onDragNoteEnd: () => void;
  onDragFileStart: (relPath: string) => void;
  onDragFileEnd: () => void;
  onFileClick: (relPath: string, name: string) => void;
  onRenameFile: (relPath: string) => void;
  onDeleteVaultAttachment: (relPath: string, name: string) => void;
};

export function NotesSidebar({
  currentKB,
  currentKBName,
  notes,
  searchQuery,
  processedFilter,
  isLoading,
  isSaving,
  selectedFolder,
  vaultName,
  vaultFolders,
  mediaFiles,
  attachmentFiles,
  collapsedFolders,
  selectedNoteId,
  selectedNoteIds,
  batchDeleting,
  dragNoteId,
  dragFileRel,
  onSearchChange,
  onFilterChange,
  onReingestVault,
  onOpenFolderDialog,
  onCreateNote,
  onToggleSelectAll,
  onBatchDelete,
  onToggleFolder,
  onSelectFolder,
  onNoteSelect,
  onToggleNoteSelected,
  onMoveNoteToFolder,
  onMoveVaultFile,
  onDragNoteStart,
  onDragNoteEnd,
  onDragFileStart,
  onDragFileEnd,
  onFileClick,
  onRenameFile,
  onDeleteVaultAttachment,
}: NotesSidebarProps) {
  const visibleNotes =
    processedFilter === "ingesting"
      ? notes.filter(isActiveProcessingNote)
      : notes;
  const treeScrollRef = useRef<HTMLDivElement>(null);

  return (
    <div className="relative z-10 flex w-56 shrink-0 flex-col border-r border-white/10 bg-black/50 backdrop-blur-xl sm:w-64 md:w-72 lg:w-80">
      <div className="border-b border-white/10 p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">Notes</h1>
            {currentKB !== "default" && (
              <p className="text-[10px] text-purple-400 font-medium mt-0.5">
                KB: {currentKBName}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              title="Re-ingest entire vault"
              onClick={() => void onReingestVault()}
              className="flex h-10 items-center justify-center rounded-xl border border-white/10 bg-white/5 px-2 text-white/60 transition hover:bg-white/10 hover:text-white"
            >
              <RotateCcw className="h-4 w-4" />
            </button>
            <button
              type="button"
              title={
                selectedFolder
                  ? `New folder under ${selectedFolder}`
                  : "New folder"
              }
              onClick={() => onOpenFolderDialog(selectedFolder)}
              className="flex h-10 items-center justify-center rounded-xl border border-white/10 bg-white/5 px-2 text-white/60 transition hover:bg-white/10 hover:text-white"
            >
              <FolderPlus className="h-4 w-4" />
            </button>
            <button
              onClick={() => void onCreateNote()}
              disabled={isSaving}
              title={
                selectedFolder
                  ? `New note in ${selectedFolder}`
                  : "New note (vault root)"
              }
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-linear-to-br from-purple-500 to-pink-500 text-white transition-all hover:scale-105 disabled:opacity-50"
            >
              {isSaving ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Plus className="h-5 w-5" />
              )}
            </button>
          </div>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            type="text"
            placeholder="Search notes..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full rounded-xl border border-white/10 bg-white/5 py-2 pl-10 pr-4 text-sm text-white placeholder-white/40 backdrop-blur-xl focus:border-purple-500/50 focus:outline-none"
          />
        </div>

        <NotesFilterBar
          processedFilter={processedFilter}
          onFilterChange={onFilterChange}
        />

        <NotesBatchBar
          noteCount={notes.length}
          selectedCount={selectedNoteIds.size}
          batchDeleting={batchDeleting}
          onToggleSelectAll={onToggleSelectAll}
          onBatchDelete={onBatchDelete}
        />
      </div>

      <div ref={treeScrollRef} className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-white/40" />
          </div>
        ) : notes.length === 0 && vaultFolders.length === 0 ? (
          <NotesEmptyState variant="sidebar" searchQuery={searchQuery} />
        ) : (
          <div className="p-2">
            <VaultFolderTree
              notes={visibleNotes}
              scrollRef={treeScrollRef}
              vaultFolders={vaultFolders}
              vaultName={vaultName}
              mediaFiles={mediaFiles}
              attachmentFiles={attachmentFiles}
              collapsedFolders={collapsedFolders}
              selectedFolder={selectedFolder}
              selectedNoteId={selectedNoteId}
              selectedNoteIds={selectedNoteIds}
              dragNoteId={dragNoteId}
              dragFileRel={dragFileRel}
              onToggleFolder={onToggleFolder}
              onSelectFolder={onSelectFolder}
              onNoteSelect={onNoteSelect}
              onToggleNoteSelected={onToggleNoteSelected}
              onCreateNote={onCreateNote}
              onOpenFolderDialog={onOpenFolderDialog}
              onMoveNoteToFolder={onMoveNoteToFolder}
              onMoveVaultFile={onMoveVaultFile}
              onDragNoteStart={onDragNoteStart}
              onDragNoteEnd={onDragNoteEnd}
              onDragFileStart={onDragFileStart}
              onDragFileEnd={onDragFileEnd}
              onFileClick={onFileClick}
              onRenameFile={onRenameFile}
              onDeleteVaultAttachment={onDeleteVaultAttachment}
            />
          </div>
        )}
      </div>

      <div className="border-t border-white/10 p-3">
        <p className="text-xs text-white/40 text-center">
          {processedFilter === "ingesting"
            ? `${notes.filter(isActiveProcessingNote).length} ingesting`
            : `${notes.length} ${notes.length === 1 ? "note" : "notes"}`}
          {selectedFolder ? ` · ${selectedFolder}` : ` · ${vaultName}`}
        </p>
      </div>
    </div>
  );
}
