"use client";

import { useEffect, useState } from "react";
import {
  encodeFileUrl,
  fetchMediaObjectUrl,
  resolveFileUrl,
  youtubeEmbedUrl,
  vimeoEmbedUrl,
} from "@/lib/utils";

/** Video/audio/YouTube preview with reliable local playback. */
export function BlobMediaPlayer({
  url,
  kbId = "default",
  kind,
  className,
}: {
  url: string;
  kbId?: string;
  kind: "video" | "audio";
  className?: string;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const yt = youtubeEmbedUrl(url);
  const vimeo = vimeoEmbedUrl(url);

  useEffect(() => {
    if (yt || vimeo) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    setSrc(null);
    setError(null);

    const direct = encodeFileUrl(resolveFileUrl(url, kbId));
    // Try direct first (works with Range + faststart); blob as fallback.
    setSrc(direct);

    void fetchMediaObjectUrl(url, kbId)
      .then((blobUrl) => {
        if (cancelled) {
          if (blobUrl.startsWith("blob:")) URL.revokeObjectURL(blobUrl);
          return;
        }
        if (blobUrl.startsWith("blob:")) {
          objectUrl = blobUrl;
        }
        setSrc(blobUrl);
      })
      .catch(() => {
        /* keep direct src */
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, kbId, yt, vimeo]);

  if (yt || vimeo) {
    return (
      <iframe
        src={yt || vimeo || ""}
        title="Embedded video"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        allowFullScreen
        className={
          className ||
          "mx-auto aspect-video min-h-[200px] w-full max-w-full rounded-lg border border-white/10 bg-black"
        }
      />
    );
  }

  if (error) {
    return <p className="text-sm text-red-400">{error}</p>;
  }
  if (!src) {
    return <p className="text-sm text-white/40">Loading media…</p>;
  }

  if (kind === "video") {
    return (
      <video
        controls
        playsInline
        src={src}
        className={
          className ||
          "mx-auto max-h-[70vh] w-full max-w-full rounded-lg bg-black"
        }
        onError={() => setError("Could not play this video.")}
      >
        Your browser does not support video playback.
      </video>
    );
  }

  return (
    <audio
      controls
      src={src}
      className={className || "w-full max-w-2xl"}
      onError={() => setError("Could not play this audio.")}
    />
  );
}
