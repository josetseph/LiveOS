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
import { lastNoteStorageKey } from "../_lib/storage-keys";

type UseNoteSelectionArgs = {
  currentKB: string;
  setNotes: Dispatch<SetStateAction<Note[]>>;
};

export function useNoteSelection({ currentKB, setNotes }: UseNoteSelectionArgs) {
  const [selectedNote, setSelectedNote] = useState<Note | null>(null);
  const contentBeforeEditRef = useRef<string>("");
  const titleBeforeEditRef = useRef<string>("");
  const selectedNoteRef = useRef<Note | null>(null);

  useEffect(() => {
    selectedNoteRef.current = selectedNote;
  }, [selectedNote]);

  const syncSelectedNoteFromList = useCallback((data: Note[]) => {
    setSelectedNote((prev) => {
      if (!prev) return null;
      const fresh = data.find((note) => note.id === prev.id);
      if (!fresh) return prev;

      const hasUnsavedEdits =
        prev.content !== contentBeforeEditRef.current ||
        (prev.title || "") !== titleBeforeEditRef.current;
      if (hasUnsavedEdits) {
        return { ...fresh, content: prev.content, title: prev.title };
      }

      // Ignore stale list responses that predate the last successful save.
      if (fresh.content !== contentBeforeEditRef.current) {
        return { ...fresh, content: prev.content, title: prev.title };
      }

      contentBeforeEditRef.current = fresh.content;
      titleBeforeEditRef.current = fresh.title || "";
      return fresh;
    });
  }, []);

  const patchLocalNote = useCallback(
    (note: Note) => {
      setNotes((prev) => prev.map((n) => (n.id === note.id ? note : n)));
      setSelectedNote((prev) => (prev?.id === note.id ? note : prev));
    },
    [setNotes],
  );

  /** Load a note by id and make it the active selection (used by graph → notes, restore). */
  const openNoteById = useCallback(
    async (noteId: string) => {
      try {
        const fresh = await api.getNote(noteId, currentKB);
        if (!fresh) return;
        sessionStorage.setItem(lastNoteStorageKey(currentKB), fresh.id);
        contentBeforeEditRef.current = fresh.content;
        titleBeforeEditRef.current = fresh.title || "";
        setNotes((prev) =>
          prev.some((n) => n.id === fresh.id)
            ? prev.map((n) => (n.id === fresh.id ? fresh : n))
            : prev,
        );
        setSelectedNote(fresh);
      } catch (error) {
        console.error("Error opening note:", error);
      }
    },
    [currentKB, setNotes],
  );

  const refreshSelectedNote = useCallback(
    async (noteId: string) => {
      try {
        const fresh = await api.getNote(noteId, currentKB);
        if (!fresh) return;
        contentBeforeEditRef.current = fresh.content;
        titleBeforeEditRef.current = fresh.title || "";
        // Always select when nothing is open; otherwise only patch the matching note.
        setNotes((prev) =>
          prev.some((n) => n.id === fresh.id)
            ? prev.map((n) => (n.id === fresh.id ? fresh : n))
            : prev,
        );
        setSelectedNote((prev) =>
          !prev || prev.id === fresh.id ? fresh : prev,
        );
      } catch (error) {
        console.error("Error refreshing note:", error);
      }
    },
    [currentKB, setNotes],
  );

  const clearSelectionForKBSwitch = useCallback(() => {
    setSelectedNote(null);
    contentBeforeEditRef.current = "";
    titleBeforeEditRef.current = "";
  }, []);

  const handleContentChange = useCallback(
    (content: string) => {
      setSelectedNote((prev) => {
        if (!prev) return null;
        const updatedNote = { ...prev, content };
        setNotes((notes) =>
          notes.map((note) =>
            note.id === updatedNote.id ? updatedNote : note,
          ),
        );
        return updatedNote;
      });
    },
    [setNotes],
  );

  const handleTitleChange = useCallback(
    (title: string) => {
      setSelectedNote((prev) => {
        if (!prev) return null;
        const updatedNote = { ...prev, title };
        setNotes((notes) =>
          notes.map((note) =>
            note.id === updatedNote.id ? updatedNote : note,
          ),
        );
        return updatedNote;
      });
    },
    [setNotes],
  );

  return {
    selectedNote,
    setSelectedNote,
    contentBeforeEditRef,
    titleBeforeEditRef,
    selectedNoteRef,
    syncSelectedNoteFromList,
    patchLocalNote,
    openNoteById,
    refreshSelectedNote,
    clearSelectionForKBSwitch,
    handleContentChange,
    handleTitleChange,
  };
}

export type NoteSelectionApi = ReturnType<typeof useNoteSelection>;

type UseNoteSelectHandlerArgs = {
  currentKB: string;
  selectedNote: Note | null;
  contentBeforeEditRef: MutableRefObject<string>;
  titleBeforeEditRef: MutableRefObject<string>;
  handleSaveNote: (note: Note) => Promise<void>;
  setSelectedNote: Dispatch<SetStateAction<Note | null>>;
};

/** Select handler depends on autosave — kept separate to avoid circular hook init. */
export function useNoteSelectHandler({
  currentKB,
  selectedNote,
  contentBeforeEditRef,
  titleBeforeEditRef,
  handleSaveNote,
  setSelectedNote,
}: UseNoteSelectHandlerArgs) {
  const handleNoteSelect = useCallback(
    async (note: Note) => {
      // Save previous note if it has changes
      if (
        selectedNote &&
        contentBeforeEditRef.current !== selectedNote.content
      ) {
        await handleSaveNote(selectedNote);
      }

      try {
        const fresh = await api.getNote(note.id, currentKB);
        const nextNote = fresh ?? note;
        sessionStorage.setItem(lastNoteStorageKey(currentKB), nextNote.id);
        setSelectedNote(nextNote);
        contentBeforeEditRef.current = nextNote.content;
        titleBeforeEditRef.current = nextNote.title || "";
      } catch (error) {
        console.error("Error loading note:", error);
        sessionStorage.setItem(lastNoteStorageKey(currentKB), note.id);
        setSelectedNote(note);
        contentBeforeEditRef.current = note.content;
        titleBeforeEditRef.current = note.title || "";
      }
    },
    [
      currentKB,
      selectedNote,
      contentBeforeEditRef,
      titleBeforeEditRef,
      handleSaveNote,
      setSelectedNote,
    ],
  );

  return { handleNoteSelect };
}
