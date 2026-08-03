"use client";

import { cn } from "@/lib/utils";
import type { ProcessedFilter } from "../_lib/types";

type NotesFilterBarProps = {
  processedFilter: ProcessedFilter;
  onFilterChange: (filter: ProcessedFilter) => void;
};

export function NotesFilterBar({
  processedFilter,
  onFilterChange,
}: NotesFilterBarProps) {
  return (
    <div className="mt-2 space-y-1 px-2">
      <div className="flex gap-1">
        <button
          onClick={() => onFilterChange("all")}
          className={cn(
            "flex-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-all",
            processedFilter === "all"
              ? "bg-white/10 text-white border border-white/20"
              : "bg-white/5 text-white/60 border border-transparent hover:bg-white/10",
          )}
        >
          All
        </button>
        <button
          onClick={() => onFilterChange("ingested")}
          className={cn(
            "flex-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-all",
            processedFilter === "ingested"
              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
              : "bg-white/5 text-white/60 border border-transparent hover:bg-white/10",
          )}
        >
          Ingested
        </button>
        <button
          onClick={() => onFilterChange("saved")}
          className={cn(
            "flex-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-all",
            processedFilter === "saved"
              ? "bg-white/10 text-white/80 border border-white/20"
              : "bg-white/5 text-white/60 border border-transparent hover:bg-white/10",
          )}
        >
          Saved
        </button>
      </div>
      <div className="flex gap-1">
        <button
          onClick={() => onFilterChange("ingesting")}
          className={cn(
            "flex-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-all",
            processedFilter === "ingesting"
              ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
              : "bg-white/5 text-white/60 border border-transparent hover:bg-white/10",
          )}
        >
          Ingesting
        </button>
        <button
          onClick={() => onFilterChange("failed")}
          className={cn(
            "flex-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-all",
            processedFilter === "failed"
              ? "bg-red-500/20 text-red-400 border border-red-500/30"
              : "bg-white/5 text-white/60 border border-transparent hover:bg-white/10",
          )}
        >
          Failed
        </button>
      </div>
    </div>
  );
}
