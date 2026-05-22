"use client";

import React, { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Image as ImageIcon, FileText, Mic } from "lucide-react";
import { api } from "@/lib/api";

/** Allow entity:// pseudo-links through react-markdown's URL sanitizer. */
function urlTransform(url: string): string {
    if (url.startsWith("entity://")) return url;
    // Reproduce react-markdown's defaultUrlTransform for all other schemes
    return /^(https?|ircs?|mailto|xmpp):/i.test(url) || !url.includes(":") ? url : "";
}

// ── Segment types ────────────────────────────────────────────────────────────

type SegmentType = "text" | "image" | "pdf" | "audio";

interface Segment {
    type: SegmentType;
    label: string; // e.g. "Votex 365 Ad", "Offer Letter.pdf", "Voice Recording"
    content: string;
}

// ── Entity mention helpers ───────────────────────────────────────────────────

type ScannedEntity = { node_id: string; name: string; node_type: string };

function escapeRegex(s: string) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Injects entity:// pseudo-links directly into plain text for scanned entities.
 * Uses a single-pass range-collection approach so no entity name is ever
 * matched inside an already-injected link (avoids nested/broken markdown).
 */
function injectEntityLinks(text: string, entities: ScannedEntity[]): string {
    if (!entities.length) return text;
    const sorted = [...entities].sort((a, b) => b.name.length - a.name.length);

    function replacePlain(plain: string): string {
        // Collect non-overlapping ranges against the ORIGINAL text, longest-match wins
        const ranges: { start: number; end: number; name: string; node_id: string }[] = [];
        for (const { name, node_id } of sorted) {
            const re = new RegExp(`\\b${escapeRegex(name)}\\b`, "gi");
            let m: RegExpExecArray | null;
            while ((m = re.exec(plain)) !== null) {
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
            result += plain.slice(last, start);
            result += `[${name}](entity://${node_id})`;
            last = end;
        }
        return result + plain.slice(last);
    }

    // Split on existing [[name|id]] markers (backward compat) — never double-process them
    const parts = text.split(/(\[\[[^\]]*\]\])/);
    return parts
        .map((part, i) => {
            if (i % 2 === 1) {
                const m = part.match(/\[\[([^\]|]+)\|([^\]]+)\]\]/);
                return m ? `[${m[1]}](entity://${m[2]})` : part;
            }
            return replacePlain(part);
        })
        .join("");
}

// ── Marker parser ────────────────────────────────────────────────────────────
// Recognises:
//   [Image: <title>]
//   [PDF Extraction (<filename>)]:
//   [Audio Transcript (<title>)]:

const MARKER_RE =
    /(\[Image:[^\]]+\]|\[PDF Extraction[^\]]*\]:|\[Audio Transcript[^\]]*\]:)/;

function parseSegments(content: string): Segment[] {
    const parts = content.split(MARKER_RE);
    const segments: Segment[] = [];

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        if (!part) continue;

        if (i % 2 === 0) {
            // Plain text (before/between/after markers)
            const trimmed = part.trim();
            if (trimmed) segments.push({ type: "text", label: "", content: trimmed });
        } else {
            // This is the marker itself
            const body = parts[i + 1] ?? "";
            i++; // consume the content part

            if (part.startsWith("[Image:")) {
                const m = part.match(/\[Image:\s*([^\]]+)\]/);
                segments.push({
                    type: "image",
                    label: m?.[1]?.trim() || "Image",
                    content: body.trim(),
                });
            } else if (part.includes("PDF Extraction")) {
                const m = part.match(/\[PDF Extraction\s*\(([^)]+)\)\]/);
                segments.push({
                    type: "pdf",
                    label: m?.[1]?.trim() || "PDF",
                    content: body.trim(),
                });
            } else if (part.includes("Audio Transcript")) {
                const m = part.match(/\[Audio Transcript\s*\(([^)]+)\)\]/);
                segments.push({
                    type: "audio",
                    label: m?.[1]?.trim() || "Audio",
                    content: body.trim(),
                });
            }
        }
    }

    return segments;
}

// ── Divider header ────────────────────────────────────────────────────────────

const SEGMENT_STYLES: Record<
    Exclude<SegmentType, "text">,
    { border: string; text: string; bg: string }
> = {
    image: {
        border: "border-blue-500/30",
        text: "text-blue-300",
        bg: "bg-blue-500/10",
    },
    pdf: {
        border: "border-amber-500/30",
        text: "text-amber-300",
        bg: "bg-amber-500/10",
    },
    audio: {
        border: "border-emerald-500/30",
        text: "text-emerald-300",
        bg: "bg-emerald-500/10",
    },
};

const SEGMENT_ICONS: Record<Exclude<SegmentType, "text">, React.ReactNode> = {
    image: <ImageIcon className="h-3.5 w-3.5" />,
    pdf: <FileText className="h-3.5 w-3.5" />,
    audio: <Mic className="h-3.5 w-3.5" />,
};

function SegmentDivider({
    type,
    label,
}: {
    type: Exclude<SegmentType, "text">;
    label: string;
}) {
    const s = SEGMENT_STYLES[type];
    return (
        <div className="flex items-center gap-3 my-4 not-prose">
            <div className="h-px flex-1 bg-white/10" />
            <div
                className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${s.border} ${s.text} ${s.bg}`}
            >
                {SEGMENT_ICONS[type]}
                <span className="max-w-[280px] truncate">{label}</span>
            </div>
            <div className="h-px flex-1 bg-white/10" />
        </div>
    );
}

// ── Link renderer ─────────────────────────────────────────────────────────────

function makeLinkComponent(
    onFileClick: (url: string, filename: string) => void,
    onEntityClick?: (nodeId: string, name: string) => void,
) {
    return function LinkComponent({
        children,
        href,
        ...props
    }: React.ComponentPropsWithoutRef<"a"> & { node?: unknown }) {
        const text = children?.toString() || "";
        // Entity mention pseudo-link: entity://node_id
        if (href?.startsWith("entity://")) {
            const nodeId = href.slice("entity://".length);
            return (
                <button
                    type="button"
                    onClick={() => onEntityClick?.(nodeId, text)}
                    className="inline-block rounded px-1 py-0.5 text-blue-300 bg-blue-500/15 border border-blue-500/20 hover:bg-blue-500/25 transition-colors cursor-pointer no-underline font-medium"
                    style={{ textDecoration: "none" }}
                >
                    {text}
                </button>
            );
        }
        if (href && (text.startsWith("📎") || text.startsWith("🎤"))) {
            const filename = text.replace(/^[📎🎤]\s*/, "");
            return (
                <button
                    onClick={() => onFileClick(href, filename)}
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
    };
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
    content: string;
    onFileClick: (url: string, filename: string) => void;
    onEntityClick?: (nodeId: string, name: string) => void;
    proseClassName: string;
    /** Knowledge base key used to scan for entity mentions. Defaults to "default". */
    kb?: string;
}

export function SegmentedNoteContent({
    content,
    onFileClick,
    onEntityClick,
    proseClassName,
    kb = "default",
}: Props) {
    const [scannedEntities, setScannedEntities] = useState<ScannedEntity[]>([]);

    useEffect(() => {
        if (!content?.trim() || !onEntityClick) return;
        let cancelled = false;
        api.scanTextEntities(content, kb)
            .then((e) => { if (!cancelled) setScannedEntities(e); })
            .catch(() => { });
        return () => { cancelled = true; };
    }, [content, kb, onEntityClick]);

    const processed = useMemo(() => {
        return injectEntityLinks(content || "", scannedEntities);
    }, [content, scannedEntities]);

    const segments = parseSegments(processed || "*Empty note*");
    const LinkComponent = makeLinkComponent(onFileClick, onEntityClick);

    return (
        <div className={proseClassName}>
            {segments.map((seg, idx) => (
                <React.Fragment key={idx}>
                    {seg.type !== "text" && (
                        <SegmentDivider
                            type={seg.type as Exclude<SegmentType, "text">}
                            label={seg.label}
                        />
                    )}
                    <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{ a: LinkComponent }}
                        urlTransform={urlTransform}
                    >
                        {seg.content || (idx === 0 && !seg.content ? "*Empty note*" : "")}
                    </ReactMarkdown>
                </React.Fragment>
            ))}
        </div>
    );
}
