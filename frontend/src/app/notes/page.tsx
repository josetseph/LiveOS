"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Plus, Search, Trash2, Eye, FileText, Loader2, Paperclip, Mic, MicOff, Calendar, X, ExternalLink, Database } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ShaderBackground } from "@/components/shader-background";

interface Note {
  id: string;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
  processed?: boolean;
}

interface FilePreview {
  url: string;
  filename: string;
  type: "image" | "pdf" | "audio" | "other";
}

type ProcessedFilter = "all" | "ingested" | "not-ingested";

export default function NotesPage() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [selectedNote, setSelectedNote] = useState<Note | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [processedFilter, setProcessedFilter] = useState<ProcessedFilter>("all");
  const [isPreviewMode, setIsPreviewMode] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [filePreview, setFilePreview] = useState<FilePreview | null>(null);
  const [showDatePicker, setShowDatePicker] = useState(false);
  const contentBeforeEditRef = useRef<string>("");
  const searchTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // Load draft from localStorage on mount
  useEffect(() => {
    const savedDraft = localStorage.getItem('note-draft');
    if (savedDraft) {
      try {
        const draft = JSON.parse(savedDraft);
        // Add draft to notes list and select it
        setNotes((prevNotes) => [draft, ...prevNotes]);
        setSelectedNote(draft);
        setIsPreviewMode(false);
        contentBeforeEditRef.current = draft.content;
      } catch (error) {
        console.error('Error loading draft:', error);
        localStorage.removeItem('note-draft');
      }
    }
    fetchNotes(undefined, processedFilter);
  }, []);

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

  // Save locally on page unload
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (selectedNote && contentBeforeEditRef.current !== selectedNote.content) {
        handleSaveNote(selectedNote);
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [selectedNote]);

  const fetchNotes = async (search?: string, filter?: ProcessedFilter) => {
    try {
      setIsLoading(true);
      const processed = filter === "ingested" ? true : filter === "not-ingested" ? false : undefined;
      const data = await api.getNotes(search, processed);
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
      const newNote = await api.createNote("", new Date().toISOString());
      
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
      
      // Trigger ingestion for the note
      await api.ingestNote(selectedNote.id);
      
      // Refresh to get updated metadata (processed=true)
      await fetchNotes(searchQuery, processedFilter);
      const updatedNote = await api.getNote(selectedNote.id);
      setSelectedNote(updatedNote);
      contentBeforeEditRef.current = updatedNote.content;
    } catch (error) {
      console.error("Error ingesting note:", error);
      alert("Failed to ingest note. Please try again.");
    } finally {
      setIsSaving(false);
    }
  };

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

  const handleContentChange = (content: string) => {
    if (!selectedNote) return;
    const updatedNote = { ...selectedNote, content };
    setSelectedNote(updatedNote);
  };

  const handleBlur = () => {
    if (selectedNote && selectedNote.content !== contentBeforeEditRef.current) {
      handleSaveNote(selectedNote);
    }
  };

  const handleDeleteNote = async () => {
    if (!selectedNote) return;

    const confirmDelete = window.confirm(`Delete "${selectedNote.title}"?`);
    if (!confirmDelete) return;

    try {
      await api.deleteNote(selectedNote.id);
      setSelectedNote(null);
      await fetchNotes(searchQuery, processedFilter);
    } catch (error) {
      console.error("Error deleting note:", error);
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
        
        // Autosave to localStorage for temp notes
        if (selectedNote.id.startsWith('temp-')) {
          localStorage.setItem('note-draft', JSON.stringify(updatedNote));
        }
        
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
        const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        const audioFile = new File([audioBlob], `recording-${Date.now()}.webm`, { type: "audio/webm" });
        
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
            
            // Autosave to localStorage for temp notes
            if (selectedNote.id.startsWith('temp-')) {
              localStorage.setItem('note-draft', JSON.stringify(updatedNote));
            }
            
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
    
    try {
      // Update note with new created_at date
      const updatedNote = { ...selectedNote, created_at: dateString };
      setSelectedNote(updatedNote);
      setShowDatePicker(false);
      
      // Autosave to localStorage for temp notes
      if (selectedNote.id.startsWith('temp-')) {
        localStorage.setItem('note-draft', JSON.stringify(updatedNote));
      }
    } catch (error) {
      console.error("Error updating date:", error);
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays} days ago`;
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-black">
      <ShaderBackground />
      <div className="relative z-10 flex w-80 flex-col border-r border-white/10 bg-black/50 backdrop-blur-xl">
        <div className="border-b border-white/10 p-4">
          <div className="mb-4 flex items-center justify-between">
            <h1 className="text-xl font-bold text-white">Notes</h1>
            <button
              onClick={handleCreateNote}
              disabled={isSaving}
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 text-white transition-all hover:scale-105 disabled:opacity-50"
            >
              {isSaving ? <Loader2 className="h-5 w-5 animate-spin" /> : <Plus className="h-5 w-5" />}
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
          <div className="flex gap-1 px-2 mt-2">
            <button
              onClick={() => setProcessedFilter("all")}
              className={cn(
                "flex-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                processedFilter === "all"
                  ? "bg-white/10 text-white border border-white/20"
                  : "bg-white/5 text-white/60 border border-transparent hover:bg-white/10"
              )}
            >
              All
            </button>
            <button
              onClick={() => setProcessedFilter("ingested")}
              className={cn(
                "flex-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                processedFilter === "ingested"
                  ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                  : "bg-white/5 text-white/60 border border-transparent hover:bg-white/10"
              )}
            >
              Ingested
            </button>
            <button
              onClick={() => setProcessedFilter("not-ingested")}
              className={cn(
                "flex-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                processedFilter === "not-ingested"
                  ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                  : "bg-white/5 text-white/60 border border-transparent hover:bg-white/10"
              )}
            >
              Drafts
            </button>
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
              {notes.map((note) => (
                <button
                  key={note.id}
                  onClick={() => handleNoteSelect(note)}
                  className={cn(
                    "w-full rounded-xl p-3 text-left transition-all relative",
                    selectedNote?.id === note.id
                      ? "bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-purple-500/30"
                      : "hover:bg-white/5 border border-transparent"
                  )}
                >
                  {/* Ingestion Status Indicator */}
                  <div className="absolute top-3 right-3">
                    {note.processed ? (
                      <div className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]" title="Ingested into brain" />
                    ) : (
                      <div className="h-2 w-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]" title="Draft - not ingested" />
                    )}
                  </div>
                  <h3 className="mb-1 truncate font-medium text-white pr-6">{note.title || "Untitled"}</h3>
                  <p className="truncate text-sm text-white/60">
                    {note.content || "Empty note"}
                  </p>
                  <p className="mt-1 text-xs text-white/40">{formatDate(note.created_at)}</p>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-white/10 p-3">
          <p className="text-xs text-white/40 text-center">
            {notes.length} {notes.length === 1 ? "note" : "notes"}
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
                    <h2 className="text-xl font-bold text-white">{selectedNote.title || "Untitled"}</h2>
                    <p className="text-sm text-white/40 mt-1">
                      {new Date(selectedNote.created_at).toLocaleDateString("en-US", { 
                        month: "long", 
                        day: "numeric", 
                        year: "numeric",
                        hour: "numeric",
                        minute: "2-digit"
                      })}
                    </p>
                  </>
                )}
                {!isPreviewMode && (
                  <>
                    <p className="text-sm text-white/60">
                      {isSaving ? "Saving..." : isUploading ? "Uploading..." : "Saved"}
                    </p>
                    <p className="text-xs text-white/40 mt-0.5">
                      {new Date(selectedNote.created_at).toLocaleDateString("en-US", { 
                        month: "short", 
                        day: "numeric", 
                        year: "numeric",
                        hour: "numeric",
                        minute: "2-digit"
                      })}
                    </p>
                  </>
                )}
              </div>
              <div className="flex items-center gap-2">
                {!isPreviewMode && (
                  <>
                    <button
                      onClick={handleIngestNote}
                      disabled={isSaving || !selectedNote?.content.trim()}
                      className="flex h-9 items-center gap-2 rounded-lg bg-gradient-to-r from-purple-500 to-pink-500 px-4 text-sm font-medium text-white transition-all hover:from-purple-600 hover:to-pink-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isSaving ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Database className="h-4 w-4" />
                      )}
                      {isSaving ? "Ingesting..." : "Ingest Note"}
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
                        isUploading ? "opacity-50 cursor-not-allowed" : "hover:bg-white/10"
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
                          : "border-white/10 bg-white/5 text-white/80 hover:bg-white/10"
                      )}
                    >
                      {isRecording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                      {isRecording ? "Stop" : "Record"}
                    </button>
                  </>
                )}
                <button
                  onClick={() => setShowDatePicker(!showDatePicker)}
                  className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/80 transition-all hover:bg-white/10"
                >
                  <Calendar className="h-4 w-4" />
                  Date
                </button>
                <button
                  onClick={() => setIsPreviewMode(!isPreviewMode)}
                  className={cn(
                    "flex items-center gap-2 rounded-xl px-4 py-2 text-sm transition-all",
                    isPreviewMode
                      ? "bg-gradient-to-br from-purple-500 to-pink-500 text-white"
                      : "border border-white/10 bg-white/5 text-white/80 hover:bg-white/10"
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

            <div className="flex-1 overflow-y-auto p-6">
              {isPreviewMode ? (
                <div className="prose prose-invert mx-auto max-w-3xl prose-headings:font-bold prose-headings:text-white prose-h1:text-4xl prose-h1:mt-6 prose-h1:mb-4 prose-h2:text-3xl prose-h2:mt-5 prose-h2:mb-3 prose-h3:text-2xl prose-h3:mt-4 prose-h3:mb-3 prose-h4:text-xl prose-h4:mt-3 prose-h4:mb-2 prose-p:leading-relaxed prose-p:text-white/90 prose-p:my-3 prose-strong:text-white prose-strong:font-bold prose-em:text-white/90 prose-em:italic prose-a:text-purple-400 prose-a:underline hover:prose-a:text-purple-300 prose-code:text-pink-400 prose-code:bg-white/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-[''] prose-code:after:content-[''] prose-pre:bg-white/5 prose-pre:border prose-pre:border-white/10 prose-blockquote:border-l-4 prose-blockquote:border-purple-500/50 prose-blockquote:text-white/80 prose-blockquote:pl-4 prose-blockquote:italic prose-ul:text-white/90 prose-ul:my-3 prose-ol:text-white/90 prose-ol:my-3 prose-li:text-white/90 prose-li:my-1">
                  <ReactMarkdown 
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ node, children, href, ...props }) => {
                        const text = children?.toString() || "";
                        // Check if this is a file link
                        if (href && (text.startsWith("📎") || text.startsWith("🎤"))) {
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
                        return <a href={href} {...props}>{children}</a>;
                      },
                      h1: ({ node, children, ...props }) => (
                        <h1 className="text-4xl font-bold text-white mt-6 mb-4" {...props}>{children}</h1>
                      ),
                      h2: ({ node, children, ...props }) => (
                        <h2 className="text-3xl font-bold text-white mt-5 mb-3" {...props}>{children}</h2>
                      ),
                      h3: ({ node, children, ...props }) => (
                        <h3 className="text-2xl font-bold text-white mt-4 mb-3" {...props}>{children}</h3>
                      ),
                      h4: ({ node, children, ...props }) => (
                        <h4 className="text-xl font-bold text-white mt-3 mb-2" {...props}>{children}</h4>
                      ),
                      strong: ({ node, children, ...props }) => (
                        <strong className="font-bold text-white" {...props}>{children}</strong>
                      ),
                      em: ({ node, children, ...props }) => (
                        <em className="italic text-white/90" {...props}>{children}</em>
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
            <h2 className="mb-2 text-2xl font-bold text-white">No note selected</h2>
            <p className="mb-6 text-white/60">Select a note from the sidebar or create a new one</p>
            <button
              onClick={handleCreateNote}
              disabled={isSaving}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 px-6 py-3 text-white transition-all hover:scale-105 disabled:opacity-50"
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
                  onClick={() => setShowDatePicker(false)}
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <input
                type="datetime-local"
                defaultValue={new Date(selectedNote.created_at).toISOString().slice(0, 16)}
                onBlur={(e) => {
                  if (e.target.value) {
                    handleDateChange(new Date(e.target.value).toISOString());
                  }
                }}
                className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-white backdrop-blur-xl focus:border-purple-500/50 focus:outline-none"
                autoFocus
              />
              <div className="mt-4 flex justify-end gap-2">
                <button
                  onClick={() => setShowDatePicker(false)}
                  className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/80 transition-all hover:bg-white/10"
                >
                  Close
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
                <h2 className="text-lg font-bold text-white">{filePreview.filename}</h2>
                <div className="flex items-center gap-2">
                  <a
                    href={filePreview.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                  <button
                    onClick={() => setFilePreview(null)}
                    className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>
              <div className="overflow-y-auto p-6" style={{ maxHeight: "calc(90vh - 80px)" }}>
                {filePreview.type === "image" && (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img src={filePreview.url} alt={filePreview.filename} className="mx-auto max-w-full rounded-lg" />
                )}
                {filePreview.type === "pdf" && (
                  <iframe src={filePreview.url} className="h-[70vh] w-full rounded-lg" />
                )}
                {filePreview.type === "audio" && (
                  <div className="flex items-center justify-center">
                    <audio controls src={filePreview.url} className="w-full max-w-2xl" />
                  </div>
                )}
                {filePreview.type === "other" && (
                  <div className="text-center">
                    <p className="mb-4 text-white/60">Preview not available for this file type</p>
                    <a
                      href={filePreview.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 px-6 py-3 text-white transition-all hover:scale-105"
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
