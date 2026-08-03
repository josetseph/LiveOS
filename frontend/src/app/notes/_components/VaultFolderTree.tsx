"use client";

import type { DragEvent } from "react";
import {
  ChevronRight,
  FileText,
  Folder,
  FolderPlus,
  Paperclip,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Note } from "@/lib/types";
import { buildFolderTree } from "../_lib/folder-tree";
import type { FolderTreeNode, VaultFileEntry } from "../_lib/types";
import { NoteStatusDot } from "./NoteStatusBadge";
import { VaultFileRow } from "./VaultFileRow";

type VaultFolderTreeProps = {
  notes: Note[];
  vaultFolders: string[];
  vaultName: string;
  mediaFiles: VaultFileEntry[];
  attachmentFiles: VaultFileEntry[];
  collapsedFolders: Set<string>;
  selectedFolder: string;
  selectedNoteId: string | null;
  selectedNoteIds: Set<string>;
  dragNoteId: string | null;
  dragFileRel: string | null;
  onToggleFolder: (path: string) => void;
  onSelectFolder: (path: string) => void;
  onNoteSelect: (note: Note) => void;
  onToggleNoteSelected: (noteId: string) => void;
  onCreateNote: (folderPath: string) => void;
  onOpenFolderDialog: (parent: string) => void;
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

export function VaultFolderTree({
  notes,
  vaultFolders,
  vaultName,
  mediaFiles,
  attachmentFiles,
  collapsedFolders,
  selectedFolder,
  selectedNoteId,
  selectedNoteIds,
  dragNoteId,
  dragFileRel,
  onToggleFolder,
  onSelectFolder,
  onNoteSelect,
  onToggleNoteSelected,
  onCreateNote,
  onOpenFolderDialog,
  onMoveNoteToFolder,
  onMoveVaultFile,
  onDragNoteStart,
  onDragNoteEnd,
  onDragFileStart,
  onDragFileEnd,
  onFileClick,
  onRenameFile,
  onDeleteVaultAttachment,
}: VaultFolderTreeProps) {
  const noteFolders = vaultFolders.filter(
    (f) => f !== "attachments" && !f.startsWith("attachments/"),
  );
  const tree = buildFolderTree(notes, noteFolders);
  const attachmentsOpen = !collapsedFolders.has("attachments");

  const mediaByFolder = new Map<string, VaultFileEntry[]>();
  const rootMedia: VaultFileEntry[] = [];
  for (const f of mediaFiles) {
    const rel = f.rel_path.replace(/\\/g, "/");
    if (rel === "attachments" || rel.startsWith("attachments/")) {
      continue;
    }
    const slash = rel.lastIndexOf("/");
    if (slash < 0) {
      rootMedia.push(f);
      continue;
    }
    const parent = rel.slice(0, slash);
    const list = mediaByFolder.get(parent) || [];
    list.push(f);
    mediaByFolder.set(parent, list);
  }

  const acceptVaultDrop = (e: DragEvent, folderPath: string) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    const noteId = e.dataTransfer.getData("text/note-id") || dragNoteId;
    const fileRel = e.dataTransfer.getData("text/vault-file") || dragFileRel;
    onDragNoteEnd();
    onDragFileEnd();
    if (noteId) void onMoveNoteToFolder(noteId, folderPath);
    else if (fileRel) void onMoveVaultFile(fileRel, folderPath);
  };

  const allowVaultDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
  };

  const folderActionButtons = (folderPath: string) => (
    <div className="flex shrink-0 items-center gap-0.5">
      <button
        type="button"
        title="New folder"
        onClick={(e) => {
          e.stopPropagation();
          onOpenFolderDialog(folderPath);
        }}
        className="flex h-6 w-6 items-center justify-center rounded text-white/45 hover:bg-white/10 hover:text-white/90"
      >
        <FolderPlus className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        title="New note"
        onClick={(e) => {
          e.stopPropagation();
          onSelectFolder(folderPath);
          void onCreateNote(folderPath);
        }}
        className="flex h-6 w-6 items-center justify-center rounded text-white/45 hover:bg-white/10 hover:text-white/90"
      >
        <Plus className="h-3.5 w-3.5" />
      </button>
    </div>
  );

  const renderNode = (node: FolderTreeNode, depth: number) => {
    const isFolder = !node.note;
    const isOpen = !collapsedFolders.has(node.path);

    if (isFolder) {
      const isSelected = selectedFolder === node.path;
      const folderMedia = mediaByFolder.get(node.path) || [];
      return (
        <div
          key={node.path}
          className={cn(
            "relative group/folder rounded-md",
            (dragNoteId || dragFileRel) && "ring-1 ring-teal-500/25",
          )}
          onDragOver={allowVaultDragOver}
          onDrop={(e) => acceptVaultDrop(e, node.path)}
        >
          {depth > 0 && (
            <div
              className="absolute bottom-0 top-0 w-px bg-white/10"
              style={{ left: 10 + (depth - 1) * 12 }}
            />
          )}
          <div
            className={cn(
              "flex w-full items-center gap-0.5 rounded-md pr-1 text-[13px]",
              isSelected
                ? "bg-teal-500/15 text-teal-100"
                : "text-white/65 hover:bg-white/5 hover:text-white/90",
            )}
            style={{ paddingLeft: 6 + depth * 12 }}
          >
            <button
              type="button"
              onClick={() => {
                onToggleFolder(node.path);
                onSelectFolder(node.path);
              }}
              className="flex min-w-0 flex-1 items-center gap-1 px-1.5 py-1 text-left"
            >
              <ChevronRight
                className={cn(
                  "h-3 w-3 shrink-0 text-white/40 transition-transform",
                  isOpen && "rotate-90",
                )}
              />
              <Folder className="h-3.5 w-3.5 shrink-0 text-amber-300/80" />
              <span className="truncate font-medium">{node.name}</span>
            </button>
            {folderActionButtons(node.path)}
          </div>
          {isOpen && (
            <>
              {node.children.map((child) => renderNode(child, depth + 1))}
              {folderMedia.map((f) => (
                <VaultFileRow
                  key={f.rel_path}
                  name={f.name}
                  relPath={f.rel_path}
                  depth={depth + 1}
                  isDragging={dragFileRel === f.rel_path}
                  onDragStart={onDragFileStart}
                  onDragEnd={onDragFileEnd}
                  onClick={onFileClick}
                  onRename={onRenameFile}
                  onDelete={onDeleteVaultAttachment}
                />
              ))}
            </>
          )}
        </div>
      );
    }

    const note = node.note!;
    const parentFolder = node.path.includes("/")
      ? node.path.slice(0, node.path.lastIndexOf("/"))
      : "";
    const isChecked = selectedNoteIds.has(note.id);
    return (
      <div
        key={note.id}
        draggable
        onDragStart={(e) => {
          onDragNoteStart(note.id);
          e.dataTransfer.setData("text/note-id", note.id);
          e.dataTransfer.effectAllowed = "move";
        }}
        onDragEnd={onDragNoteEnd}
        onDragOver={allowVaultDragOver}
        onDrop={(e) => acceptVaultDrop(e, parentFolder)}
        className={cn(
          "relative flex w-full items-center gap-1 rounded-md px-1 py-1 text-left text-[13px] transition-colors",
          selectedNoteId === note.id
            ? "bg-white/10 text-white"
            : "text-white/70 hover:bg-white/5 hover:text-white/90",
          dragNoteId === note.id && "opacity-50",
          isChecked && "ring-1 ring-red-400/30",
        )}
        style={{ paddingLeft: 10 + depth * 12 }}
      >
        <input
          type="checkbox"
          checked={isChecked}
          onChange={() => onToggleNoteSelected(note.id)}
          onClick={(e) => e.stopPropagation()}
          className="h-3.5 w-3.5 shrink-0 rounded border-white/30 bg-black/40"
          aria-label={`Select ${note.title || "note"}`}
        />
        <button
          type="button"
          onClick={() => onNoteSelect(note)}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        >
          <FileText className="h-3.5 w-3.5 shrink-0 text-white/35" />
          <span className="min-w-0 flex-1 truncate">
            {note.title || node.name || "Untitled"}
          </span>
          <span className="shrink-0">
            <NoteStatusDot note={note} />
          </span>
        </button>
      </div>
    );
  };

  return (
    <>
      <div
        className={cn(
          "group/folder mb-1 rounded-md",
          (dragNoteId || dragFileRel) && "ring-1 ring-teal-500/25",
        )}
        onDragOver={allowVaultDragOver}
        onDrop={(e) => acceptVaultDrop(e, "")}
      >
        <div
          className={cn(
            "flex w-full items-center gap-0.5 rounded-md pr-1 text-[12px]",
            selectedFolder === ""
              ? "bg-teal-500/15 text-teal-200"
              : "text-white/55 hover:bg-white/5 hover:text-white/80",
          )}
        >
          <button
            type="button"
            onClick={() => onSelectFolder("")}
            className="flex min-w-0 flex-1 items-center gap-1.5 px-2 py-1 text-left"
          >
            <Folder className="h-3.5 w-3.5 shrink-0 text-teal-300/90" />
            <span className="truncate font-medium">{vaultName}</span>
            {selectedFolder === "" && (
              <span className="ml-1 truncate text-[10px] text-teal-300/70">
                new notes here
              </span>
            )}
          </button>
          {folderActionButtons("")}
        </div>
      </div>
      <div
        className="min-h-[40px]"
        onDragOver={allowVaultDragOver}
        onDrop={(e) => {
          acceptVaultDrop(e, "");
        }}
      >
        {tree.map((n) => renderNode(n, 0))}
        {rootMedia.map((f) => (
          <VaultFileRow
            key={f.rel_path}
            name={f.name}
            relPath={f.rel_path}
            depth={0}
            isDragging={dragFileRel === f.rel_path}
            onDragStart={onDragFileStart}
            onDragEnd={onDragFileEnd}
            onClick={onFileClick}
            onRename={onRenameFile}
            onDelete={onDeleteVaultAttachment}
          />
        ))}
      </div>

      <div
        className={cn(
          "group/folder mt-2 border-t border-white/5 pt-2",
          (dragNoteId || dragFileRel) && "ring-1 ring-sky-500/25 rounded-md",
        )}
        onDragOver={allowVaultDragOver}
        onDrop={(e) => acceptVaultDrop(e, "attachments")}
      >
        <div className="flex w-full items-center gap-0.5 rounded-md pr-1 text-[13px] text-white/65 hover:bg-white/5 hover:text-white/90">
          <button
            type="button"
            onClick={() => onToggleFolder("attachments")}
            className="flex min-w-0 flex-1 items-center gap-1 px-1.5 py-1 text-left"
          >
            <ChevronRight
              className={cn(
                "h-3 w-3 shrink-0 text-white/40 transition-transform",
                attachmentsOpen && "rotate-90",
              )}
            />
            <Paperclip className="h-3.5 w-3.5 shrink-0 text-sky-300/80" />
            <span className="truncate font-medium">Attachments</span>
            <span className="text-[10px] text-white/35">
              {attachmentFiles.length}
            </span>
          </button>
        </div>
        {attachmentsOpen &&
          (attachmentFiles.length === 0 ? (
            <p className="px-8 py-1 text-[11px] text-white/30">
              Default upload folder — drag files into other folders anytime
            </p>
          ) : (
            attachmentFiles.map((f) => (
              <VaultFileRow
                key={f.rel_path}
                name={f.name}
                relPath={f.rel_path}
                depth={0}
                isDragging={dragFileRel === f.rel_path}
                onDragStart={onDragFileStart}
                onDragEnd={onDragFileEnd}
                onClick={onFileClick}
                onRename={onRenameFile}
                onDelete={onDeleteVaultAttachment}
              />
            ))
          ))}
      </div>
    </>
  );
}
