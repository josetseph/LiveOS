"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";

/** Persistent banner when AI is not configured (Obsidian-like limited mode). */
export function AiLimitedBanner() {
  const [show, setShow] = useState(false);
  const [needsDownload, setNeedsDownload] = useState(false);

  useEffect(() => {
    api
      .getSetupStatus()
      .then((s) => {
        setShow(!s.ai_configured);
        setNeedsDownload(Boolean(s.needs_model_download));
      })
      .catch(() => setShow(false));
  }, []);

  if (!show) return null;

  return (
    <div className="fixed bottom-4 left-24 right-4 z-50 mx-auto max-w-3xl rounded-xl border border-amber-500/30 bg-amber-950/90 px-4 py-3 text-sm text-amber-100 shadow-xl backdrop-blur">
      <div className="flex flex-wrap items-center gap-3">
        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-300" />
        <span className="flex-1">
          {needsDownload
            ? "Local models are not downloaded yet — open Setup to finish the download (chat / ingest stay unavailable until then)."
            : "AI not configured — limited experience (notes & wikilinks work; chat / ingest / entity graph need setup)."}
        </span>
        <Link
          href="/setup"
          className="rounded-lg bg-amber-500/25 px-3 py-1.5 text-xs font-medium hover:bg-amber-500/40"
        >
          {needsDownload ? "Continue download" : "Set up AI"}
        </Link>
        <button
          type="button"
          onClick={() => setShow(false)}
          className="text-xs text-amber-200/60 hover:text-amber-100"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
