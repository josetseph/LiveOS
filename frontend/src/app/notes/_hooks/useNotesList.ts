"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { api } from "@/lib/api";
import type { Note } from "@/lib/types";
import { isActiveProcessingNote } from "../_lib/processing-status";
import type { ProcessedFilter, VaultFileEntry } from "../_lib/types";

export type VaultListing = {
  folders: string[];
  attachments: VaultFileEntry[];
  media_files: VaultFileEntry[];
  vault_name?: string;
};

type UseNotesListArgs = {
  currentKB: string;
  isHydrated: boolean;
  syncSelectedNoteFromList: (data: Note[]) => void;
  setIngestingNoteIds: Dispatch<SetStateAction<Set<string>>>;
  onVaultListing: (listing: VaultListing) => void;
  clearSelectionForKBSwitch: () => void;
};

export function useNotesList({
  currentKB,
  isHydrated,
  syncSelectedNoteFromList,
  setIngestingNoteIds,
  onVaultListing,
  clearSelectionForKBSwitch,
}: UseNotesListArgs) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [processedFilter, setProcessedFilter] =
    useState<ProcessedFilter>("all");
  const [isLoading, setIsLoading] = useState(false);
  const searchTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const fetchNotesRequestRef = useRef(0);
  const prevKBRef = useRef(currentKB);

  const fetchNotes = useCallback(
    async (search?: string, filter?: ProcessedFilter) => {
      const requestId = ++fetchNotesRequestRef.current;
      try {
        setIsLoading(true);
        let processed: boolean | undefined;
        let failed: boolean | undefined;
        if (filter === "ingested") {
          processed = true;
        } else if (filter === "saved") {
          processed = false;
          failed = false;
        } else if (filter === "failed") {
          failed = true;
        } else if (filter === "ingesting") {
          // fetch unprocessed+non-failed candidates; client-side filtered below
          processed = false;
          failed = false;
        }
        // "all" → no filters
        const data = await api.getNotes(search, processed, failed, currentKB);
        if (requestId !== fetchNotesRequestRef.current) return;
        setNotes(data);
        syncSelectedNoteFromList(data);
        try {
          const folderRes = await api.listVaultFolders(currentKB);
          if (requestId === fetchNotesRequestRef.current) {
            onVaultListing({
              folders: folderRes.folders || [],
              attachments: folderRes.attachments || [],
              media_files: folderRes.media_files || [],
              vault_name: folderRes.vault_name,
            });
          }
        } catch {
          /* folders optional */
        }
        // Only keep polling notes the user already queued for ingest — never
        // start "ingesting" tracking from autosave / vault-watcher markers.
        setIngestingNoteIds((prev) => {
          const next = new Set<string>();
          for (const id of prev) {
            const note = data.find((n: Note) => n.id === id);
            if (note && isActiveProcessingNote(note)) next.add(id);
          }
          return next;
        });
      } catch (error) {
        console.error("Error fetching notes:", error);
      } finally {
        if (requestId === fetchNotesRequestRef.current) {
          setIsLoading(false);
        }
      }
    },
    [
      currentKB,
      syncSelectedNoteFromList,
      onVaultListing,
      setIngestingNoteIds,
    ],
  );

  // Fetch notes once KB context is hydrated from localStorage, and re-fetch on KB switch
  useEffect(() => {
    if (!isHydrated) return;
    if (prevKBRef.current !== currentKB) {
      prevKBRef.current = currentKB;
      // Don't keep editing another vault's note after switching KBs.
      clearSelectionForKBSwitch();
    }
    fetchNotes(undefined, processedFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentKB, isHydrated]);

  // Debounced search and filter — skip until localStorage is hydrated so we
  // never fetch with the pre-hydration default KB slug.
  useEffect(() => {
    if (!isHydrated) return;

    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    searchTimeoutRef.current = setTimeout(() => {
      fetchNotes(searchQuery, processedFilter);
    }, 300);

    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
    };
    // fetchNotes reads currentKB; KB changes are handled by the dedicated effect above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, processedFilter, isHydrated]);

  return {
    notes,
    setNotes,
    searchQuery,
    setSearchQuery,
    processedFilter,
    setProcessedFilter,
    isLoading,
    fetchNotes,
  };
}
