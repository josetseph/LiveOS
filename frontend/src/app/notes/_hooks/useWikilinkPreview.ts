"use client";

import { useCallback, useMemo, useState } from "react";
import type { Note } from "@/lib/types";
import { WikilinkResolver } from "../_lib/wikilinks";
import type { WikilinkPreviewState } from "../_lib/types";

type UseWikilinkPreviewArgs = {
  notes: Note[];
  onNoteSelect: (note: Note) => void;
  sourceNote?: Note | null;
};

export function useWikilinkPreview({
  notes,
  onNoteSelect,
  sourceNote,
}: UseWikilinkPreviewArgs) {
  const [wikilinkPreview, setWikilinkPreview] =
    useState<WikilinkPreviewState | null>(null);

  // Index once per notes list — hover fires often and must not re-scan the vault.
  const resolver = useMemo(() => new WikilinkResolver(notes), [notes]);

  const handleWikilinkClick = useCallback(
    (target: string) => {
      const match = resolver.resolve(target, sourceNote);
      if (match) {
        void onNoteSelect(match);
      }
    },
    [resolver, onNoteSelect, sourceNote],
  );

  const handleWikilinkHover = useCallback(
    (target: string, rect: DOMRect) => {
      const match = resolver.resolve(target, sourceNote);
      setWikilinkPreview({
        title: match?.title || target,
        content: match?.content || "",
        x: Math.min(rect.left, window.innerWidth - 340),
        y: Math.min(rect.bottom + 8, window.innerHeight - 220),
        missing: !match,
      });
    },
    [resolver, sourceNote],
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
