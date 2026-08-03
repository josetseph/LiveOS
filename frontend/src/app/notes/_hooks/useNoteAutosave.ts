"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import { api } from "@/lib/api";
import type { Note } from "@/lib/types";

type UseNoteAutosaveArgs = {
  selectedNote: Note | null;
  selectedNoteRef: MutableRefObject<Note | null>;
  contentBeforeEditRef: MutableRefObject<string>;
  titleBeforeEditRef: MutableRefObject<string>;
  currentKB: string;
  currentKBRef: MutableRefObject<string>;
  patchLocalNote: (note: Note) => void;
};

export function useNoteAutosave({
  selectedNote,
  selectedNoteRef,
  contentBeforeEditRef,
  titleBeforeEditRef,
  currentKB,
  currentKBRef,
  patchLocalNote,
}: UseNoteAutosaveArgs) {
  const [isSaving, setIsSaving] = useState(false);
  const autoSaveTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);

  const handleSaveNote = useCallback(
    async (note: Note) => {
      // Don't save if content hasn't changed
      if (
        !note ||
        (note.content === contentBeforeEditRef.current &&
          (note.title || "") === titleBeforeEditRef.current)
      ) {
        return;
      }

      try {
        setIsSaving(true);
        const savedNote = await api.updateNote(
          note.id,
          note.content,
          undefined,
          currentKB,
          note.title || undefined,
        );
        const nextNote = savedNote ?? note;
        contentBeforeEditRef.current = nextNote.content;
        titleBeforeEditRef.current = nextNote.title || "";
        patchLocalNote(nextNote);
      } catch (error) {
        console.error("Error saving note:", error);
      } finally {
        setIsSaving(false);
      }
    },
    [patchLocalNote, currentKB, contentBeforeEditRef, titleBeforeEditRef],
  );

  // Auto-save: Debounced save 1.5 seconds after user stops typing
  useEffect(() => {
    if (!selectedNote) return;

    // Clear any existing timeout
    if (autoSaveTimeoutRef.current) {
      clearTimeout(autoSaveTimeoutRef.current);
    }

    // Only auto-save if content has changed
    if (
      selectedNote.content !== contentBeforeEditRef.current ||
      (selectedNote.title || "") !== titleBeforeEditRef.current
    ) {
      autoSaveTimeoutRef.current = setTimeout(() => {
        handleSaveNote(selectedNote);
      }, 1500); // Save 1.5 seconds after user stops typing
    }

    return () => {
      if (autoSaveTimeoutRef.current) {
        clearTimeout(autoSaveTimeoutRef.current);
      }
    };
  }, [selectedNote, handleSaveNote, contentBeforeEditRef, titleBeforeEditRef]);

  // Flush pending edits when leaving the page.
  useEffect(() => {
    return () => {
      if (autoSaveTimeoutRef.current) {
        clearTimeout(autoSaveTimeoutRef.current);
      }
      const note = selectedNoteRef.current;
      if (
        note &&
        (note.content !== contentBeforeEditRef.current ||
          (note.title || "") !== titleBeforeEditRef.current)
      ) {
        void api
          .updateNote(
            note.id,
            note.content,
            undefined,
            currentKBRef.current,
            note.title || undefined,
          )
          .catch(() => {});
      }
    };
  }, [selectedNoteRef, contentBeforeEditRef, titleBeforeEditRef, currentKBRef]);

  // Save locally on page unload (backup)
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (
        selectedNote &&
        (contentBeforeEditRef.current !== selectedNote.content ||
          titleBeforeEditRef.current !== (selectedNote.title || ""))
      ) {
        handleSaveNote(selectedNote);
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () =>
      window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [selectedNote, handleSaveNote, contentBeforeEditRef, titleBeforeEditRef]);

  return {
    isSaving,
    setIsSaving,
    handleSaveNote,
    autoSaveTimeoutRef,
  };
}

export type NoteAutosaveApi = ReturnType<typeof useNoteAutosave> & {
  setIsSaving: Dispatch<SetStateAction<boolean>>;
};
