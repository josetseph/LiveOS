"use client";

import { useState, useEffect, useCallback, useRef, type DragEvent } from "react";
import {
  Plus,
  Search,
  Trash2,
  FileText,
  Loader2,
  Mic,
  MicOff,
  Calendar,
  X,
  Database,
  RotateCcw,
  Network,
  ChevronRight,
  Folder,
  FolderPlus,
  Paperclip,
  FolderOpen,
  Pencil,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { api } from "@/lib/api";
import { cn, resolveFileUrl, encodeFileUrl, isImageUrl, isVideoUrl, isAudioUrl } from "@/lib/utils";
import { BlobMediaPlayer } from "@/components/blob-media-player";
import {
  isDesktopApp,
  revealInFolder,
  revealInFolderLabel,
} from "@/lib/desktop";
import { ShaderBackground } from "@/components/shader-background";
import { useKB } from "@/lib/kb-context";
import {
  MarkdownNoteEditor,
  type MarkdownNoteEditorHandle,
} from "@/components/markdown-editor";
import { EntityDetailPanel } from "@/components/entity-detail-panel";
import { ConnectedNotesPanel } from "@/components/connected-notes-panel";
import type { Note, FilePreview } from "@/lib/types";


type ProcessedFilter = "all" | "ingested" | "ingesting" | "saved" | "failed";

type FolderTreeNode = {
  name: string;
  path: string;
  note?: Note;
  children: FolderTreeNode[];
};

function resolveNoteByWikilink(notes: Note[], target: string): Note | undefined {
  const key = target.toLowerCase().trim().replace(/\\/g, "/");
  const base = key.split("/").pop()?.replace(/\.md$/i, "") || key;
  return notes.find((n) => {
    const title = (n.title || "").toLowerCase();
    const rel = (n.rel_path || "").replace(/\\/g, "/").toLowerCase();
    const stem = rel.split("/").pop()?.replace(/\.md$/i, "") || "";
    const withoutExt = rel.endsWith(".md") ? rel.slice(0, -3) : rel;
    return (
      title === key ||
      stem === key ||
      withoutExt === key ||
      title === base ||
      stem === base
    );
  });
}

function buildFolderTree(notes: Note[], extraFolders: string[] = []): FolderTreeNode[] {
  const root: FolderTreeNode[] = [];

  const ensureFolder = (parts: string[]): FolderTreeNode => {
    let level = root;
    let path = "";
    let node: FolderTreeNode | undefined;
    for (const part of parts) {
      path = path ? `${path}/${part}` : part;
      node = level.find((c) => c.name === part && !c.note);
      if (!node) {
        node = { name: part, path, children: [] };
        level.push(node);
      }
      level = node.children;
    }
    return node!;
  };

  for (const folder of extraFolders) {
    const parts = folder.replace(/\\/g, "/").split("/").filter(Boolean);
    if (parts.length) ensureFolder(parts);
  }

  for (const note of notes) {
    const rel = (note.rel_path || "").replace(/\\/g, "/");
    if (!rel) {
      root.push({
        name: note.title || "Untitled",
        path: note.id,
        note,
        children: [],
      });
      continue;
    }
    const parts = rel.replace(/\.md$/i, "").split("/").filter(Boolean);
    const fileName = parts.pop() || note.title || "Untitled";
    if (parts.length === 0) {
      root.push({ name: fileName, path: rel, note, children: [] });
    } else {
      const folder = ensureFolder(parts);
      folder.children.push({
        name: fileName,
        path: rel,
        note,
        children: [],
      });
    }
  }

  const sortTree = (nodes: FolderTreeNode[]) => {
    nodes.sort((a, b) => {
      const aFolder = !a.note && a.children.length > 0;
      const bFolder = !b.note && b.children.length > 0;
      if (aFolder !== bFolder) return aFolder ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const n of nodes) sortTree(n.children);
  };
  sortTree(root);
  return root;
}

function getProcessingLabel(note: Pick<Note, "processing_stage" | "processing_model">) {
  const stage = note.processing_stage || "Processing";
  return note.processing_model ? `${stage} (${note.processing_model})` : stage;
}

function isPendingReingestNote(note: Note) {
  const stage = note.processing_stage || "";
  return (
    !note.processed &&
    !note.failed &&
    (stage.includes("pending re-ingest") ||
      stage.includes("pending ingest") ||
      stage.includes("re-ingest when ready") ||
      stage.includes("Changed on disk"))
  );
}

/** True only while a user-triggered ingest pipeline is running. */
function isActiveProcessingNote(note: Note) {
  if (note.processed || note.failed) return false;
  if (isPendingReingestNote(note)) return false;
  const stage = (note.processing_stage || "").trim();
  if (!stage || stage === "Saved") return false;
  // Explicit ingest queue / pipeline stages only (never watcher / autosave markers).
  const activePrefixes = [
    "Queued for ingestion",
    "Queued for vault re-ingest",
    "Starting ingestion",
  ];
  if (activePrefixes.some((p) => stage.startsWith(p))) return true;
  // Ingestion tracker writes intermediate labels like "Extracting entities…" —
  // treat anything else non-terminal as active only if it does not look like a
  // watcher/save status.
  const nonPipeline = [
    "External",
    "Changed on disk",
    "pending",
    "Saved",
    "Ingestion complete",
    "Ingestion failed",
  ];
  if (nonPipeline.some((p) => stage.includes(p) || stage.startsWith(p))) {
    return false;
  }
  return true;
}

export default function NotesPage() {
  const { currentKB, currentKBName, isHydrated } = useKB();
  const [notes, setNotes] = useState<Note[]>([]);
  const [selectedNote, setSelectedNote] = useState<Note | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [processedFilter, setProcessedFilter] =
    useState<ProcessedFilter>("all");
  const [ingestingNoteIds, setIngestingNoteIds] = useState<Set<string>>(
    new Set(),
  );
  const [showConnectedPanel, setShowConnectedPanel] = useState(false);
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(
    () => new Set(),
  );
  /** Vault-relative folder selected for new notes / drop target ("" = root). */
  const [selectedFolder, setSelectedFolder] = useState<string>("");
  const [dragNoteId, setDragNoteId] = useState<string | null>(null);
  const [dragFileRel, setDragFileRel] = useState<string | null>(null);
  const [vaultFolders, setVaultFolders] = useState<string[]>([]);
  const [vaultName, setVaultName] = useState<string>("Vault");
  const [attachmentFiles, setAttachmentFiles] = useState<
    Array<{ name: string; rel_path: string }>
  >([]);
  const [mediaFiles, setMediaFiles] = useState<
    Array<{ name: string; rel_path: string }>
  >([]);
  const [folderDialog, setFolderDialog] = useState<{
    parent: string;
    name: string;
  } | null>(null);
  const [renameDialog, setRenameDialog] = useState<{
    rel_path: string;
    name: string;
  } | null>(null);
  const [wikilinkPreview, setWikilinkPreview] = useState<{
    title: string;
    content: string;
    x: number;
    y: number;
    missing?: boolean;
  } | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [filePreview, setFilePreview] = useState<FilePreview | null>(null);
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [pendingDateChange, setPendingDateChange] = useState<string | null>(
    null,
  );
  const [entityPanelNodeId, setEntityPanelNodeId] = useState<string | null>(
    null,
  );
  const [entityPanelName, setEntityPanelName] = useState<string | undefined>(
    undefined,
  );
  const [selectedNoteIds, setSelectedNoteIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [batchDeleting, setBatchDeleting] = useState(false);

  const handleEntityClick = useCallback(
    (nodeId: string, name: string) => {
      setEntityPanelNodeId(nodeId);
      setEntityPanelName(name);
    },
    [],
  );

  const handleWikilinkClick = useCallback(
    (target: string) => {
      const match = resolveNoteByWikilink(notes, target);
      if (match) {
        void handleNoteSelect(match);
      }
    },
    // handleNoteSelect defined below — intentional late binding via notes
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [notes],
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

  const contentBeforeEditRef = useRef<string>("");
  const titleBeforeEditRef = useRef<string>("");
  const searchTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const autoSaveTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const fetchNotesRequestRef = useRef(0);
  const selectedNoteRef = useRef<Note | null>(null);
  const editorRef = useRef<MarkdownNoteEditorHandle>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

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

  const patchLocalNote = useCallback((note: Note) => {
    setNotes((prev) => prev.map((n) => (n.id === note.id ? note : n)));
    setSelectedNote((prev) => (prev?.id === note.id ? note : prev));
  }, []);

  /** Load a note by id and make it the active selection (used by graph → notes, restore). */
  const openNoteById = useCallback(
    async (noteId: string) => {
      try {
        const fresh = await api.getNote(noteId, currentKB);
        if (!fresh) return;
        sessionStorage.setItem("orb:last-note-id", fresh.id);
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
    [currentKB],
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
    [currentKB],
  );

  // Fetch notes once KB context is hydrated from localStorage, and re-fetch on KB switch
  useEffect(() => {
    if (!isHydrated) return;
    fetchNotes(undefined, processedFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentKB, isHydrated]);

  // Open a specific note from /notes?note=<id> (e.g. Notes Graph → Open in Notes)
  // and restore last selection when landing on /notes with nothing open.
  useEffect(() => {
    if (!isHydrated) return;

    const params = new URLSearchParams(window.location.search);
    const noteParam = params.get("note");
    if (noteParam) {
      sessionStorage.setItem("orb:last-note-id", noteParam);
      void openNoteById(noteParam);
      // Drop the query so refresh doesn't fight with in-page selection changes
      window.history.replaceState({}, "", "/notes");
      return;
    }

    const restoreSelection = () => {
      const noteId =
        selectedNoteRef.current?.id ??
        sessionStorage.getItem("orb:last-note-id");
      if (!noteId) return;
      if (selectedNoteRef.current?.id === noteId) {
        void refreshSelectedNote(noteId);
      } else {
        void openNoteById(noteId);
      }
    };

    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        void fetchNotes(searchQuery, processedFilter);
        restoreSelection();
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        restoreSelection();
      }
    };

    restoreSelection();
    window.addEventListener("pageshow", handlePageShow);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("pageshow", handlePageShow);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isHydrated, currentKB, openNoteById, refreshSelectedNote]);

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

  const handleSaveNote = useCallback(async (note: Note) => {
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
  }, [patchLocalNote]);

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
  }, [selectedNote, handleSaveNote]);

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
            currentKB,
            note.title || undefined,
          )
          .catch(() => {});
      }
    };
  }, []);

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
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [selectedNote, handleSaveNote]);

  const fetchNotes = async (search?: string, filter?: ProcessedFilter) => {
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
          setVaultFolders(folderRes.folders || []);
          setAttachmentFiles(folderRes.attachments || []);
          setMediaFiles(folderRes.media_files || []);
          if (folderRes.vault_name) setVaultName(folderRes.vault_name);
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
  };

  const handleNoteSelect = async (note: Note) => {
    // Save previous note if it has changes
    if (selectedNote && contentBeforeEditRef.current !== selectedNote.content) {
      await handleSaveNote(selectedNote);
    }

    try {
      const fresh = await api.getNote(note.id, currentKB);
      const nextNote = fresh ?? note;
      sessionStorage.setItem("orb:last-note-id", nextNote.id);
      setSelectedNote(nextNote);
      contentBeforeEditRef.current = nextNote.content;
      titleBeforeEditRef.current = nextNote.title || "";
    } catch (error) {
      console.error("Error loading note:", error);
      sessionStorage.setItem("orb:last-note-id", note.id);
      setSelectedNote(note);
      contentBeforeEditRef.current = note.content;
      titleBeforeEditRef.current = note.title || "";
    }
  };

  const handleCreateNote = async (folderOverride?: string) => {
    // Save current note if it has changes
    if (
      selectedNote &&
      (contentBeforeEditRef.current !== selectedNote.content ||
        titleBeforeEditRef.current !== (selectedNote.title || ""))
    ) {
      await handleSaveNote(selectedNote);
    }

    const folder =
      typeof folderOverride === "string" ? folderOverride : selectedFolder;

    try {
      const newNote = await api.createNote(
        "",
        new Date().toISOString(),
        currentKB,
        undefined,
        folder || undefined,
      );

      await fetchNotes(searchQuery, processedFilter);
      setSelectedNote(newNote);
      contentBeforeEditRef.current = "";
      titleBeforeEditRef.current = newNote.title || "";
      if (folder) {
        setCollapsedFolders((prev) => {
          const next = new Set(prev);
          next.delete(folder);
          // also expand ancestors
          const parts = folder.split("/");
          for (let i = 1; i < parts.length; i++) {
            next.delete(parts.slice(0, i).join("/"));
          }
          return next;
        });
      }
    } catch (error) {
      console.error("Error creating note:", error);
      alert("Failed to create note. Please try again.");
    }
  };

  const handleMoveNoteToFolder = async (noteId: string, folder: string) => {
    try {
      const result = await api.moveNote(noteId, folder, currentKB);
      await fetchNotes(searchQuery, processedFilter);
      if (result?.note) {
        patchLocalNote(result.note);
      } else {
        void refreshSelectedNote(noteId);
      }
    } catch (error) {
      console.error("Error moving note:", error);
      const detail =
        error && typeof error === "object" && "response" in error
          ? (error as { response?: { data?: { detail?: string } } }).response
              ?.data?.detail
          : null;
      alert(detail || "Failed to move note.");
    }
  };

  const handleMoveVaultFile = async (fromRel: string, folder: string) => {
    const filename = fromRel.split("/").pop() || fromRel;
    const toRel = folder ? `${folder}/${filename}` : filename;
    if (toRel === fromRel) return;
    try {
      const result = await api.moveVaultFile(fromRel, toRel, currentKB);
      // Rewrite open note content if it referenced the old path
      if (selectedNote && result?.from && result?.to) {
        const oldUrl = `/vault-files/${currentKB}/${result.from}`;
        const newUrl = `/vault-files/${currentKB}/${result.to}`;
        if (
          selectedNote.content.includes(result.from) ||
          selectedNote.content.includes(oldUrl)
        ) {
          const next = selectedNote.content
            .replaceAll(oldUrl, newUrl)
            .replaceAll(result.from, result.to);
          if (next !== selectedNote.content) {
            handleContentChange(next);
          }
        }
      }
      await fetchNotes(searchQuery, processedFilter);
    } catch (error) {
      console.error("Error moving file:", error);
      const detail =
        error && typeof error === "object" && "response" in error
          ? (error as { response?: { data?: { detail?: string } } }).response
              ?.data?.detail
          : null;
      alert(detail || "Failed to move file.");
    }
  };

  const openRenameDialog = (relPath: string) => {
    setRenameDialog({
      rel_path: relPath,
      name: relPath.split("/").pop() || relPath,
    });
  };

  const submitRenameDialog = async () => {
    if (!renameDialog) return;
    const newName = renameDialog.name.trim();
    if (!newName) {
      alert("Enter a file name");
      return;
    }
    if (/[\\/]/.test(newName) || newName.includes("..")) {
      alert("File name cannot contain path separators");
      return;
    }
    const parts = renameDialog.rel_path.replace(/\\/g, "/").split("/");
    parts[parts.length - 1] = newName;
    const toRel = parts.join("/");
    if (toRel === renameDialog.rel_path) {
      setRenameDialog(null);
      return;
    }
    try {
      const result = await api.moveVaultFile(
        renameDialog.rel_path,
        toRel,
        currentKB,
      );
      setRenameDialog(null);
      if (selectedNote && result?.from && result?.to) {
        const oldUrl = `/vault-files/${currentKB}/${result.from}`;
        const newUrl = `/vault-files/${currentKB}/${result.to}`;
        if (
          selectedNote.content.includes(result.from) ||
          selectedNote.content.includes(oldUrl)
        ) {
          const next = selectedNote.content
            .replaceAll(oldUrl, newUrl)
            .replaceAll(result.from, result.to);
          if (next !== selectedNote.content) {
            handleContentChange(next);
          }
        }
      }
      await fetchNotes(searchQuery, processedFilter);
    } catch (error) {
      console.error("Error renaming file:", error);
      const detail =
        error && typeof error === "object" && "response" in error
          ? (error as { response?: { data?: { detail?: string } } }).response
              ?.data?.detail
          : null;
      alert(detail || "Failed to rename file.");
    }
  };

  const openFolderDialog = (parent: string) => {
    setSelectedFolder(parent);
    setFolderDialog({ parent, name: "" });
  };

  const submitFolderDialog = async () => {
    if (!folderDialog) return;
    const name = folderDialog.name.trim();
    if (!name) {
      alert("Enter a folder name");
      return;
    }
    if (/[\\/]/.test(name) || name.includes("..")) {
      alert("Folder name cannot contain path separators");
      return;
    }
    const path = folderDialog.parent
      ? `${folderDialog.parent}/${name}`
      : name;
    try {
      await api.mkdirVaultFolder(path, currentKB);
      setFolderDialog(null);
      setSelectedFolder(path);
      setCollapsedFolders((prev) => {
        const next = new Set(prev);
        next.delete(path);
        if (folderDialog.parent) next.delete(folderDialog.parent);
        return next;
      });
      await fetchNotes(searchQuery, processedFilter);
    } catch (err) {
      console.error(err);
      const detail =
        err && typeof err === "object" && "response" in err
          ? (err as { response?: { data?: { detail?: string } } }).response
              ?.data?.detail
          : null;
      alert(detail || "Failed to create folder");
    }
  };

  const handleIngestNote = async () => {
    if (!selectedNote || !selectedNote.content.trim()) {
      alert("Cannot ingest an empty note");
      return;
    }

    try {
      setIsSaving(true);
      if (
        selectedNote.content !== contentBeforeEditRef.current ||
        (selectedNote.title || "") !== titleBeforeEditRef.current
      ) {
        await handleSaveNote(selectedNote);
      }
      await api.ingestNote(selectedNote.id, currentKB);
      // Track as in-flight — polling will update state when done
      setIngestingNoteIds((prev) => new Set([...prev, selectedNote.id]));
      // Optimistically clear any previous failure flag and show queue status.
      const patched = {
        ...selectedNote,
        processed: false,
        failed: false,
        processing_stage: "Queued for ingestion",
        processing_model: null,
      };
      setSelectedNote(patched);
      setNotes((prev) =>
        prev.map((n) => (n.id === selectedNote.id ? patched : n)),
      );
    } catch (error) {
      console.error("Error ingesting note:", error);
      alert("Failed to ingest note. Please try again.");
    } finally {
      setIsSaving(false);
    }
  };

  // Poll status for any notes that have been queued for ingestion
  useEffect(() => {
    if (ingestingNoteIds.size === 0) return;

    const poll = async () => {
      const updates: Array<{
        id: string;
        processed: boolean;
        failed: boolean;
        processing_stage?: string | null;
        processing_model?: string | null;
      }> = [];
      const refreshedNotes: Note[] = [];
      await Promise.all(
        Array.from(ingestingNoteIds).map(async (noteId) => {
          try {
            const status = await api.getNoteStatus(noteId);
            updates.push({
              id: noteId,
              processed: status.processed,
              failed: status.failed,
              processing_stage: status.processing_stage,
              processing_model: status.processing_model,
            });
            if (status.processed || status.failed) {
              refreshedNotes.push(await api.getNote(noteId, currentKB));
            }
          } catch { }
        }),
      );
      if (updates.length === 0) return;
      const refreshedById = new Map(
        refreshedNotes.map((note) => [note.id, note]),
      );
      setIngestingNoteIds((prev) => {
        const next = new Set(prev);
        updates
          .filter((c) => c.processed || c.failed)
          .forEach((c) => next.delete(c.id));
        return next;
      });
      setNotes((prev) =>
        prev.map((n) => {
          const refreshed = refreshedById.get(n.id);
          if (refreshed) return refreshed;
          const update = updates.find((c) => c.id === n.id);
          return update
            ? {
              ...n,
              processed: update.processed,
              failed: update.failed,
              processing_stage: update.processing_stage,
              processing_model: update.processing_model,
            }
            : n;
        }),
      );
      setSelectedNote((prev) => {
        if (!prev) return null;
        const refreshed = refreshedById.get(prev.id);
        if (refreshed) {
          const hasUnsavedEdits =
            prev.content !== contentBeforeEditRef.current ||
            (prev.title || "") !== titleBeforeEditRef.current;
          if (!hasUnsavedEdits) {
            contentBeforeEditRef.current = refreshed.content;
            titleBeforeEditRef.current = refreshed.title || "";
            return refreshed;
          }
          return {
            ...refreshed,
            content: prev.content,
          };
        }
        const update = updates.find((c) => c.id === prev.id);
        return update
          ? {
            ...prev,
            processed: update.processed,
            failed: update.failed,
            processing_stage: update.processing_stage,
            processing_model: update.processing_model,
          }
          : prev;
      });
    };

    const interval = setInterval(poll, 5000);
    return () => clearInterval(interval);
  }, [ingestingNoteIds]);

  const handleContentChange = (content: string) => {
    if (!selectedNote) return;
    const updatedNote = { ...selectedNote, content };
    setSelectedNote(updatedNote);
    setNotes((prev) =>
      prev.map((note) => (note.id === updatedNote.id ? updatedNote : note)),
    );
  };

  const handleTitleChange = (title: string) => {
    if (!selectedNote) return;
    const updatedNote = { ...selectedNote, title };
    setSelectedNote(updatedNote);
    setNotes((prev) =>
      prev.map((note) => (note.id === updatedNote.id ? updatedNote : note)),
    );
  };

  const handleDeleteNote = async () => {
    if (!selectedNote) return;

    const confirmDelete = window.confirm(
      `Delete "${selectedNote.title || "Untitled"}"?\n\nThis removes it from Orb and deletes the markdown file in your vault folder.`,
    );
    if (!confirmDelete) return;

    const deletedId = selectedNote.id;
    try {
      // Stop autosave from writing the file back while we delete.
      if (autoSaveTimeoutRef.current) {
        clearTimeout(autoSaveTimeoutRef.current);
        autoSaveTimeoutRef.current = undefined;
      }
      contentBeforeEditRef.current = "";
      setSelectedNote(null);
      setNotes((prev) => prev.filter((n) => n.id !== deletedId));
      setSelectedNoteIds((prev) => {
        const next = new Set(prev);
        next.delete(deletedId);
        return next;
      });
      await api.deleteNote(deletedId, currentKB);
      await fetchNotes(searchQuery, processedFilter);
    } catch (error) {
      console.error("Error deleting note:", error);
      // DB may already be gone even if cleanup failed — refresh list.
      setSelectedNote(null);
      try {
        await fetchNotes(searchQuery, processedFilter);
      } catch {
        /* ignore */
      }
      alert(
        "Delete may have partially failed. If the note file is still in your vault folder, delete it manually, then Reload.",
      );
    }
  };

  const toggleNoteSelected = (noteId: string) => {
    setSelectedNoteIds((prev) => {
      const next = new Set(prev);
      if (next.has(noteId)) next.delete(noteId);
      else next.add(noteId);
      return next;
    });
  };

  const handleBatchDeleteNotes = async () => {
    const ids = Array.from(selectedNoteIds);
    if (ids.length === 0) return;
    if (
      !window.confirm(
        `Delete ${ids.length} selected note${ids.length === 1 ? "" : "s"}?\n\n` +
          `This removes them from Orb and deletes the markdown files in your vault.`,
      )
    ) {
      return;
    }
    setBatchDeleting(true);
    try {
      if (selectedNote && selectedNoteIds.has(selectedNote.id)) {
        if (autoSaveTimeoutRef.current) {
          clearTimeout(autoSaveTimeoutRef.current);
          autoSaveTimeoutRef.current = undefined;
        }
        contentBeforeEditRef.current = "";
        setSelectedNote(null);
      }
      const result = await api.batchDeleteNotes(ids, currentKB);
      setSelectedNoteIds(new Set());
      await fetchNotes(searchQuery, processedFilter);
      if (result.failed_count > 0) {
        alert(
          `Deleted ${result.deleted_count} note(s). ${result.failed_count} failed — check the vault and try again.`,
        );
      }
    } catch (error) {
      console.error("Batch delete failed:", error);
      alert("Batch delete failed. Refresh and try again.");
      try {
        await fetchNotes(searchQuery, processedFilter);
      } catch {
        /* ignore */
      }
    } finally {
      setBatchDeleting(false);
    }
  };

  const handleDeleteFile = async (fileUrl: string, _markdownText: string) => {
    if (!selectedNote) return;
    if (
      !confirm(
        "Delete this attachment from the vault and remove it from this note?",
      )
    ) {
      return;
    }
    try {
      // Prefer vault-relative path so nested attachments/ delete correctly
      const resolved = resolveFileUrl(fileUrl, currentKB);
      let relPath = fileUrl;
      if (resolved.startsWith("/vault-files/")) {
        const parts = resolved.split("/");
        // '', 'vault-files', kb, ...path
        relPath = parts.slice(3).map((p) => {
          try {
            return decodeURIComponent(p);
          } catch {
            return p;
          }
        }).join("/");
      } else if (fileUrl.startsWith("attachments/")) {
        relPath = fileUrl;
      } else {
        // legacy: filename only — assume attachments/
        const name = fileUrl.split("/").pop() || fileUrl;
        relPath = `attachments/${name}`;
      }

      await api.deleteVaultFile(relPath, currentKB);
      // Server already stripped markdown links across notes
      await refreshSelectedNote(selectedNote.id);
      await fetchNotes(searchQuery, processedFilter);
    } catch (error) {
      console.error("Error deleting file:", error);
      alert("Failed to delete attachment.");
    }
  };

  const handleDeleteVaultAttachment = async (relPath: string, name: string) => {
    if (
      !confirm(
        `Delete "${name}" from your vault?\n\nLinks to this file will be removed from notes.`,
      )
    ) {
      return;
    }
    try {
      const result = await api.deleteVaultFile(relPath, currentKB);
      if (selectedNote && result?.deleted) {
        const oldUrl = `/vault-files/${currentKB}/${result.deleted}`;
        if (
          selectedNote.content.includes(result.deleted) ||
          selectedNote.content.includes(oldUrl)
        ) {
          // Server already stripped note bodies on disk; refresh open note
          void refreshSelectedNote(selectedNote.id);
        }
      }
      setFilePreview((prev) =>
        prev &&
        (prev.url.includes(relPath) ||
          prev.filename === name ||
          prev.url.endsWith(name))
          ? null
          : prev,
      );
      await fetchNotes(searchQuery, processedFilter);
    } catch (error) {
      console.error("Error deleting vault file:", error);
      const detail =
        error && typeof error === "object" && "response" in error
          ? (error as { response?: { data?: { detail?: string } } }).response
              ?.data?.detail
          : null;
      alert(detail || "Failed to delete file.");
    }
  };

  const handleFileAttach = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedNote) return;

    try {
      setIsUploading(true);
      const response = await api.upload(file, currentKB);
      const linkUrl = encodeFileUrl(response.url || response.href);
      if (!linkUrl) throw new Error("Upload returned no URL");

      const lower = file.name.toLowerCase();
      const isImage =
        file.type.startsWith("image/") ||
        /\.(jpg|jpeg|png|gif|webp|svg)$/i.test(lower);

      // Images stay as markdown image embeds so the editor previews them;
      // ingestion also discovers ![alt](/vault-files/...) for Florence.
      const markdownLink = isImage
        ? `\n![${file.name}](${linkUrl})\n`
        : `\n[📎 ${file.name}](${linkUrl})\n`;
      if (editorRef.current) {
        editorRef.current.insertAtCursor(markdownLink);
      } else {
        handleContentChange((selectedNote?.content ?? "") + markdownLink);
      }
      try {
        const folderRes = await api.listVaultFolders(currentKB);
        setAttachmentFiles(folderRes.attachments || []);
        setMediaFiles(folderRes.media_files || []);
      } catch {
        /* optional */
      }
    } catch (error) {
      console.error("Error uploading file:", error);
      const detail =
        error && typeof error === "object" && "response" in error
          ? (error as { response?: { data?: { detail?: unknown } } }).response
              ?.data?.detail
          : null;
      const msg =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail
                .map((d) =>
                  typeof d === "object" && d && "msg" in d
                    ? String((d as { msg: string }).msg)
                    : String(d),
                )
                .join("; ")
            : error instanceof Error
              ? error.message
              : "Failed to upload file";
      alert(msg || "Failed to upload file");
    } finally {
      setIsUploading(false);
      e.target.value = "";
    }
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Pick the best supported audio format.
      // Safari only supports MP4/AAC; Chrome/Firefox support WebM/Opus.
      const preferredTypes = [
        "audio/mp4;codecs=aac", // Safari
        "audio/mp4",            // Safari fallback
        "audio/webm;codecs=opus", // Chrome / Firefox
        "audio/webm",           // Chrome / Firefox fallback
      ];
      const mimeType =
        preferredTypes.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";

      const mediaRecorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        audioChunksRef.current.push(event.data);
      };

      mediaRecorder.onstop = async () => {
        const actualMime = mediaRecorder.mimeType || mimeType || "audio/webm";
        const ext = actualMime.includes("mp4") ? "m4a" : "webm";
        const audioBlob = new Blob(audioChunksRef.current, {
          type: actualMime,
        });
        const audioFile = new File(
          [audioBlob],
          `recording-${Date.now()}.${ext}`,
          { type: actualMime },
        );

        try {
          setIsUploading(true);
          const response = await api.upload(audioFile, currentKB);

          const markdownLink = `[🎤 Voice Recording](${encodeFileUrl(response.url || response.href)})`;
          if (editorRef.current) {
            editorRef.current.insertAtCursor(markdownLink);
          } else if (selectedNote) {
            handleContentChange(selectedNote.content + markdownLink);
          }
        } catch (error) {
          console.error("Error uploading recording:", error);
          alert("Failed to upload recording");
        } finally {
          setIsUploading(false);
        }

        stream.getTracks().forEach((track) => track.stop());
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (error) {
      console.error("Error starting recording:", error);
      alert("Failed to access microphone");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleFileClick = (url: string, filename: string) => {
    const resolvedUrl = encodeFileUrl(resolveFileUrl(url, currentKB));
    let type: FilePreview["type"] = "other";

    if (isImageUrl(resolvedUrl) || isImageUrl(filename)) {
      type = "image";
    } else if (/\.pdf(\?|$)/i.test(resolvedUrl) || /\.pdf$/i.test(filename)) {
      type = "pdf";
    } else if (isVideoUrl(resolvedUrl) || isVideoUrl(filename)) {
      type = "video";
    } else if (isAudioUrl(resolvedUrl) || isAudioUrl(filename)) {
      type = "audio";
    }

    setFilePreview({ url: resolvedUrl, filename, type });
  };

  const handleRevealPreviewFile = async () => {
    if (!filePreview) return;
    try {
      const { local_path } = await api.resolveVaultLocalPath(
        filePreview.url,
        currentKB,
      );
      const ok = await revealInFolder(local_path);
      if (!ok) {
        // Browser / no desktop bridge — fall back to opening the file URL
        window.open(filePreview.url, "_blank", "noopener,noreferrer");
      }
    } catch (error) {
      console.error("Reveal failed:", error);
      alert("Could not reveal this file on disk.");
    }
  };

  const handleDateChange = async (dateString: string) => {
    if (!selectedNote) return;

    console.log("handleDateChange called with:", dateString);
    try {
      setIsSaving(true);

      // Save to backend with the new date
      console.log("Sending PUT request to update note date...");
      await api.updateNote(
        selectedNote.id,
        selectedNote.content,
        dateString,
        currentKB,
        selectedNote.title || undefined,
      );
      console.log("PUT request successful");

      // Refresh the note from backend to get the updated data
      const updatedNote = await api.getNote(selectedNote.id, currentKB);
      console.log("Refreshed note from backend:", updatedNote);
      setSelectedNote(updatedNote);
      contentBeforeEditRef.current = updatedNote.content;
      titleBeforeEditRef.current = updatedNote.title || "";

      // Refresh notes list to reflect the new date in sidebar
      await fetchNotes(searchQuery, processedFilter);
    } catch (error) {
      console.error("Error updating date:", error);
      alert("Failed to update note date. Please try again.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleCloseDatePicker = async () => {
    // Save the date if it was changed
    if (pendingDateChange && selectedNote) {
      console.log("Saving date change:", pendingDateChange);
      await handleDateChange(pendingDateChange);
    }
    setPendingDateChange(null);
    setShowDatePicker(false);
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-black">
      <ShaderBackground />
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
                onClick={async () => {
                  if (
                    !confirm(
                      "Queue all notes in this vault for re-ingest? Graph/vectors will rebuild from current .md files.",
                    )
                  )
                    return;
                  try {
                    await api.reingestVault(currentKB);
                    await fetchNotes(searchQuery, processedFilter);
                  } catch {
                    /* ignore */
                  }
                }}
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
                onClick={() => openFolderDialog(selectedFolder)}
                className="flex h-10 items-center justify-center rounded-xl border border-white/10 bg-white/5 px-2 text-white/60 transition hover:bg-white/10 hover:text-white"
              >
                <FolderPlus className="h-4 w-4" />
              </button>
              <button
                onClick={() => void handleCreateNote()}
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
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-xl border border-white/10 bg-white/5 py-2 pl-10 pr-4 text-sm text-white placeholder-white/40 backdrop-blur-xl focus:border-purple-500/50 focus:outline-none"
            />
          </div>

          {/* Filter Buttons */}
          <div className="mt-2 space-y-1 px-2">
            <div className="flex gap-1">
              <button
                onClick={() => setProcessedFilter("all")}
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
                onClick={() => setProcessedFilter("ingested")}
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
                onClick={() => setProcessedFilter("saved")}
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
                onClick={() => setProcessedFilter("ingesting")}
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
                onClick={() => setProcessedFilter("failed")}
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

          {notes.length > 0 && (
            <div className="mt-2 flex items-center gap-2 px-2">
              <button
                type="button"
                onClick={() => {
                  if (selectedNoteIds.size === notes.length) {
                    setSelectedNoteIds(new Set());
                  } else {
                    setSelectedNoteIds(new Set(notes.map((n) => n.id)));
                  }
                }}
                className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/60 hover:bg-white/10 hover:text-white"
              >
                {selectedNoteIds.size === notes.length
                  ? "Clear selection"
                  : "Select all"}
              </button>
              {selectedNoteIds.size > 0 && (
                <button
                  type="button"
                  disabled={batchDeleting}
                  onClick={() => void handleBatchDeleteNotes()}
                  className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1 text-[11px] text-red-300 hover:bg-red-500/20 disabled:opacity-50"
                >
                  {batchDeleting ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Trash2 className="h-3 w-3" />
                  )}
                  Delete {selectedNoteIds.size}
                </button>
              )}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-white/40" />
            </div>
          ) : notes.length === 0 && vaultFolders.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <FileText className="mb-2 h-8 w-8 text-white/20" />
              <p className="text-sm text-white/40">
                {searchQuery ? "No notes found" : "No notes yet"}
              </p>
            </div>
          ) : (
            <div className="space-y-0.5 p-2">
              {(() => {
                const visibleNotes =
                  processedFilter === "ingesting"
                    ? notes.filter(isActiveProcessingNote)
                    : notes;
                const noteFolders = vaultFolders.filter(
                  (f) => f !== "attachments" && !f.startsWith("attachments/"),
                );
                const tree = buildFolderTree(visibleNotes, noteFolders);
                const attachmentsOpen = !collapsedFolders.has("attachments");

                const toggleFolder = (path: string) => {
                  setCollapsedFolders((prev) => {
                    const next = new Set(prev);
                    if (next.has(path)) next.delete(path);
                    else next.add(path);
                    return next;
                  });
                };

                const mediaByFolder = new Map<
                  string,
                  Array<{ name: string; rel_path: string }>
                >();
                const rootMedia: Array<{ name: string; rel_path: string }> = [];
                for (const f of mediaFiles) {
                  const rel = f.rel_path.replace(/\\/g, "/");
                  if (
                    rel === "attachments" ||
                    rel.startsWith("attachments/")
                  ) {
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

                const acceptVaultDrop = (
                  e: DragEvent,
                  folderPath: string,
                ) => {
                  e.preventDefault();
                  e.stopPropagation();
                  e.dataTransfer.dropEffect = "move";
                  const noteId =
                    e.dataTransfer.getData("text/note-id") || dragNoteId;
                  const fileRel =
                    e.dataTransfer.getData("text/vault-file") || dragFileRel;
                  setDragNoteId(null);
                  setDragFileRel(null);
                  if (noteId) void handleMoveNoteToFolder(noteId, folderPath);
                  else if (fileRel)
                    void handleMoveVaultFile(fileRel, folderPath);
                };

                const allowVaultDragOver = (e: DragEvent) => {
                  e.preventDefault();
                  e.stopPropagation();
                  e.dataTransfer.dropEffect = "move";
                };

                const renderMediaRow = (
                  file: { name: string; rel_path: string },
                  depth: number,
                ) => (
                  <div
                    key={file.rel_path}
                    draggable
                    onDragStart={(e) => {
                      setDragFileRel(file.rel_path);
                      e.dataTransfer.setData("text/vault-file", file.rel_path);
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    onDragEnd={() => setDragFileRel(null)}
                    className={cn(
                      "group/file relative flex w-full items-center gap-1 rounded-md px-1.5 py-1 text-left text-[12px] text-white/60 hover:bg-white/5 hover:text-white/85",
                      dragFileRel === file.rel_path && "opacity-50",
                    )}
                    style={{ paddingLeft: 22 + depth * 12 }}
                  >
                    <button
                      type="button"
                      onClick={() => handleFileClick(file.rel_path, file.name)}
                      onDoubleClick={() => openRenameDialog(file.rel_path)}
                      className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                      title={`${file.rel_path}\nDouble-click to rename`}
                    >
                      <Paperclip className="h-3 w-3 shrink-0 text-white/30" />
                      <span className="truncate">{file.name}</span>
                    </button>
                    <button
                      type="button"
                      title="Rename"
                      onClick={(e) => {
                        e.stopPropagation();
                        openRenameDialog(file.rel_path);
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
                        void handleDeleteVaultAttachment(
                          file.rel_path,
                          file.name,
                        );
                      }}
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded opacity-0 hover:bg-red-500/20 group-hover/file:opacity-100"
                    >
                      <Trash2 className="h-3 w-3 text-red-400/80" />
                    </button>
                  </div>
                );

                const folderActionButtons = (folderPath: string) => (
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button
                      type="button"
                      title="New folder"
                      onClick={(e) => {
                        e.stopPropagation();
                        openFolderDialog(folderPath);
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
                        setSelectedFolder(folderPath);
                        void handleCreateNote(folderPath);
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
                          (dragNoteId || dragFileRel) &&
                            "ring-1 ring-teal-500/25",
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
                              toggleFolder(node.path);
                              setSelectedFolder(node.path);
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
                            <span className="truncate font-medium">
                              {node.name}
                            </span>
                          </button>
                          {folderActionButtons(node.path)}
                        </div>
                        {isOpen && (
                          <>
                            {node.children.map((child) =>
                              renderNode(child, depth + 1),
                            )}
                            {folderMedia.map((f) =>
                              renderMediaRow(f, depth + 1),
                            )}
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
                        setDragNoteId(note.id);
                        e.dataTransfer.setData("text/note-id", note.id);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onDragEnd={() => setDragNoteId(null)}
                      onDragOver={allowVaultDragOver}
                      onDrop={(e) => acceptVaultDrop(e, parentFolder)}
                      className={cn(
                        "relative flex w-full items-center gap-1 rounded-md px-1 py-1 text-left text-[13px] transition-colors",
                        selectedNote?.id === note.id
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
                        onChange={() => toggleNoteSelected(note.id)}
                        onClick={(e) => e.stopPropagation()}
                        className="h-3.5 w-3.5 shrink-0 rounded border-white/30 bg-black/40"
                        aria-label={`Select ${note.title || "note"}`}
                      />
                      <button
                        type="button"
                        onClick={() => handleNoteSelect(note)}
                        className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                      >
                        <FileText className="h-3.5 w-3.5 shrink-0 text-white/35" />
                        <span className="min-w-0 flex-1 truncate">
                          {note.title || node.name || "Untitled"}
                        </span>
                        <span className="shrink-0">
                          {note.processed ? (
                            <span className="block h-1.5 w-1.5 rounded-full bg-emerald-400" title="Ingested" />
                          ) : note.failed ? (
                            <span className="block h-1.5 w-1.5 rounded-full bg-red-400" title="Failed" />
                          ) : isActiveProcessingNote(note) ? (
                            <span className="block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" title={getProcessingLabel(note)} />
                          ) : (
                            <span className="block h-1.5 w-1.5 rounded-full bg-white/20" title="Saved" />
                          )}
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
                        (dragNoteId || dragFileRel) &&
                          "ring-1 ring-teal-500/25",
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
                          onClick={() => setSelectedFolder("")}
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
                      {rootMedia.map((f) => renderMediaRow(f, 0))}
                    </div>

                    <div
                      className={cn(
                        "group/folder mt-2 border-t border-white/5 pt-2",
                        (dragNoteId || dragFileRel) &&
                          "ring-1 ring-sky-500/25 rounded-md",
                      )}
                      onDragOver={allowVaultDragOver}
                      onDrop={(e) => acceptVaultDrop(e, "attachments")}
                    >
                      <div className="flex w-full items-center gap-0.5 rounded-md pr-1 text-[13px] text-white/65 hover:bg-white/5 hover:text-white/90">
                        <button
                          type="button"
                          onClick={() => toggleFolder("attachments")}
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
                            Default upload folder — drag files into other
                            folders anytime
                          </p>
                        ) : (
                          attachmentFiles.map((f) => (
                            <div
                              key={f.rel_path}
                              draggable
                              onDragStart={(e) => {
                                setDragFileRel(f.rel_path);
                                e.dataTransfer.setData(
                                  "text/vault-file",
                                  f.rel_path,
                                );
                                e.dataTransfer.effectAllowed = "move";
                              }}
                              onDragEnd={() => setDragFileRel(null)}
                              className={cn(
                                "group/file flex w-full items-center gap-1 rounded-md px-1.5 py-1 text-left text-[12px] text-white/60 hover:bg-white/5 hover:text-white/85",
                                dragFileRel === f.rel_path && "opacity-50",
                              )}
                              style={{ paddingLeft: 22 }}
                            >
                              <button
                                type="button"
                                onClick={() =>
                                  handleFileClick(f.rel_path, f.name)
                                }
                                onDoubleClick={() =>
                                  openRenameDialog(f.rel_path)
                                }
                                className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                                title={`${f.rel_path}\nDouble-click to rename`}
                              >
                                <Paperclip className="h-3 w-3 shrink-0 text-white/30" />
                                <span className="truncate">{f.name}</span>
                              </button>
                              <button
                                type="button"
                                title="Rename"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openRenameDialog(f.rel_path);
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
                                  void handleDeleteVaultAttachment(
                                    f.rel_path,
                                    f.name,
                                  );
                                }}
                                className="flex h-5 w-5 shrink-0 items-center justify-center rounded opacity-0 hover:bg-red-500/20 group-hover/file:opacity-100"
                              >
                                <Trash2 className="h-3 w-3 text-red-400/80" />
                              </button>
                            </div>
                          ))
                        ))}
                    </div>
                  </>
                );
              })()}
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

      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        {selectedNote ? (
          <>
            <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-white/10 bg-black/50 px-4 py-3 backdrop-blur-xl sm:px-6 sm:py-4">
              <div className="min-w-0 max-w-full flex-1 basis-[12rem]">
                <input
                  type="text"
                  value={selectedNote.title || ""}
                  onChange={(e) => handleTitleChange(e.target.value)}
                  placeholder="Untitled"
                  className="w-full max-w-xl rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-white placeholder-white/25 outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
                />
                <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-2">
                  <p className="text-xs text-white/50">
                    {isSaving
                      ? "Saving…"
                      : isUploading
                        ? "Uploading…"
                        : "Saved"}
                  </p>
                  <p className="shrink-0 text-xs text-white/40">
                    {new Date(selectedNote.created_at).toLocaleDateString(
                      "en-US",
                      {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      },
                    )}
                  </p>
                  {selectedNote.processed ? (
                    <span className="inline-flex max-w-full items-center gap-1 truncate rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                      Ingested
                    </span>
                  ) : selectedNote.failed ? (
                    <span className="inline-flex max-w-full items-center gap-1 truncate rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-400">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" />
                      Failed
                    </span>
                  ) : isActiveProcessingNote(selectedNote) ? (
                    <span
                      className="inline-flex max-w-full items-center gap-1 truncate rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-400"
                      title={getProcessingLabel(selectedNote)}
                    >
                      <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
                      Ingesting…
                    </span>
                  ) : isPendingReingestNote(selectedNote) ? (
                    <span className="inline-flex max-w-full items-center gap-1 truncate rounded-full bg-orange-500/15 px-2 py-0.5 text-xs font-medium text-orange-300/90">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-orange-400" />
                      Needs re-ingest
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-white/8 px-2 py-0.5 text-xs font-medium text-white/40">
                      <span className="h-1.5 w-1.5 rounded-full bg-white/30" />
                      Saved
                    </span>
                  )}
                </div>
              </div>
              <div className="flex max-w-full flex-wrap items-center justify-end gap-2">
                <>
                    <button
                      onClick={handleIngestNote}
                      disabled={
                        isSaving ||
                        !selectedNote?.content.trim() ||
                        Boolean(selectedNote && isActiveProcessingNote(selectedNote))
                      }
                      title={
                        selectedNote && isActiveProcessingNote(selectedNote)
                          ? getProcessingLabel(selectedNote)
                          : selectedNote?.processed
                            ? "Re-ingest note"
                            : "Ingest note"
                      }
                      className="flex h-9 shrink-0 items-center gap-2 rounded-lg bg-linear-to-r from-purple-500 to-pink-500 px-3 text-sm font-medium text-white transition-all hover:from-purple-600 hover:to-pink-600 disabled:cursor-not-allowed disabled:opacity-50 sm:px-4"
                    >
                      {selectedNote && isActiveProcessingNote(selectedNote) ? (
                        <>
                          <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                          <span className="whitespace-nowrap">Ingesting…</span>
                        </>
                      ) : isSaving ? (
                        <>
                          <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                          <span className="whitespace-nowrap">Saving…</span>
                        </>
                      ) : selectedNote?.processed ? (
                        <>
                          <Database className="h-4 w-4 shrink-0" />
                          <span className="whitespace-nowrap">Re-ingest</span>
                        </>
                      ) : selectedNote?.failed ? (
                        <>
                          <Database className="h-4 w-4 shrink-0" />
                          <span className="whitespace-nowrap">Retry</span>
                        </>
                      ) : (
                        <>
                          <Database className="h-4 w-4 shrink-0" />
                          <span className="whitespace-nowrap">Ingest</span>
                        </>
                      )}
                    </button>
                    <button
                      onClick={() => setShowDatePicker(!showDatePicker)}
                      title="Change date"
                      className="flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-2.5 text-sm text-white/80 transition-all hover:bg-white/10 sm:px-4"
                    >
                      <Calendar className="h-4 w-4 shrink-0" />
                      <span className="hidden sm:inline">Date</span>
                    </button>
                    <div className="hidden h-6 w-px bg-white/10 sm:block" />
                    <button
                      onClick={isRecording ? stopRecording : startRecording}
                      disabled={isUploading}
                      title={isRecording ? "Stop recording" : "Record audio"}
                      className={cn(
                        "flex h-9 items-center gap-2 rounded-xl border px-2.5 text-sm transition-all sm:px-4",
                        isRecording
                          ? "border-red-500/30 bg-red-500/10 text-red-400 animate-pulse"
                          : "border-white/10 bg-white/5 text-white/80 hover:bg-white/10",
                      )}
                    >
                      {isRecording ? (
                        <MicOff className="h-4 w-4 shrink-0" />
                      ) : (
                        <Mic className="h-4 w-4 shrink-0" />
                      )}
                      <span className="hidden sm:inline">
                        {isRecording ? "Stop" : "Record"}
                      </span>
                    </button>
                </>
                <button
                  onClick={() => setShowConnectedPanel((v) => !v)}
                  title="Connected notes"
                  className={cn(
                    "flex h-9 items-center gap-2 rounded-xl px-2.5 text-sm transition-all sm:px-4",
                    showConnectedPanel
                      ? "bg-teal-500/25 text-teal-200 border border-teal-500/40"
                      : "border border-white/10 bg-white/5 text-white/80 hover:bg-white/10",
                  )}
                >
                  <Network className="h-4 w-4 shrink-0" />
                  <span className="hidden sm:inline">Connected</span>
                </button>
                <button
                  onClick={handleDeleteNote}
                  title="Delete note"
                  className="flex h-9 items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-2.5 text-sm text-red-400 transition-all hover:bg-red-500/20 sm:px-4"
                >
                  <Trash2 className="h-4 w-4 shrink-0" />
                  <span className="hidden sm:inline">Delete</span>
                </button>
              </div>
            </div>

            {/* Attachments strip */}
            {selectedNote &&
              (() => {
                const attachmentRegex =
                  /(?:!\[([^\]]*)\]\(([^)]+)\)|\[([📎🎤][^\]]+)\]\(([^)]+)\))/g;
                const attachments: {
                  label: string;
                  url: string;
                  raw: string;
                }[] = [];
                let m: RegExpExecArray | null;
                while (
                  (m = attachmentRegex.exec(selectedNote.content)) !== null
                ) {
                  const label = (m[1] ?? m[3] ?? "file").replace(
                    /^[📎🎤]\s*/,
                    "",
                  );
                  const url = m[2] ?? m[4] ?? "";
                  if (!url) continue;
                  attachments.push({ label, url, raw: m[0] });
                }
                return attachments.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-2 border-t border-white/5 bg-white/[0.02] px-6 py-2">
                    <span className="text-xs text-white/30">Attachments:</span>
                    {attachments.map((att) => (
                        <span
                          key={att.url}
                          className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/60"
                        >
                          <button
                            onClick={() =>
                              handleFileClick(
                                att.url,
                                att.label.replace(/^[📎🎤]\s*/, ""),
                              )
                            }
                            className="hover:text-white/90 transition-colors"
                          >
                            {att.label}
                          </button>
                          <button
                            onClick={() => handleDeleteFile(att.url, att.raw)}
                            className="ml-1 rounded text-white/30 hover:text-red-400 transition-colors"
                            title="Delete file"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                  </div>
                ) : null;
              })()}

            <div className="flex min-h-0 flex-1 overflow-hidden">
              <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                <MarkdownNoteEditor
                  key={selectedNote.id}
                  ref={editorRef}
                  value={selectedNote.content}
                  onChange={handleContentChange}
                  onEntityClick={handleEntityClick}
                  onWikilinkClick={handleWikilinkClick}
                  onWikilinkHover={handleWikilinkHover}
                  onWikilinkLeave={handleWikilinkLeave}
                  onAttachFile={handleFileAttach}
                  attachDisabled={isUploading}
                  kb={currentKB}
                  placeholder="Start writing..."
                  className="h-full w-full"
                />
              </div>
              {showConnectedPanel && (
                <ConnectedNotesPanel
                  noteId={selectedNote.id}
                  noteContent={selectedNote.content}
                  kb={currentKB}
                  onClose={() => setShowConnectedPanel(false)}
                  onSelectNote={(id) => {
                    const match = notes.find((n) => n.id === id);
                    if (match) void handleNoteSelect(match);
                  }}
                  onSelectEntity={(nodeId, name) => {
                    handleEntityClick(nodeId, name);
                  }}
                />
              )}
            </div>

            {/* Entity detail panel — overlays from the right within the note area */}
            <EntityDetailPanel
              nodeId={entityPanelNodeId}
              name={entityPanelName}
              kb={currentKB}
              onClose={() => setEntityPanelNodeId(null)}
            />
          </>
        ) : (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <FileText className="mb-4 h-16 w-16 text-white/20" />
            <h2 className="mb-2 text-2xl font-bold text-white">
              No note selected
            </h2>
            <p className="mb-6 text-white/60">
              Select a note from the sidebar or create a new one
            </p>
            <button
              onClick={() => void handleCreateNote()}
              disabled={isSaving}
              className="flex items-center gap-2 rounded-xl bg-linear-to-br from-purple-500 to-pink-500 px-6 py-3 text-white transition-all hover:scale-105 disabled:opacity-50"
            >
              <Plus className="h-5 w-5" />
              Create Note
            </button>
          </div>
        )}
      </div>

      {/* Date Picker Modal */}
      <AnimatePresence>
        {showDatePicker && selectedNote && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
            onClick={(e) => {
              // Only close if clicking the backdrop itself
              if (e.target === e.currentTarget) {
                handleCloseDatePicker();
              }
            }}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="relative mx-4 w-full max-w-md rounded-2xl border border-white/10 bg-black/95 p-6 shadow-2xl backdrop-blur-xl"
            >
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Set Note Date</h2>
                <button
                  onClick={handleCloseDatePicker}
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
                  title="Close date picker"
                  aria-label="Close date picker"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <input
                type="datetime-local"
                defaultValue={new Date(selectedNote.created_at)
                  .toISOString()
                  .slice(0, 16)}
                onChange={(e) => {
                  if (e.target.value) {
                    const isoDate = new Date(e.target.value).toISOString();
                    console.log("Date changed to:", isoDate);
                    setPendingDateChange(isoDate);
                  }
                }}
                className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-white backdrop-blur-xl focus:border-purple-500/50 focus:outline-none"
                autoFocus
                title="Select note date"
                aria-label="Select note date"
              />
              <div className="mt-4 flex justify-end gap-2">
                <button
                  onClick={handleCloseDatePicker}
                  className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/80 transition-all hover:bg-white/10"
                >
                  {pendingDateChange ? "Save & Close" : "Close"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* File Preview Modal */}
      <AnimatePresence>
        {filePreview && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
            onClick={() => setFilePreview(null)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="relative max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-2xl border border-white/10 bg-black/95 shadow-2xl backdrop-blur-xl"
            >
              <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
                <h2 className="text-lg font-bold text-white">
                  {filePreview.filename}
                </h2>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleRevealPreviewFile()}
                    className="flex h-8 items-center gap-1.5 rounded-lg bg-white/5 px-2.5 text-white/60 transition-all hover:bg-white/10 hover:text-white sm:px-3"
                    title={
                      isDesktopApp()
                        ? revealInFolderLabel()
                        : "Open file"
                    }
                    aria-label={
                      isDesktopApp()
                        ? revealInFolderLabel()
                        : "Open file"
                    }
                  >
                    <FolderOpen className="h-4 w-4" />
                    <span className="hidden text-xs sm:inline">
                      {isDesktopApp()
                        ? revealInFolderLabel()
                        : "Open"}
                    </span>
                  </button>
                  <button
                    onClick={() => setFilePreview(null)}
                    className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
                    title="Close file preview"
                    aria-label="Close file preview"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>
              <div className="max-h-[calc(90vh-80px)] overflow-y-auto p-6">
                {filePreview.type === "image" && (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={filePreview.url}
                    alt={filePreview.filename}
                    className="mx-auto max-w-full rounded-lg"
                  />
                )}
                {filePreview.type === "pdf" && (
                  <iframe
                    src={filePreview.url}
                    className="h-[70vh] w-full rounded-lg"
                    title="PDF preview"
                  />
                )}
                {filePreview.type === "video" && (
                  <div className="flex min-h-[240px] items-center justify-center">
                    <BlobMediaPlayer
                      url={filePreview.url}
                      kbId={currentKB}
                      kind="video"
                      className="mx-auto max-h-[70vh] w-full max-w-full rounded-lg bg-black"
                    />
                  </div>
                )}
                {filePreview.type === "audio" && (
                  <div className="flex items-center justify-center">
                    <BlobMediaPlayer
                      url={filePreview.url}
                      kbId={currentKB}
                      kind="audio"
                      className="w-full max-w-2xl"
                    />
                  </div>
                )}
                {filePreview.type === "other" && (
                  <div className="text-center">
                    <p className="mb-4 text-white/60">
                      Preview not available for this file type
                    </p>
                    <button
                      type="button"
                      onClick={() => void handleRevealPreviewFile()}
                      className="inline-flex items-center gap-2 rounded-xl bg-linear-to-br from-purple-500 to-pink-500 px-6 py-3 text-white transition-all hover:scale-105"
                    >
                      <FolderOpen className="h-5 w-5" />
                      {isDesktopApp()
                        ? revealInFolderLabel()
                        : "Open file"}
                    </button>
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {folderDialog && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="mx-4 w-full max-w-sm rounded-2xl border border-white/10 bg-black/95 p-5 shadow-2xl">
            <h2 className="mb-1 text-lg font-semibold text-white">New folder</h2>
            <p className="mb-4 text-xs text-white/45">
              {folderDialog.parent
                ? `Inside ${folderDialog.parent}`
                : `Inside ${vaultName}`}
            </p>
            <input
              autoFocus
              value={folderDialog.name}
              onChange={(e) =>
                setFolderDialog((d) =>
                  d ? { ...d, name: e.target.value } : d,
                )
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitFolderDialog();
                if (e.key === "Escape") setFolderDialog(null);
              }}
              placeholder="Folder name"
              className="mb-4 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-teal-500/40"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setFolderDialog(null)}
                className="rounded-lg px-3 py-2 text-sm text-white/60 hover:bg-white/10"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void submitFolderDialog()}
                className="rounded-lg bg-teal-500/25 px-3 py-2 text-sm font-medium text-teal-200 hover:bg-teal-500/35"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {renameDialog && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="mx-4 w-full max-w-sm rounded-2xl border border-white/10 bg-black/95 p-5 shadow-2xl">
            <h2 className="mb-1 text-lg font-semibold text-white">Rename file</h2>
            <p className="mb-4 truncate text-xs text-white/45">
              {renameDialog.rel_path}
            </p>
            <input
              autoFocus
              value={renameDialog.name}
              onChange={(e) =>
                setRenameDialog((d) =>
                  d ? { ...d, name: e.target.value } : d,
                )
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitRenameDialog();
                if (e.key === "Escape") setRenameDialog(null);
              }}
              placeholder="File name"
              className="mb-4 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-teal-500/40"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRenameDialog(null)}
                className="rounded-lg px-3 py-2 text-sm text-white/60 hover:bg-white/10"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void submitRenameDialog()}
                className="rounded-lg bg-teal-500/25 px-3 py-2 text-sm font-medium text-teal-200 hover:bg-teal-500/35"
              >
                Rename
              </button>
            </div>
          </div>
        </div>
      )}

      {wikilinkPreview && (
        <div
          className="pointer-events-none fixed z-[80] w-80 overflow-hidden rounded-xl border border-teal-500/30 bg-black/95 shadow-2xl backdrop-blur-xl"
          style={{ left: wikilinkPreview.x, top: wikilinkPreview.y }}
        >
          <div className="border-b border-white/10 px-3 py-2">
            <p className="truncate text-sm font-medium text-teal-200">
              {wikilinkPreview.title}
            </p>
            {wikilinkPreview.missing && (
              <p className="text-[11px] text-red-300/80">Note not found</p>
            )}
          </div>
          <div className="max-h-44 overflow-hidden px-3 py-2">
            <p className="whitespace-pre-wrap text-xs leading-relaxed text-white/70 line-clamp-[10]">
              {wikilinkPreview.missing
                ? "Create this note or check the [[wikilink]] target."
                : wikilinkPreview.content.slice(0, 600) || "Empty note"}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
