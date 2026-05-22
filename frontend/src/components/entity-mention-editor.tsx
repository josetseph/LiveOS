"use client";

import {
    useRef,
    useState,
    useCallback,
    useEffect,
    forwardRef,
    useImperativeHandle,
} from "react";
import { api } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface EntitySuggestion {
    node_id: string;
    name: string;
    node_type: string;
}

export interface EntityMentionEditorProps {
    value: string;
    onChange: (value: string) => void;
    onEntityClick?: (nodeId: string, name: string) => void;
    kb?: string;
    placeholder?: string;
    className?: string;
}

export interface EntityMentionEditorHandle {
    /** Insert text at the current cursor position (used by file/audio attachment). */
    insertAtCursor: (text: string) => void;
    focus: () => void;
    /** The underlying textarea element (for compatibility). */
    textarea: HTMLTextAreaElement | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function escapeHtml(text: string): string {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function escapeAttr(text: string): string {
    return text.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function escapeRegex(text: string): string {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Build the HTML for the overlay mirror div.
 * Highlights entity names found by scanTextEntities as blue spans.
 * The text rendered here must match the textarea content character-for-character
 * so that the visual layer aligns with the cursor.
 */
function buildHighlightedHtml(
    content: string,
    scannedEntities: EntitySuggestion[],
): string {
    if (scannedEntities.length === 0) return escapeHtml(content);

    // Collect all match ranges across all entities
    const ranges: { start: number; end: number; entity: EntitySuggestion }[] = [];
    for (const entity of scannedEntities) {
        const re = new RegExp(`\\b${escapeRegex(entity.name)}\\b`, "gi");
        let m: RegExpExecArray | null;
        while ((m = re.exec(content)) !== null) {
            ranges.push({ start: m.index, end: m.index + entity.name.length, entity });
        }
    }

    // Sort by start position, skip overlapping ranges
    ranges.sort((a, b) => a.start - b.start);

    let out = "";
    let last = 0;
    for (const r of ranges) {
        if (r.start < last) continue;
        out += escapeHtml(content.slice(last, r.start));
        out += `<span class="entity-scanned" data-node-id="${escapeAttr(r.entity.node_id)}" data-name="${escapeAttr(r.entity.name)}">${escapeHtml(content.slice(r.start, r.end))}</span>`;
        last = r.end;
    }
    out += escapeHtml(content.slice(last));
    return out;
}


/**
 * Extract the word the user is currently typing (at the given cursor position).
 * Stops at whitespace and special characters. Returns null if < minLength chars.
 */
function getCurrentWord(
    text: string,
    cursorPos: number,
    minLength = 3,
): { word: string; start: number; end: number } | null {
    let start = cursorPos;
    while (start > 0 && /\S/.test(text[start - 1])) {
        start--;
    }
    let end = cursorPos;
    while (end < text.length && /\S/.test(text[end])) {
        end++;
    }
    const word = text.slice(start, cursorPos);
    if (word.length < minLength) return null;
    return { word, start, end };
}

// ── Component ─────────────────────────────────────────────────────────────────

const EntityMentionEditor = forwardRef<
    EntityMentionEditorHandle,
    EntityMentionEditorProps
>(function EntityMentionEditor(
    { value, onChange, onEntityClick, kb = "default", placeholder, className },
    ref,
) {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const mirrorRef = useRef<HTMLDivElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const [suggestions, setSuggestions] = useState<EntitySuggestion[]>([]);
    const [showSuggestions, setShowSuggestions] = useState(false);
    const [selectedIdx, setSelectedIdx] = useState(0);
    const [currentWordMeta, setCurrentWordMeta] = useState<{
        word: string;
        start: number;
        end: number;
    } | null>(null);
    const [scannedEntities, setScannedEntities] = useState<EntitySuggestion[]>(
        [],
    );
    const [dropdownTop, setDropdownTop] = useState<number | null>(null);

    // ── Expose imperative handle so parent can insert text ──────────────────
    useImperativeHandle(ref, () => ({
        insertAtCursor(text: string) {
            const ta = textareaRef.current;
            if (!ta) return;
            const start = ta.selectionStart;
            const end = ta.selectionEnd;
            const newValue = value.slice(0, start) + text + value.slice(end);
            onChange(newValue);
            setTimeout(() => {
                ta.focus();
                const pos = start + text.length;
                ta.setSelectionRange(pos, pos);
            }, 0);
        },
        focus() {
            textareaRef.current?.focus();
        },
        get textarea() {
            return textareaRef.current;
        },
    }));

    // ── Sync overlay scroll with textarea scroll ─────────────────────────────
    const syncScroll = useCallback(() => {
        const ta = textareaRef.current;
        const mirror = mirrorRef.current;
        if (ta && mirror) {
            mirror.scrollTop = ta.scrollTop;
            mirror.scrollLeft = ta.scrollLeft;
        }
    }, []);

    // ── Scan existing note text for entity mentions on load ──────────────────
    useEffect(() => {
        if (!value || value.length < 10) return;
        let cancelled = false;
        api
            .scanTextEntities(value, kb)
            .then((entities) => {
                if (!cancelled) setScannedEntities(entities);
            })
            .catch(() => {
                // Silently fail — scan is best-effort
            });
        return () => {
            cancelled = true;
        };
        // Only run on initial load (value is stable at that point) or KB change
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [kb]);

    // ── Debounced entity search ──────────────────────────────────────────────
    const triggerSearch = useCallback(
        (word: string, wordStart: number, wordEnd: number) => {
            if (searchTimeoutRef.current)
                clearTimeout(searchTimeoutRef.current);
            searchTimeoutRef.current = setTimeout(async () => {
                try {
                    const results = await api.searchEntities(word, kb, 6);
                    if (results.length > 0) {
                        setSuggestions(results);
                        setSelectedIdx(0);
                        setCurrentWordMeta({ word, start: wordStart, end: wordEnd });
                        setShowSuggestions(true);
                    } else {
                        setShowSuggestions(false);
                    }
                } catch {
                    setShowSuggestions(false);
                }
            }, 250);
        },
        [kb],
    );

    // ── Handle textarea input ────────────────────────────────────────────────
    const handleChange = useCallback(
        (e: React.ChangeEvent<HTMLTextAreaElement>) => {
            const newValue = e.target.value;
            onChange(newValue);

            const cursorPos = e.target.selectionStart;
            const wordMeta = getCurrentWord(newValue, cursorPos);
            if (wordMeta) {
                triggerSearch(wordMeta.word, wordMeta.start, wordMeta.end);
            } else {
                setShowSuggestions(false);
            }
        },
        [onChange, triggerSearch],
    );

    // ── Accept a suggestion ──────────────────────────────────────────────────
    const acceptSuggestion = useCallback(
        (suggestion: EntitySuggestion) => {
            if (!currentWordMeta) return;
            const { start } = currentWordMeta;
            const cursorPos = textareaRef.current?.selectionStart ?? start + currentWordMeta.word.length;
            // Insert the plain entity name (no special markers)
            const newValue =
                value.slice(0, start) + suggestion.name + value.slice(cursorPos);
            onChange(newValue);
            setShowSuggestions(false);
            setSuggestions([]);
            setCurrentWordMeta(null);
            // Move cursor to end of inserted name
            setTimeout(() => {
                const ta = textareaRef.current;
                if (ta) {
                    ta.focus();
                    const pos = start + suggestion.name.length;
                    ta.setSelectionRange(pos, pos);
                }
            }, 0);
        },
        [value, onChange, currentWordMeta],
    );

    // ── Keyboard navigation for suggestion dropdown ──────────────────────────
    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
            if (!showSuggestions || suggestions.length === 0) return;

            if (e.key === "ArrowDown") {
                e.preventDefault();
                setSelectedIdx((i) => Math.min(i + 1, suggestions.length - 1));
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSelectedIdx((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter" || e.key === "Tab") {
                e.preventDefault();
                acceptSuggestion(suggestions[selectedIdx]);
            } else if (e.key === "Escape") {
                e.preventDefault();
                setShowSuggestions(false);
            }
        },
        [showSuggestions, suggestions, selectedIdx, acceptSuggestion],
    );

    // ── Click on highlighted entity span in the OVERLAY ─────────────────────
    // (overlay is pointer-events:none but we handle clicks on the textarea
    //  by inspecting what span would be under the cursor via data attributes
    //  exposed in the mirror — see onClick below)
    const handleTextareaClick = useCallback(
        (e: React.MouseEvent<HTMLTextAreaElement>) => {
            // Close suggestions on click-away
            setShowSuggestions(false);

            // Entity click-through: find corresponding position in the mirror
            // We check if the click coords overlap any entity span in the mirror
            const mirror = mirrorRef.current;
            if (!mirror || !onEntityClick) return;
            const spans = mirror.querySelectorAll<HTMLSpanElement>(
                "[data-node-id]",
            );
            const { clientX, clientY } = e;
            for (const span of spans) {
                const rect = span.getBoundingClientRect();
                if (
                    clientX >= rect.left &&
                    clientX <= rect.right &&
                    clientY >= rect.top &&
                    clientY <= rect.bottom
                ) {
                    const nodeId = span.dataset.nodeId!;
                    const name = span.dataset.name!;
                    onEntityClick(nodeId, name);
                    break;
                }
            }
        },
        [onEntityClick],
    );

    // ── Compute dropdown position ────────────────────────────────────────────
    useEffect(() => {
        if (!showSuggestions || !containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        setDropdownTop(rect.height);
    }, [showSuggestions]);

    // ── Highlighted overlay HTML ─────────────────────────────────────────────
    const highlightedHtml = buildHighlightedHtml(value, scannedEntities);

    return (
        <div ref={containerRef} className={`relative h-full ${className ?? ""}`}>
            {/* ── Style block for entity highlights ── */}
            <style>{`
        .entity-explicit {
          background-color: rgba(96, 165, 250, 0.25);
          color: #93c5fd;
          border-radius: 3px;
          padding: 0 2px;
          border-bottom: 1px solid rgba(147, 197, 253, 0.5);
          cursor: pointer;
        }
        .entity-scanned {
          background-color: rgba(139, 92, 246, 0.15);
          color: #c4b5fd;
          border-radius: 3px;
          padding: 0 2px;
          border-bottom: 1px dashed rgba(196, 181, 253, 0.4);
          cursor: pointer;
        }
      `}</style>

            {/* ── Mirror overlay (visual layer) ── */}
            <div
                ref={mirrorRef}
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 overflow-auto whitespace-pre-wrap break-words font-mono text-sm leading-relaxed"
                style={{
                    // Exact same padding/font as the textarea
                    padding: "0",
                    fontSize: "inherit",
                    lineHeight: "inherit",
                    fontFamily: "inherit",
                    wordBreak: "break-word",
                    // Text is rendered here; textarea text is transparent
                }}
                dangerouslySetInnerHTML={{ __html: highlightedHtml }}
            />

            {/* ── Actual textarea (transparent text, caret visible) ── */}
            <textarea
                ref={textareaRef}
                value={value}
                onChange={handleChange}
                onKeyDown={handleKeyDown}
                onScroll={syncScroll}
                onClick={handleTextareaClick}
                placeholder={placeholder}
                className="absolute inset-0 h-full w-full resize-none bg-transparent font-mono focus:outline-none"
                style={{
                    color: "transparent",
                    caretColor: "white",
                    fontSize: "inherit",
                    lineHeight: "inherit",
                    fontFamily: "inherit",
                    padding: "0",
                    wordBreak: "break-word",
                }}
                spellCheck={false}
            />

            {/* ── Autocomplete dropdown ── */}
            {showSuggestions && suggestions.length > 0 && (
                <div
                    className="absolute left-0 right-0 z-50 mt-1 overflow-hidden rounded-xl border border-white/15 bg-black/95 shadow-2xl backdrop-blur-xl"
                    style={{ top: dropdownTop ?? "auto" }}
                    onMouseDown={(e) => e.preventDefault()} // prevent textarea blur
                >
                    <div className="px-3 py-2 border-b border-white/10">
                        <p className="text-xs text-white/40">Entity suggestions</p>
                    </div>
                    {suggestions.map((suggestion, idx) => (
                        <button
                            key={suggestion.node_id}
                            type="button"
                            onMouseDown={(e) => {
                                e.preventDefault();
                                acceptSuggestion(suggestion);
                            }}
                            className={`flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors ${idx === selectedIdx
                                    ? "bg-blue-500/20"
                                    : "hover:bg-white/5"
                                }`}
                        >
                            <span
                                className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                                style={{
                                    backgroundColor: "rgba(96, 165, 250, 0.15)",
                                    color: "#93c5fd",
                                    border: "1px solid rgba(96, 165, 250, 0.25)",
                                }}
                            >
                                {suggestion.node_type || "entity"}
                            </span>
                            <span className="truncate text-sm font-medium text-white">
                                {suggestion.name}
                            </span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
});

export default EntityMentionEditor;
