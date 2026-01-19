"use client";

import React, { useState, useRef, useEffect } from "react";
import { Send, User, Loader2, Sparkles, Database, Network, Cpu, Brain, X, FileText, ExternalLink, Trash2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ShaderBackground } from "@/components/shader-background";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface NotePreview {
  id: string;
  title: string;
  content: string;
}

interface FilePreview {
  url: string;
  filename: string;
  type: "image" | "pdf" | "audio" | "other";
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [previewNote, setPreviewNote] = useState<NotePreview | null>(null);
  const [filePreview, setFilePreview] = useState<FilePreview | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
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

  // Load messages from sessionStorage on mount
  useEffect(() => {
    const savedMessages = sessionStorage.getItem("chat-messages");
    if (savedMessages) {
      try {
        const parsed = JSON.parse(savedMessages);
        setMessages(parsed.map((m: any) => ({ ...m, timestamp: new Date(m.timestamp) })));
      } catch (error) {
        console.error("Error loading chat messages:", error);
      }
    }
  }, []);

  // Save messages to sessionStorage whenever they change
  useEffect(() => {
    if (messages.length > 0) {
      sessionStorage.setItem("chat-messages", JSON.stringify(messages));
    }
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      const response = await api.chat(input);
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: response.answer || "I couldn't generate a response.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      console.error("Chat error:", error);
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: "Sorry, I encountered an error. Please try again.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleNoteReference = async (noteId: string) => {
    try {
      console.log('Fetching note with ID:', noteId);
      const fullNote = await api.getNote(noteId);
      console.log('Note fetched:', fullNote);
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
      setMessages([]);
      sessionStorage.removeItem("chat-messages");
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
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500 to-pink-500">
                <img src="/logo-black-background.png" alt="LiveOS" className="h-24 w-24 object-contain" />
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
              <div className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                <Database className="h-3 w-3 text-green-400" />
                <span className="text-xs text-white/70">Postgres</span>
              </div>
              <div className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                <Network className="h-3 w-3 text-blue-400" />
                <span className="text-xs text-white/70">Neo4j</span>
              </div>
              <div className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                <Cpu className="h-3 w-3 text-orange-400" />
                <span className="text-xs text-white/70">MinIO</span>
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
                      message.role === "user" ? "justify-end" : "justify-start"
                    )}
                  >
                    {message.role === "assistant" && (
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-pink-500">
                        <Sparkles className="h-4 w-4 text-white" />
                      </div>
                    )}
                    <div
                      className={cn(
                        "max-w-[80%] rounded-2xl px-4 py-3",
                        message.role === "user"
                          ? "bg-gradient-to-br from-purple-500 to-pink-500 text-white"
                          : "border border-white/10 bg-white/5 text-white backdrop-blur-xl"
                      )}
                    >
                      {message.role === "assistant" ? (
                        <>
                          {(() => {
                            // Check if message contains References section (### References or References:)
                            const refMatch = message.content.match(/###?\s*References[:\s]*\n([\s\S]+?)$/i);
                            if (refMatch) {
                              const beforeRefs = message.content.substring(0, refMatch.index);
                              const refsList = refMatch[1];
                              const titles = refsList
                                .split('\n')
                                .map(t => t.trim())
                                .filter(t => t && !t.match(/^[\*\s]*$/));
                              
                              return (
                                <>
                                  <div className="prose prose-invert max-w-none prose-headings:font-bold prose-headings:text-white prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg prose-p:my-2 prose-p:leading-relaxed prose-p:text-white/90 prose-strong:text-white prose-em:text-white/90 prose-a:text-purple-400 prose-code:text-pink-400 prose-ul:text-white/90 prose-ol:text-white/90 prose-li:text-white/90">
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
                                          
                                          // Regular links
                                          return <a href={href} {...props}>{children}</a>;
                                        },
                                      }}
                                    >
                                      {beforeRefs}
                                    </ReactMarkdown>
                                  </div>
                                  <div className="mt-4 pt-3 border-t border-white/10">
                                    <p className="text-sm font-semibold text-white/60 mb-2">References:</p>
                                    <div className="flex flex-wrap gap-2">
                                      {titles.map((title, i) => {
                                        // Extract note ID from markdown link format: - [Title](/notes/id)
                                        const linkMatch = title.match(/\[([^\]]+)\]\(\/notes\/([^)]+)\)/);
                                        if (!linkMatch) return null;
                                        
                                        const noteTitle = linkMatch[1];
                                        const noteId = linkMatch[2];
                                        
                                        return (
                                          <button
                                            key={i}
                                            onClick={() => {
                                              console.log('Clicked note:', noteTitle, 'ID:', noteId);
                                              handleNoteReference(noteId);
                                            }}
                                            className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-purple-500/10 border border-purple-500/30 text-purple-300 hover:bg-purple-500/20 transition-all text-sm no-underline"
                                          >
                                            <FileText className="h-3.5 w-3.5" />
                                            {noteTitle}
                                          </button>
                                        );
                                      })}
                                    </div>
                                  </div>
                                </>
                              );
                            }
                            
                            // No references, just render markdown normally
                            return (
                              <div className="prose prose-invert max-w-none prose-headings:font-bold prose-headings:text-white prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg prose-p:my-2 prose-p:leading-relaxed prose-p:text-white/90 prose-strong:text-white prose-em:text-white/90 prose-a:text-purple-400 prose-code:text-pink-400 prose-ul:text-white/90 prose-ol:text-white/90 prose-li:text-white/90">
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
                                      
                                      // Regular links
                                      return <a href={href} {...props}>{children}</a>;
                                    },
                                  }}
                                >
                                  {message.content}
                                </ReactMarkdown>
                              </div>
                            );
                          })()}
                        </>
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
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-pink-500">
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
              className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-purple-500 to-pink-500 text-white transition-all hover:scale-105 disabled:opacity-50 disabled:hover:scale-100"
            >
              <Send className="h-5 w-5" />
            </button>
          </form>
          <div className="mt-3 flex items-center justify-center gap-2 text-xs text-white/40">
            <span>Powered by</span>
            <span className="font-medium text-purple-400">Gemma3 12B</span>
            <span>•</span>
            <span className="font-medium text-pink-400">Qwen3 Embedding</span>
            <span>•</span>
            <span className="font-medium text-cyan-400">MxBai Reranker</span>
            <span>•</span>
            <span className="font-medium text-emerald-400">DeepSeek OCR</span>
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
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-pink-500">
                    <FileText className="h-5 w-5 text-white" />
                  </div>
                  <h2 className="text-xl font-bold text-white">{previewNote.title}</h2>
                </div>
                <button
                  onClick={() => setPreviewNote(null)}
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="overflow-y-auto p-6" style={{ maxHeight: "calc(80vh - 80px)" }}>
                <div className="prose prose-invert max-w-none prose-headings:font-bold prose-headings:text-white prose-h1:text-4xl prose-h1:mt-6 prose-h1:mb-4 prose-h2:text-3xl prose-h2:mt-5 prose-h2:mb-3 prose-h3:text-2xl prose-h3:mt-4 prose-h3:mb-3 prose-h4:text-xl prose-h4:mt-3 prose-h4:mb-2 prose-p:leading-relaxed prose-p:text-white/90 prose-p:my-3 prose-strong:text-white prose-strong:font-bold prose-em:text-white/90 prose-em:italic prose-a:text-purple-400 prose-a:underline hover:prose-a:text-purple-300 prose-code:text-pink-400 prose-code:bg-white/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-[''] prose-code:after:content-[''] prose-pre:bg-white/5 prose-pre:border prose-pre:border-white/10 prose-blockquote:border-l-4 prose-blockquote:border-purple-500/50 prose-blockquote:text-white/80 prose-blockquote:pl-4 prose-blockquote:italic prose-ul:text-white/90 prose-ul:my-3 prose-ol:text-white/90 prose-ol:my-3 prose-li:text-white/90 prose-li:my-1">
                  <ReactMarkdown 
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ node, children, href, ...props }) => {
                        const text = children?.toString() || "";
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
                    {previewNote.content || "*Empty note*"}
                  </ReactMarkdown>
                </div>
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
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-pink-500">
                    <FileText className="h-5 w-5 text-white" />
                  </div>
                  <h2 className="text-lg font-semibold text-white">{filePreview.filename}</h2>
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
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>
              <div className="overflow-y-auto p-6" style={{ maxHeight: "calc(90vh - 80px)" }}>
                {filePreview.type === "image" && (
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
                  <div className="flex min-h-[200px] items-center justify-center">
                    <audio controls src={filePreview.url} className="w-full max-w-2xl">
                      Your browser does not support the audio element.
                    </audio>
                  </div>
                )}
                {filePreview.type === "other" && (
                  <div className="flex min-h-[200px] flex-col items-center justify-center gap-4 text-white/60">
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
