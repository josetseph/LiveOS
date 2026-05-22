"use client";

import React, { useState, useRef, useEffect, useCallback, useMemo } from "react";
import {
  Send,
  User,
  Loader2,
  Sparkles,
  Database,
  Network,
  Cpu,
  X,
  FileText,
  ExternalLink,
  Trash2,
  Search,
  Layers,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import Image from "next/image";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ShaderBackground } from "@/components/shader-background";
import { useKB } from "@/lib/kb-context";
import { useChat } from "@/lib/chat-context";
import type { Message } from "@/lib/chat-context";
import { SegmentedNoteContent } from "@/components/segmented-note-content";
import { EntityDetailPanel } from "@/components/entity-detail-panel";
import type { FilePreview, NotePreview } from "@/lib/types";

type ScannedEntity = { node_id: string; name: string; node_type: string };

/** Scans message text for entity mentions once on mount (result is stable). */
function useScannedEntities(content: string, kb: string): ScannedEntity[] {
  const [entities, setEntities] = useState<ScannedEntity[]>([]);
  useEffect(() => {
    if (!content.trim()) return;
    let cancelled = false;
    api.scanTextEntities(content, kb).then((e) => {
      if (!cancelled) setEntities(e);
    }).catch(() => { });
    return () => { cancelled = true; };
  }, [content, kb]);
  return entities;
}

/** Allow entity:// pseudo-links through react-markdown's URL sanitizer. */
function urlTransform(url: string): string {
  if (url.startsWith("entity://")) return url;
  return /^(https?|ircs?|mailto|xmpp):/i.test(url) || !url.includes(":") ? url : "";
}

/** Injects entity:// pseudo-links directly into plain text for ReactMarkdown.
 * Uses a single-pass range-collection approach so no entity name is ever
 * matched inside an already-injected link (avoids nested/broken markdown). */
function injectEntityLinks(text: string, entities: ScannedEntity[]): string {
  if (!entities.length) return text;
  const sorted = [...entities].sort((a, b) => b.name.length - a.name.length);
  // Collect non-overlapping ranges against the ORIGINAL text, longest-match wins
  const ranges: { start: number; end: number; name: string; node_id: string }[] = [];
  for (const { name, node_id } of sorted) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`\\b${escaped}\\b`, "gi");
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      const start = m.index;
      const end = start + m[0].length;
      if (ranges.some((r) => start < r.end && end > r.start)) continue;
      ranges.push({ start, end, name, node_id });
    }
  }
  // Single left-to-right substitution pass
  ranges.sort((a, b) => a.start - b.start);
  let result = "";
  let last = 0;
  for (const { start, end, name, node_id } of ranges) {
    result += text.slice(last, start);
    result += `[${name}](entity://${node_id})`;
    last = end;
  }
  return result + text.slice(last);
}

/** Prose classes shared by the two inline message renderers. */
const PROSE_CLASSNAME =
  "prose prose-invert max-w-none prose-headings:font-bold prose-headings:text-white prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg prose-p:my-2 prose-p:leading-relaxed prose-p:text-white/90 prose-strong:text-white prose-em:text-white/90 prose-a:text-purple-400 prose-code:text-pink-400 prose-ul:text-white/90 prose-ol:text-white/90 prose-li:text-white/90";

/**
 * Returns a react-markdown `components` map that handles:
 * - entity:// links → clickable entity highlight button
 * - 📎/🎤 links → file/audio attachment buttons
 * - all other anchors → normal <a>
 */
function makeLinkRenderer(
  handleFileClick: (url: string, filename: string) => void,
  onEntityClick?: (nodeId: string, name: string) => void,
) {
  return {
    a: ({
      node: _node,
      children,
      href,
      ...props
    }: React.ComponentPropsWithoutRef<"a"> & { node?: unknown }) => {
      const text = children?.toString() || "";
      if (href?.startsWith("entity://") && onEntityClick) {
        const nodeId = href.slice("entity://".length);
        return (
          <button
            onClick={() => onEntityClick(nodeId, text)}
            className="inline cursor-pointer rounded px-0.5 font-medium text-blue-400 underline decoration-dashed underline-offset-2 transition-colors hover:text-blue-300"
          >
            {text}
          </button>
        );
      }
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
      return (
        <a href={href} {...props}>
          {children}
        </a>
      );
    },
  };
}

/** Renders a single assistant message with entity scanning + highlighting. */
function AssistantMessageBody({
  message,
  kb,
  onEntityClick,
  onFileClick,
  expandedThinking,
  onToggleThinking,
}: {
  message: Message;
  kb: string;
  onEntityClick: (nodeId: string, name: string) => void;
  onFileClick: (url: string, filename: string) => void;
  expandedThinking: Set<string>;
  onToggleThinking: (id: string) => void;
}) {
  const scannedEntities = useScannedEntities(message.content, kb);

  const processContent = useCallback(
    (text: string) => {
      if (!scannedEntities.length) return text;
      return injectEntityLinks(text, scannedEntities);
    },
    [scannedEntities],
  );

  const linkRenderer = useMemo(
    () => makeLinkRenderer(onFileClick, onEntityClick),
    [onFileClick, onEntityClick],
  );

  const refMatch = message.content.match(/###?\s*References[:\s]*\n([\s\S]+?)$/i);

  return (
    <>
      {/* Thinking dropdown */}
      {message.thinking && (
        <div className="mb-3">
          <button
            onClick={() => onToggleThinking(message.id)}
            className="flex items-center gap-1.5 text-xs text-purple-400/80 hover:text-purple-300 transition-colors"
          >
            {expandedThinking.has(message.id) ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
            <span>Model thinking</span>
          </button>
          <AnimatePresence initial={false}>
            {expandedThinking.has(message.id) && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="mt-2 rounded-lg border border-purple-500/20 bg-purple-500/5 px-3 py-2">
                  <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-purple-300/70">
                    {message.thinking}
                  </pre>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* Message body */}
      {refMatch ? (
        <>
          <div className={PROSE_CLASSNAME}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={linkRenderer} urlTransform={urlTransform}>
              {processContent(message.content.substring(0, refMatch.index))}
            </ReactMarkdown>
          </div>
          <div className="mt-4 pt-3 border-t border-white/10">
            <p className="text-sm font-semibold text-white/60 mb-2">References:</p>
            <div className="flex flex-wrap gap-2">
              {refMatch[1]
                .split("\n")
                .map((t) => t.trim())
                .filter((t) => t && !t.match(/^[\*\s]*$/))
                .map((title, i) => {
                  const linkMatch = title.match(/\[([^\]]+)\]\(\/notes\/([^)]+)\)/);
                  if (!linkMatch) return null;
                  return (
                    <button
                      key={i}
                      onClick={() => {
                        const noteId = linkMatch[2];
                        api.getNote(noteId).then((n) =>
                          (window as unknown as { __chatSetPreview?: (n: NotePreview) => void }).__chatSetPreview?.({
                            id: n.id,
                            title: n.title || "Untitled",
                            content: n.content,
                          })
                        ).catch(console.error);
                      }}
                      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-purple-500/10 border border-purple-500/30 text-purple-300 hover:bg-purple-500/20 transition-all text-sm no-underline"
                    >
                      <FileText className="h-3.5 w-3.5" />
                      {linkMatch[1]}
                    </button>
                  );
                })}
            </div>
          </div>
        </>
      ) : (
        <div className={PROSE_CLASSNAME}>
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={linkRenderer} urlTransform={urlTransform}>
            {processContent(message.content)}
          </ReactMarkdown>
        </div>
      )}
    </>
  );
}

export default function ChatPage() {
  const { currentKB, currentKBName } = useKB();
  const { messages, isLoading, sendMessage, clearMessages } = useChat();
  const [input, setInput] = useState("");
  const [previewNote, setPreviewNote] = useState<NotePreview | null>(null);
  const [filePreview, setFilePreview] = useState<FilePreview | null>(null);
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(new Set());
  const [entityPanelNodeId, setEntityPanelNodeId] = useState<string | null>(null);
  const [entityPanelName, setEntityPanelName] = useState<string | undefined>();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Expose setPreviewNote globally so AssistantMessageBody can trigger it without prop drilling
  useEffect(() => {
    (window as unknown as { __chatSetPreview?: unknown }).__chatSetPreview = (n: NotePreview) =>
      setPreviewNote(n);
    return () => { delete (window as unknown as { __chatSetPreview?: unknown }).__chatSetPreview; };
  }, []);

  const handleEntityClick = useCallback((nodeId: string, name: string) => {
    setEntityPanelNodeId(nodeId);
    setEntityPanelName(name);
  }, []);
  const [greeting, setGreeting] = useState("Hello!");
  useEffect(() => {
    const hour = new Date().getHours();
    if (hour < 12) setGreeting("Good morning!");
    else if (hour < 18) setGreeting("Good afternoon!");
    else setGreeting("Good evening!");
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    sendMessage(input, currentKB);
    setInput("");
  };

  const handleNoteReference = async (noteId: string) => {
    try {
      const fullNote = await api.getNote(noteId);
      setPreviewNote({
        id: fullNote.id,
        title: fullNote.title || "Untitled",
        content: fullNote.content,
      });
    } catch (error) {
      console.error("Error fetching note:", error);
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

  const handleClearChat = () => {
    if (window.confirm("Clear all chat messages? This cannot be undone.")) {
      clearMessages();
    }
  };

  const suggestions = [
    "What are my recent thoughts?",
    "Show me my tasks",
    "Summarize my notes",
    "What concepts am I exploring?",
  ];

  return (
    <div className="relative flex h-screen w-full flex-col overflow-hidden bg-black">
      {/* Animated background */}
      <ShaderBackground />

      {/* Header */}
      <div className="relative z-10 border-b border-white/10 bg-black/50 backdrop-blur-xl">
        <div className="mx-auto max-w-4xl px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-linear-to-br from-purple-500 to-pink-500">
                <Image
                  src="/logo-black-background.png"
                  alt="LiveOS"
                  width={40}
                  height={40}
                  loading="eager"
                  className="h-full w-full object-contain"
                />
              </div>
              <div>
                <h1 className="text-xl font-bold text-white">LiveOS</h1>
                <p className="text-xs text-white/60">Your Personal Brain</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {messages.length > 0 && (
                <button
                  onClick={handleClearChat}
                  className="flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs text-red-400 transition-all hover:bg-red-500/20"
                >
                  <Trash2 className="h-3 w-3" />
                  Clear Chat
                </button>
              )}
              {/* Active KB badge */}
              <div className="flex items-center gap-1 rounded-full border border-purple-500/30 bg-purple-500/10 px-3 py-1.5">
                <Database className="h-3 w-3 text-purple-400" />
                <span className="text-xs text-purple-300 font-medium">{currentKBName}</span>
              </div>
              <div className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                <Database className="h-3 w-3 text-green-400" />
                <span className="text-xs text-white/70">Postgres</span>
              </div>
              <div className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                <Network className="h-3 w-3 text-blue-400" />
                <span className="text-xs text-white/70">Kuzu</span>
              </div>
              <div className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                <Layers className="h-3 w-3 text-cyan-400" />
                <span className="text-xs text-white/70">Qdrant</span>
              </div>
              <div className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                <Search className="h-3 w-3 text-yellow-400" />
                <span className="text-xs text-white/70">Typesense</span>
              </div>
              <div className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                <Cpu className="h-3 w-3 text-orange-400" />
                <span className="text-xs text-white/70">RustFS</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Chat Messages */}
      <div className="relative z-10 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-6 py-8">
          {messages.length === 0 ? (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center py-12"
            >
              <Sparkles className="mb-4 h-12 w-12 text-purple-400" />
              <h2 className="mb-2 text-2xl font-bold text-white">{greeting}</h2>
              <p className="mb-8 text-center text-white/60">
                Ask me anything about your notes, thoughts, and knowledge graph
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {suggestions.map((suggestion, index) => (
                  <button
                    key={index}
                    onClick={() => setInput(suggestion)}
                    className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/80 backdrop-blur-xl transition-all hover:border-purple-500/50 hover:bg-white/10"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </motion.div>
          ) : (
            <div className="space-y-6">
              <AnimatePresence>
                {messages.map((message) => (
                  <motion.div
                    key={message.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    className={cn(
                      "flex gap-4",
                      message.role === "user" ? "justify-end" : "justify-start",
                    )}
                  >
                    {message.role === "assistant" && (
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-linear-to-br from-purple-500 to-pink-500">
                        <Sparkles className="h-4 w-4 text-white" />
                      </div>
                    )}
                    <div
                      className={cn(
                        "max-w-[80%] rounded-2xl px-4 py-3",
                        message.role === "user"
                          ? "bg-linear-to-br from-purple-500 to-pink-500 text-white"
                          : "border border-white/10 bg-white/5 text-white backdrop-blur-xl",
                      )}
                    >
                      {message.role === "assistant" ? (
                        <AssistantMessageBody
                          message={message}
                          kb={currentKB}
                          onEntityClick={handleEntityClick}
                          onFileClick={handleFileClick}
                          expandedThinking={expandedThinking}
                          onToggleThinking={(id) =>
                            setExpandedThinking((prev) => {
                              const next = new Set(prev);
                              if (next.has(id)) next.delete(id); else next.add(id);
                              return next;
                            })
                          }
                        />
                      ) : (
                        <p className="whitespace-pre-wrap">{message.content}</p>
                      )}

                    </div>
                    {message.role === "user" && (
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/10">
                        <User className="h-4 w-4 text-white" />
                      </div>
                    )}
                  </motion.div>
                ))}
              </AnimatePresence>
              {isLoading && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="flex gap-4"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-linear-to-br from-purple-500 to-pink-500">
                    <Loader2 className="h-4 w-4 animate-spin text-white" />
                  </div>
                  <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 backdrop-blur-xl">
                    <span className="text-white/60">Thinking...</span>
                  </div>
                </motion.div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="relative z-10 border-t border-white/10 bg-black/50 backdrop-blur-xl">
        <div className="mx-auto max-w-4xl px-6 py-4">
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask me anything..."
              disabled={isLoading}
              className="flex-1 rounded-full border border-white/10 bg-white/5 px-6 py-3 text-white placeholder-white/40 backdrop-blur-xl transition-all focus:border-purple-500/50 focus:outline-none disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              className="flex h-12 w-12 items-center justify-center rounded-full bg-linear-to-br from-purple-500 to-pink-500 text-white transition-all hover:scale-105 disabled:opacity-50 disabled:hover:scale-100"
              title="Send message"
              aria-label="Send message"
            >
              <Send className="h-5 w-5" />
            </button>
          </form>
          <div className="mt-3 flex items-center justify-center gap-2 text-xs text-white/40">
            <span>Powered by</span>
            <span className="font-medium text-purple-400">Gemma3 4B</span>
            <span>•</span>
            <span className="font-medium text-pink-400">Qwen3 Embedding</span>
            <span>•</span>
            <span className="font-medium text-emerald-400">Qwen3 Reranker</span>
            <span>•</span>
            <span className="font-medium text-teal-400">Florence 2</span>
            <span>•</span>
            <span className="font-medium text-amber-400">Whisper V3</span>
          </div>
        </div>
      </div>

      {/* Note Preview Modal */}
      <AnimatePresence>
        {previewNote && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
            onClick={() => setPreviewNote(null)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="relative mx-4 max-h-[80vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-white/10 bg-black/95 shadow-2xl backdrop-blur-xl"
            >
              <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-linear-to-br from-purple-500 to-pink-500">
                    <FileText className="h-5 w-5 text-white" />
                  </div>
                  <h2 className="text-xl font-bold text-white">
                    {previewNote.title}
                  </h2>
                </div>
                <button
                  onClick={() => setPreviewNote(null)}
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
                  title="Close preview"
                  aria-label="Close preview"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="max-h-[calc(80vh-80px)] overflow-y-auto p-6">
                <SegmentedNoteContent
                  content={previewNote.content || "*Empty note*"}
                  onFileClick={handleFileClick}
                  onEntityClick={handleEntityClick}
                  kb={currentKB}
                  proseClassName="prose prose-invert max-w-none prose-headings:font-bold prose-headings:text-white prose-h1:text-4xl prose-h1:mt-6 prose-h1:mb-4 prose-h2:text-3xl prose-h2:mt-5 prose-h2:mb-3 prose-h3:text-2xl prose-h3:mt-4 prose-h3:mb-3 prose-h4:text-xl prose-h4:mt-3 prose-h4:mb-2 prose-p:leading-relaxed prose-p:text-white/90 prose-p:my-3 prose-strong:text-white prose-strong:font-bold prose-em:text-white/90 prose-em:italic prose-a:text-purple-400 prose-a:underline hover:prose-a:text-purple-300 prose-code:text-pink-400 prose-code:bg-white/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-[''] prose-code:after:content-[''] prose-pre:bg-white/5 prose-pre:border prose-pre:border-white/10 prose-blockquote:border-l-4 prose-blockquote:border-purple-500/50 prose-blockquote:text-white/80 prose-blockquote:pl-4 prose-blockquote:italic prose-ul:text-white/90 prose-ul:my-3 prose-ol:text-white/90 prose-ol:my-3 prose-li:text-white/90 prose-li:my-1"
                />
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Entity Detail Panel */}
      <EntityDetailPanel
        nodeId={entityPanelNodeId}
        name={entityPanelName}
        kb={currentKB}
        onClose={() => setEntityPanelNodeId(null)}
      />

      {/* File Preview Modal */}
      <AnimatePresence>
        {filePreview && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
            onClick={() => setFilePreview(null)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="relative mx-4 max-h-[90vh] w-full max-w-6xl overflow-hidden rounded-2xl border border-white/10 bg-black/95 shadow-2xl backdrop-blur-xl"
            >
              <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-linear-to-br from-purple-500 to-pink-500">
                    <FileText className="h-5 w-5 text-white" />
                  </div>
                  <h2 className="text-lg font-semibold text-white">
                    {filePreview.filename}
                  </h2>
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href={filePreview.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex h-8 items-center gap-1.5 rounded-lg bg-purple-500/20 px-3 text-sm text-purple-300 transition-all hover:bg-purple-500/30"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <ExternalLink className="h-4 w-4" />
                    Open
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
                    className="max-h-full max-w-full rounded-lg"
                  />
                )}
                {filePreview.type === "pdf" && (
                  <iframe
                    src={filePreview.url}
                    className="h-[calc(90vh-160px)] w-full rounded-lg"
                    title={filePreview.filename}
                  />
                )}
                {filePreview.type === "audio" && (
                  <div className="flex min-h-50 items-center justify-center">
                    <audio
                      controls
                      src={filePreview.url}
                      className="w-full max-w-2xl"
                    >
                      Your browser does not support the audio element.
                    </audio>
                  </div>
                )}
                {filePreview.type === "other" && (
                  <div className="flex min-h-50 flex-col items-center justify-center gap-4 text-white/60">
                    <FileText className="h-16 w-16" />
                    <p>Preview not available for this file type</p>
                    <a
                      href={filePreview.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-lg bg-purple-500/20 px-4 py-2 text-purple-300 transition-all hover:bg-purple-500/30"
                    >
                      Download File
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
