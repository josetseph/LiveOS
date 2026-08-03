"use client";

import { Paperclip, Pencil, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

type VaultFileRowProps = {
  name: string;
  relPath: string;
  depth: number;
  isDragging: boolean;
  onDragStart: (relPath: string) => void;
  onDragEnd: () => void;
  onClick: (relPath: string, name: string) => void;
  onRename: (relPath: string) => void;
  onDelete: (relPath: string, name: string) => void;
};

export function VaultFileRow({
  name,
  relPath,
  depth,
  isDragging,
  onDragStart,
  onDragEnd,
  onClick,
  onRename,
  onDelete,
}: VaultFileRowProps) {
  return (
    <div
      draggable
      onDragStart={(e) => {
        onDragStart(relPath);
        e.dataTransfer.setData("text/vault-file", relPath);
        e.dataTransfer.effectAllowed = "move";
      }}
      onDragEnd={onDragEnd}
      className={cn(
        "group/file relative flex w-full items-center gap-1 rounded-md px-1.5 py-1 text-left text-[12px] text-white/60 hover:bg-white/5 hover:text-white/85",
        isDragging && "opacity-50",
      )}
      style={{ paddingLeft: 22 + depth * 12 }}
    >
      <button
        type="button"
        onClick={() => onClick(relPath, name)}
        onDoubleClick={() => onRename(relPath)}
        className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        title={`${relPath}\nDouble-click to rename`}
      >
        <Paperclip className="h-3 w-3 shrink-0 text-white/30" />
        <span className="truncate">{name}</span>
      </button>
      <button
        type="button"
        title="Rename"
        onClick={(e) => {
          e.stopPropagation();
          onRename(relPath);
        }}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded opacity-0 hover:bg-white/10 group-hover/file:opacity-100"
      >
        <Pencil className="h-3 w-3 text-white/45" />
      </button>
      <button
        type="button"
        title="Delete"
        onClick={(e) => {
          e.stopPropagation();
          void onDelete(relPath, name);
        }}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded opacity-0 hover:bg-red-500/20 group-hover/file:opacity-100"
      >
        <Trash2 className="h-3 w-3 text-red-400/80" />
      </button>
    </div>
  );
}
