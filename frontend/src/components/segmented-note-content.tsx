"use client";

import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Image as ImageIcon, FileText, Mic, Film } from "lucide-react";
import { resolveFileUrl, isImageUrl, isVideoUrl, isPdfUrl } from "@/lib/utils";
import { BlobMediaPlayer } from "@/components/blob-media-player";
import {
    MarkdownAnchor,
    flattenLinkText,
    injectEntityLinks,
    isAttachmentHref,
    urlTransform,
    useScannedEntities,
} from "@/lib/markdown-entities";

// ── Segment types ────────────────────────────────────────────────────────────

type SegmentType = "text" | "image" | "pdf" | "audio" | "video";

interface Segment {
    type: SegmentType;
    label: string; // e.g. "Votex 365 Ad", "Offer Letter.pdf", "Voice Recording"
    content: string;
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
            (text.startsWith("📎") ||
                text.startsWith("🖇") ||
                text.startsWith("🎤") ||
                isAttachmentHref(href!));
        const filename =
            text.replace(/^[📎🖇🎤]\s*/, "").trim() ||
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
        // Inline image/video/PDF rendering for 📎 file attachments
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
            if (isPdfUrl(href) || isPdfUrl(resolvedUrl)) {
                return (
                    <span className="block my-4 not-prose">
                        <iframe
                            src={resolvedUrl}
                            title={filename}
                            className="h-[480px] max-h-[70vh] w-full max-w-3xl rounded-xl border border-white/10 bg-black/40"
                        />
                        <button
                            type="button"
                            onClick={() => onFileClick(resolvedUrl, filename)}
                            className="mt-1 block text-xs text-white/40 hover:text-white/70"
                        >
                            {filename} — open full preview
                        </button>
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
            <MarkdownAnchor href={href} {...props}>
                {children}
            </MarkdownAnchor>
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
    const scannedEntities = useScannedEntities(content || "", kb, {
        enabled: Boolean(onEntityClick),
    });

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
