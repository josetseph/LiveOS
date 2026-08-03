"use client";

import React, { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Image as ImageIcon, FileText, Mic, Film } from "lucide-react";
import { api } from "@/lib/api";
import { resolveFileUrl, isImageUrl, isVideoUrl } from "@/lib/utils";
import { BlobMediaPlayer } from "@/components/blob-media-player";

/** Allow entity:// pseudo-links through react-markdown's URL sanitizer. */
function urlTransform(url: string): string {
    if (url.startsWith("entity://")) return url;
    // Reproduce react-markdown's defaultUrlTransform for all other schemes
    return /^(https?|ircs?|mailto|xmpp):/i.test(url) || !url.includes(":") ? url : "";
}

// ── Segment types ────────────────────────────────────────────────────────────

type SegmentType = "text" | "image" | "pdf" | "audio" | "video";

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

    // Split on existing links/markers so attachment links never get nested
    // entity markdown injected into their label or URL.
    const parts = text.split(/(\[[^\]]+\]\([^)]+\)|\[\[[^\]]*\]\])/);
    return parts
        .map((part, i) => {
            if (i % 2 === 1) {
                if (/^\[[^\]]+\]\([^)]+\)$/.test(part)) return part;
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
    /(\[Image:[^\]]+\]|\[PDF Extraction[^\]]*\]:|\[Audio Transcript[^\]]*\]:|\[Video Transcript[^\]]*\]:)/;

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
            } else if (part.includes("Video Transcript")) {
                const m = part.match(/\[Video Transcript\s*\(([^)]+)\)\]/);
                segments.push({
                    type: "video",
                    label: m?.[1]?.trim() || "Video",
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
    video: {
        border: "border-purple-500/30",
        text: "text-purple-300",
        bg: "bg-purple-500/10",
    },
};

const SEGMENT_ICONS: Record<Exclude<SegmentType, "text">, React.ReactNode> = {
    image: <ImageIcon className="h-3.5 w-3.5" />,
    pdf: <FileText className="h-3.5 w-3.5" />,
    audio: <Mic className="h-3.5 w-3.5" />,
    video: <Film className="h-3.5 w-3.5" />,
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

/** Extract display text from react-markdown link children (handles nested nodes). */
function flattenLinkText(children: React.ReactNode): string {
    if (children == null) return "";
    if (typeof children === "string" || typeof children === "number") {
        return String(children);
    }
    if (Array.isArray(children)) {
        return children.map(flattenLinkText).join("");
    }
    if (typeof children === "object" && "props" in children) {
        return flattenLinkText(
            (children as React.ReactElement<{ children?: React.ReactNode }>).props
                .children,
        );
    }
    return "";
}

/** True when href points at an uploaded vault attachment. */
function isAttachmentHref(href: string): boolean {
    return (
        /\/files\//.test(href) ||
        /\/uploads\//.test(href) ||
        /\/vault-files\//.test(href) ||
        /^attachments\//.test(href)
    );
}

// ── Link renderer ─────────────────────────────────────────────────────────────

function makeLinkComponent(
    onFileClick: (url: string, filename: string) => void,
    onEntityClick: ((nodeId: string, name: string) => void) | undefined,
    kbId: string,
) {
    return function LinkComponent({
        children,
        href,
        ...props
    }: React.ComponentPropsWithoutRef<"a"> & { node?: unknown }) {
        const text = flattenLinkText(children).trim();
        const resolvedUrl = href ? resolveFileUrl(href, kbId) : "";
        const isAttachment =
            Boolean(href) &&
            (text.startsWith("📎") || text.startsWith("🎤") || isAttachmentHref(href!));
        const filename =
            text.replace(/^[📎🎤]\s*/, "").trim() ||
            (href ? decodeURIComponent(href.split("/").pop() ?? "file") : "file");

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
        // Inline image/video rendering for 📎 file attachments
        if (href && isAttachment) {
            if (isImageUrl(href) || isImageUrl(resolvedUrl)) {
                return (
                    <span className="block my-4 not-prose">
                        <img
                            src={resolvedUrl}
                            alt={filename}
                            className="max-w-full rounded-xl border border-white/10 cursor-pointer"
                            onClick={() => onFileClick(resolvedUrl, filename)}
                        />
                        <span className="block text-xs text-white/40 mt-1">{filename}</span>
                    </span>
                );
            }
            if (isVideoUrl(href) || isVideoUrl(resolvedUrl)) {
                return (
                    <span className="block my-4 not-prose">
                        <BlobMediaPlayer
                          url={resolvedUrl}
                          kbId={kbId}
                          kind="video"
                          className="max-w-full rounded-xl border border-white/10 bg-black"
                        />
                        <span className="block text-xs text-white/40 mt-1">{filename}</span>
                    </span>
                );
            }
        }
        if (href && isAttachment) {
            return (
                <button
                    onClick={() => onFileClick(resolvedUrl, filename)}
                    className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-purple-500/10 border border-purple-500/30 text-purple-300 hover:bg-purple-500/20 transition-all text-sm no-underline"
                >
                    {text || `📎 ${filename}`}
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

    const segments = useMemo(() => parseSegments(content || "*Empty note*"), [content]);
    const LinkComponent = useMemo(
        () => makeLinkComponent(onFileClick, onEntityClick, kb),
        [onFileClick, onEntityClick, kb],
    );

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
                        {injectEntityLinks(
                            seg.content || (idx === 0 && !seg.content ? "*Empty note*" : ""),
                            scannedEntities,
                        )}
                    </ReactMarkdown>
                </React.Fragment>
            ))}
        </div>
    );
}
