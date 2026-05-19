"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Plus,
  Search,
  Trash2,
  Eye,
  FileText,
  Loader2,
  Paperclip,
  Mic,
  MicOff,
  Calendar,
  X,
  ExternalLink,
  Database,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ShaderBackground } from "@/components/shader-background";
import { useKB } from "@/lib/kb-context";
import type { Note, FilePreview } from "@/lib/types";


type ProcessedFilter = "all" | "ingested" | "ingesting" | "saved" | "failed";

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
  const [isPreviewMode, setIsPreviewMode] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [filePreview, setFilePreview] = useState<FilePreview | null>(null);
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [pendingDateChange, setPendingDateChange] = useState<string | null>(
    null,
  );
  const contentBeforeEditRef = useRef<string>("");
  const searchTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const autoSaveTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // Fetch notes once KB context is hydrated from localStorage, and re-fetch on KB switch
  useEffect(() => {
    if (!isHydrated) return;
    fetchNotes(undefined, processedFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentKB, isHydrated]);

  // Debounced search and filter
  useEffect(() => {
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
  }, [searchQuery, processedFilter]);

  const handleSaveNote = useCallback(async (note: Note) => {
    // Don't save if content hasn't changed
    if (!note || note.content === contentBeforeEditRef.current) return;

    try {
      setIsSaving(true);
      await api.updateNote(note.id, note.content);
      contentBeforeEditRef.current = note.content;
      // Don't refresh list on autosave to avoid interrupting typing
    } catch (error) {
      console.error("Error saving note:", error);
    } finally {
      setIsSaving(false);
    }
  }, []);

  // Auto-save: Debounced save 1.5 seconds after user stops typing
  useEffect(() => {
    if (!selectedNote) return;

    // Clear any existing timeout
    if (autoSaveTimeoutRef.current) {
      clearTimeout(autoSaveTimeoutRef.current);
    }

    // Only auto-save if content has changed
    if (selectedNote.content !== contentBeforeEditRef.current) {
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

  // Save locally on page unload (backup)
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (
        selectedNote &&
        contentBeforeEditRef.current !== selectedNote.content
      ) {
        handleSaveNote(selectedNote);
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [selectedNote, handleSaveNote]);

  const fetchNotes = async (search?: string, filter?: ProcessedFilter) => {
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
      setNotes(data);
    } catch (error) {
      console.error("Error fetching notes:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleNoteSelect = (note: Note) => {
    // Save previous note if it has changes
    if (selectedNote && contentBeforeEditRef.current !== selectedNote.content) {
      handleSaveNote(selectedNote);
    }

    setSelectedNote(note);
    // Open notes in preview mode by default
    setIsPreviewMode(true);
    contentBeforeEditRef.current = note.content;
  };

  const handleCreateNote = async () => {
    // Save current note if it has changes
    if (selectedNote && contentBeforeEditRef.current !== selectedNote.content) {
      await handleSaveNote(selectedNote);
    }

    try {
      // Create note immediately in database (with processed=False)
      const newNote = await api.createNote("", new Date().toISOString(), currentKB);

      // Refresh notes list and select the new note
      await fetchNotes(searchQuery, processedFilter);
      setSelectedNote(newNote);
      setIsPreviewMode(false);
      contentBeforeEditRef.current = "";
    } catch (error) {
      console.error("Error creating note:", error);
      alert("Failed to create note. Please try again.");
    }
  };

  const handleIngestNote = async () => {
    if (!selectedNote || !selectedNote.content.trim()) {
      alert("Cannot ingest an empty note");
      return;
    }

    try {
      setIsSaving(true);
      await api.ingestNote(selectedNote.id, currentKB);
      // Track as in-flight — polling will update state when done
      setIngestingNoteIds((prev) => new Set([...prev, selectedNote.id]));
      // Optimistically clear any previous failure flag
      const patched = { ...selectedNote, failed: false };
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
      const completed: Array<{
        id: string;
        processed: boolean;
        failed: boolean;
      }> = [];
      await Promise.all(
        Array.from(ingestingNoteIds).map(async (noteId) => {
          try {
            const status = await api.getNoteStatus(noteId);
            if (status.processed || status.failed) {
              completed.push({
                id: noteId,
                processed: status.processed,
                failed: status.failed,
              });
            }
          } catch { }
        }),
      );
      if (completed.length === 0) return;
      setIngestingNoteIds((prev) => {
        const next = new Set(prev);
        completed.forEach((c) => next.delete(c.id));
        return next;
      });
      setNotes((prev) =>
        prev.map((n) => {
          const update = completed.find((c) => c.id === n.id);
          return update
            ? { ...n, processed: update.processed, failed: update.failed }
            : n;
        }),
      );
      setSelectedNote((prev) => {
        if (!prev) return null;
        const update = completed.find((c) => c.id === prev.id);
        return update
          ? { ...prev, processed: update.processed, failed: update.failed }
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
  };

  const handleDeleteNote = async () => {
    if (!selectedNote) return;

    const confirmDelete = window.confirm(`Delete "${selectedNote.title}"?`);
    if (!confirmDelete) return;

    try {
      await api.deleteNote(selectedNote.id, currentKB);
      setSelectedNote(null);
      await fetchNotes(searchQuery, processedFilter);
    } catch (error) {
      console.error("Error deleting note:", error);
    }
  };

  const handleDeleteFile = async (fileUrl: string, markdownText: string) => {
    if (!selectedNote) return;
    const fileKey = fileUrl.split("/").pop();
    if (!fileKey) return;
    try {
      await api.deleteFile(fileKey);
      // Remove the markdown link from note content
      const newContent = selectedNote.content.replace(markdownText, "");
      const updatedNote = { ...selectedNote, content: newContent };
      setSelectedNote(updatedNote);
      await api.updateNote(
        selectedNote.id,
        newContent,
        selectedNote.created_at,
      );
    } catch (error) {
      console.error("Error deleting file:", error);
    }
  };

  const handleFileAttach = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedNote) return;

    try {
      setIsUploading(true);
      const response = await api.upload(file);

      const textarea = textareaRef.current;
      if (textarea) {
        const cursorPos = textarea.selectionStart;
        const textBefore = selectedNote.content.substring(0, cursorPos);
        const textAfter = selectedNote.content.substring(cursorPos);
        const markdownLink = `[📎 ${file.name}](${response.url})`;
        const newContent = textBefore + markdownLink + textAfter;

        const updatedNote = { ...selectedNote, content: newContent };
        setSelectedNote(updatedNote);

        setTimeout(() => {
          textarea.focus();
          const newCursorPos = cursorPos + markdownLink.length;
          textarea.setSelectionRange(newCursorPos, newCursorPos);
        }, 0);
      }
    } catch (error) {
      console.error("Error uploading file:", error);
      alert("Failed to upload file");
    } finally {
      setIsUploading(false);
      e.target.value = "";
    }
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        audioChunksRef.current.push(event.data);
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, {
          type: "audio/webm",
        });
        const audioFile = new File(
          [audioBlob],
          `recording-${Date.now()}.webm`,
          { type: "audio/webm" },
        );

        try {
          setIsUploading(true);
          const response = await api.upload(audioFile);

          const textarea = textareaRef.current;
          if (textarea && selectedNote) {
            const cursorPos = textarea.selectionStart;
            const textBefore = selectedNote.content.substring(0, cursorPos);
            const textAfter = selectedNote.content.substring(cursorPos);
            const markdownLink = `[🎤 Voice Recording](${response.url})`;
            const newContent = textBefore + markdownLink + textAfter;

            const updatedNote = { ...selectedNote, content: newContent };
            setSelectedNote(updatedNote);

            setTimeout(() => {
              textarea.focus();
              const newCursorPos = cursorPos + markdownLink.length;
              textarea.setSelectionRange(newCursorPos, newCursorPos);
            }, 0);
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
    const lowerUrl = url.toLowerCase();
    let type: FilePreview["type"] = "other";

    if (lowerUrl.match(/\.(jpg|jpeg|png|webp|gif)$/)) {
      type = "image";
    } else if (lowerUrl.endsWith(".pdf")) {
      type = "pdf";
    } else if (lowerUrl.match(/\.(webm|m4a|mp3|wav|ogg|mp4)$/)) {
      type = "audio";
    }

    setFilePreview({ url, filename, type });
  };

  const handleDateChange = async (dateString: string) => {
    if (!selectedNote) return;

    console.log("handleDateChange called with:", dateString);
    try {
      setIsSaving(true);

      // Save to backend with the new date
      console.log("Sending PUT request to update note date...");
      await api.updateNote(selectedNote.id, selectedNote.content, dateString);
      console.log("PUT request successful");

      // Refresh the note from backend to get the updated data
      const updatedNote = await api.getNote(selectedNote.id);
      console.log("Refreshed note from backend:", updatedNote);
      setSelectedNote(updatedNote);
      contentBeforeEditRef.current = updatedNote.content;

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

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays} days ago`;
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-black">
      <ShaderBackground />
      <div className="relative z-10 flex w-80 flex-col border-r border-white/10 bg-black/50 backdrop-blur-xl">
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
            <button
              onClick={handleCreateNote}
              disabled={isSaving}
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-linear-to-br from-purple-500 to-pink-500 text-white transition-all hover:scale-105 disabled:opacity-50"
            >
              {isSaving ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Plus className="h-5 w-5" />
              )}
            </button>
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
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-white/40" />
            </div>
          ) : notes.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <FileText className="mb-2 h-8 w-8 text-white/20" />
              <p className="text-sm text-white/40">
                {searchQuery ? "No notes found" : "No notes yet"}
              </p>
            </div>
          ) : (
            <div className="space-y-1 p-2">
              {/* Note list: client-side filter for "ingesting" (local state only) */}
              {(processedFilter === "ingesting"
                ? notes.filter((n) => ingestingNoteIds.has(n.id))
                : notes
              ).map((note) => (
                <button
                  key={note.id}
                  onClick={() => handleNoteSelect(note)}
                  className={cn(
                    "w-full rounded-xl p-3 text-left transition-all relative",
                    selectedNote?.id === note.id
                      ? "bg-linear-to-br from-purple-500/20 to-pink-500/20 border border-purple-500/30"
                      : "hover:bg-white/5 border border-transparent",
                  )}
                >
                  {/* Ingestion Status Indicator */}
                  <div className="absolute top-3 right-3">
                    {note.processed ? (
                      <div
                        className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]"
                        title="Ingested"
                      />
                    ) : note.failed ? (
                      <div
                        className="h-2 w-2 rounded-full bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.6)]"
                        title="Ingestion failed"
                      />
                    ) : ingestingNoteIds.has(note.id) ? (
                      <div
                        className="h-2 w-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)] animate-pulse"
                        title="Ingesting…"
                      />
                    ) : (
                      <div
                        className="h-2 w-2 rounded-full bg-white/20"
                        title="Saved — not ingested"
                      />
                    )}
                  </div>
                  <h3 className="mb-1 truncate font-medium text-white pr-6">
                    {note.title || "Untitled"}
                  </h3>
                  <p className="truncate text-sm text-white/60">
                    {note.content || "Empty note"}
                  </p>
                  <p className="mt-1 text-xs text-white/40">
                    {formatDate(note.created_at)}
                  </p>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-white/10 p-3">
          <p className="text-xs text-white/40 text-center">
            {processedFilter === "ingesting"
              ? `${ingestingNoteIds.size} ingesting`
              : `${notes.length} ${notes.length === 1 ? "note" : "notes"}`}
          </p>
        </div>
      </div>

      <div className="relative z-10 flex flex-1 flex-col">
        {selectedNote ? (
          <>
            <div className="flex items-center justify-between border-b border-white/10 bg-black/50 px-6 py-4 backdrop-blur-xl">
              <div>
                {isPreviewMode && (
                  <>
                    <h2 className="text-xl font-bold text-white">
                      {selectedNote.title || "Untitled"}
                    </h2>
                    <div className="flex items-center gap-2 mt-1">
                      <p className="text-sm text-white/40">
                        {new Date(selectedNote.created_at).toLocaleDateString(
                          "en-US",
                          {
                            month: "long",
                            day: "numeric",
                            year: "numeric",
                            hour: "numeric",
                            minute: "2-digit",
                          },
                        )}
                      </p>
                      {selectedNote.processed ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                          Ingested
                        </span>
                      ) : selectedNote.failed ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
                          Failed
                        </span>
                      ) : ingestingNoteIds.has(selectedNote.id) ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-400">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          Ingesting…
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-white/8 px-2 py-0.5 text-xs font-medium text-white/40">
                          <span className="h-1.5 w-1.5 rounded-full bg-white/30" />
                          Saved
                        </span>
                      )}
                    </div>
                  </>
                )}
                {!isPreviewMode && (
                  <>
                    <p className="text-sm text-white/60">
                      {isSaving
                        ? "Saving..."
                        : isUploading
                          ? "Uploading..."
                          : "Saved"}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <p className="text-xs text-white/40">
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
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                          Ingested
                        </span>
                      ) : selectedNote.failed ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
                          Failed
                        </span>
                      ) : ingestingNoteIds.has(selectedNote.id) ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-400">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          Ingesting…
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-white/8 px-2 py-0.5 text-xs font-medium text-white/40">
                          <span className="h-1.5 w-1.5 rounded-full bg-white/30" />
                          Saved
                        </span>
                      )}
                    </div>
                  </>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* Edit Controls - Only visible in Edit Mode */}
                {!isPreviewMode && (
                  <>
                    <button
                      onClick={handleIngestNote}
                      disabled={
                        isSaving ||
                        !selectedNote?.content.trim() ||
                        ingestingNoteIds.has(selectedNote?.id ?? "")
                      }
                      className="flex h-9 items-center gap-2 rounded-lg bg-linear-to-r from-purple-500 to-pink-500 px-4 text-sm font-medium text-white transition-all hover:from-purple-600 hover:to-pink-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {ingestingNoteIds.has(selectedNote?.id ?? "") ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Ingesting…
                        </>
                      ) : isSaving ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Saving…
                        </>
                      ) : selectedNote?.processed ? (
                        <>
                          <Database className="h-4 w-4" />
                          Re-ingest
                        </>
                      ) : selectedNote?.failed ? (
                        <>
                          <Database className="h-4 w-4" />
                          Retry Ingest
                        </>
                      ) : (
                        <>
                          <Database className="h-4 w-4" />
                          Ingest Note
                        </>
                      )}
                    </button>
                    <button
                      onClick={() => setShowDatePicker(!showDatePicker)}
                      className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/80 transition-all hover:bg-white/10"
                    >
                      <Calendar className="h-4 w-4" />
                      Date
                    </button>
                    <div className="h-6 w-px bg-white/10" />
                    <input
                      type="file"
                      id="file-upload"
                      className="hidden"
                      onChange={handleFileAttach}
                      disabled={isUploading}
                    />
                    <label
                      htmlFor="file-upload"
                      className={cn(
                        "flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/80 transition-all cursor-pointer",
                        isUploading
                          ? "opacity-50 cursor-not-allowed"
                          : "hover:bg-white/10",
                      )}
                    >
                      <Paperclip className="h-4 w-4" />
                      Attach
                    </label>
                    <button
                      onClick={isRecording ? stopRecording : startRecording}
                      disabled={isUploading}
                      className={cn(
                        "flex items-center gap-2 rounded-xl border px-4 py-2 text-sm transition-all",
                        isRecording
                          ? "border-red-500/30 bg-red-500/10 text-red-400 animate-pulse"
                          : "border-white/10 bg-white/5 text-white/80 hover:bg-white/10",
                      )}
                    >
                      {isRecording ? (
                        <MicOff className="h-4 w-4" />
                      ) : (
                        <Mic className="h-4 w-4" />
                      )}
                      {isRecording ? "Stop" : "Record"}
                    </button>
                  </>
                )}
                <button
                  onClick={() => setIsPreviewMode(!isPreviewMode)}
                  className={cn(
                    "flex items-center gap-2 rounded-xl px-4 py-2 text-sm transition-all",
                    isPreviewMode
                      ? "bg-linear-to-br from-purple-500 to-pink-500 text-white"
                      : "border border-white/10 bg-white/5 text-white/80 hover:bg-white/10",
                  )}
                >
                  <Eye className="h-4 w-4" />
                  {isPreviewMode ? "Edit" : "Preview"}
                </button>
                <button
                  onClick={handleDeleteNote}
                  className="flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400 transition-all hover:bg-red-500/20"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </button>
              </div>
            </div>

            {/* Attachments strip */}
            {selectedNote &&
              (() => {
                const attachmentRegex =
                  /\[([📎🎤][^\]]+)\]\((https?:\/\/[^)]+)\)/g;
                const attachments: {
                  label: string;
                  url: string;
                  raw: string;
                }[] = [];
                let m: RegExpExecArray | null;
                while (
                  (m = attachmentRegex.exec(selectedNote.content)) !== null
                ) {
                  attachments.push({ label: m[1], url: m[2], raw: m[0] });
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

            <div className="flex-1 overflow-y-auto p-6">
              {isPreviewMode ? (
                <div className="prose prose-invert mx-auto max-w-3xl prose-headings:font-bold prose-headings:text-white prose-h1:text-4xl prose-h1:mt-6 prose-h1:mb-4 prose-h2:text-3xl prose-h2:mt-5 prose-h2:mb-3 prose-h3:text-2xl prose-h3:mt-4 prose-h3:mb-3 prose-h4:text-xl prose-h4:mt-3 prose-h4:mb-2 prose-p:leading-relaxed prose-p:text-white/90 prose-p:my-3 prose-strong:text-white prose-strong:font-bold prose-em:text-white/90 prose-em:italic prose-a:text-purple-400 prose-a:underline hover:prose-a:text-purple-300 prose-code:text-pink-400 prose-code:bg-white/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-[''] prose-code:after:content-[''] prose-pre:bg-white/5 prose-pre:border prose-pre:border-white/10 prose-blockquote:border-l-4 prose-blockquote:border-purple-500/50 prose-blockquote:text-white/80 prose-blockquote:pl-4 prose-blockquote:italic prose-ul:text-white/90 prose-ul:my-3 prose-ol:text-white/90 prose-ol:my-3 prose-li:text-white/90 prose-li:my-1">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ children, href, ...props }) => {
                        const text = children?.toString() || "";
                        // Check if this is a file link
                        if (
                          href &&
                          (text.startsWith("📎") || text.startsWith("🎤"))
                        ) {
                          const filename = text.replace(/^[📎🎤]\s*/, "");
                          return (
                            <button
                              onClick={() => handleFileClick(href, filename)}
                              className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-purple-500/10 border border-purple-500/30 text-purple-300 hover:bg-purple-500/20 transition-all text-sm no-underline"
                            >
                              {text}
                            </button>
                          );
                        }
                        return (
                          <a href={href} {...props}>
                            {children}
                          </a>
                        );
                      },
                      h1: ({ children, ...props }) => (
                        <h1
                          className="text-4xl font-bold text-white mt-6 mb-4"
                          {...props}
                        >
                          {children}
                        </h1>
                      ),
                      h2: ({ children, ...props }) => (
                        <h2
                          className="text-3xl font-bold text-white mt-5 mb-3"
                          {...props}
                        >
                          {children}
                        </h2>
                      ),
                      h3: ({ children, ...props }) => (
                        <h3
                          className="text-2xl font-bold text-white mt-4 mb-3"
                          {...props}
                        >
                          {children}
                        </h3>
                      ),
                      h4: ({ children, ...props }) => (
                        <h4
                          className="text-xl font-bold text-white mt-3 mb-2"
                          {...props}
                        >
                          {children}
                        </h4>
                      ),
                      strong: ({ children, ...props }) => (
                        <strong className="font-bold text-white" {...props}>
                          {children}
                        </strong>
                      ),
                      em: ({ children, ...props }) => (
                        <em className="italic text-white/90" {...props}>
                          {children}
                        </em>
                      ),
                    }}
                  >
                    {selectedNote.content || "*Empty note*"}
                  </ReactMarkdown>
                </div>
              ) : (
                <textarea
                  ref={textareaRef}
                  value={selectedNote.content}
                  onChange={(e) => handleContentChange(e.target.value)}
                  placeholder="Start writing..."
                  className="h-full w-full resize-none bg-transparent font-mono text-white placeholder-white/20 focus:outline-none"
                />
              )}
            </div>
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
              onClick={handleCreateNote}
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
                  <a
                    href={filePreview.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
                    title="Open in new tab"
                    aria-label="Open file in new tab"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
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
                {filePreview.type === "audio" && (
                  <div className="flex items-center justify-center">
                    <audio
                      controls
                      src={filePreview.url}
                      className="w-full max-w-2xl"
                    />
                  </div>
                )}
                {filePreview.type === "other" && (
                  <div className="text-center">
                    <p className="mb-4 text-white/60">
                      Preview not available for this file type
                    </p>
                    <a
                      href={filePreview.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-2 rounded-xl bg-linear-to-br from-purple-500 to-pink-500 px-6 py-3 text-white transition-all hover:scale-105"
                    >
                      <ExternalLink className="h-5 w-5" />
                      Open in New Tab
                    </a>
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
