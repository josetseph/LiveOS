"use client";

import { useCallback, useState } from "react";
import type { Note } from "@/lib/types";
import { resolveNoteByWikilink } from "../_lib/wikilinks";
import type { WikilinkPreviewState } from "../_lib/types";

type UseWikilinkPreviewArgs = {
  notes: Note[];
  onNoteSelect: (note: Note) => void;
};

export function useWikilinkPreview({
  notes,
  onNoteSelect,
}: UseWikilinkPreviewArgs) {
  const [wikilinkPreview, setWikilinkPreview] =
    useState<WikilinkPreviewState | null>(null);

  const handleWikilinkClick = useCallback(
    (target: string) => {
      const match = resolveNoteByWikilink(notes, target);
      if (match) {
        void onNoteSelect(match);
      }
    },
    [notes, onNoteSelect],
  );

  const handleWikilinkHover = useCallback(
    (target: string, rect: DOMRect) => {
      const match = resolveNoteByWikilink(notes, target);
      setWikilinkPreview({
        title: match?.title || target,
        content: match?.content || "",
        x: Math.min(rect.left, window.innerWidth - 340),
        y: Math.min(rect.bottom + 8, window.innerHeight - 220),
        missing: !match,
      });
    },
    [notes],
  );

  const handleWikilinkLeave = useCallback(() => {
    setWikilinkPreview(null);
  }, []);

  return {
    wikilinkPreview,
    handleWikilinkClick,
    handleWikilinkHover,
    handleWikilinkLeave,
  };
}
