"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useKB } from "@/lib/kb-context";
import { cn } from "@/lib/utils";

type StatusTone = "idle" | "ingest" | "community" | "digest" | "error";

interface StatusView {
  tone: StatusTone;
  label: string;
  detail: string;
}

function buildStatus(payload: Awaited<ReturnType<typeof api.getMaintenanceStatus>> | null): StatusView {
  if (!payload) {
    return {
      tone: "idle",
      label: "Checking…",
      detail: "Waiting for backend status.",
    };
  }

  const ingestActive = Number(payload.ingestion?.active || 0);
  if (ingestActive > 0) {
    return {
      tone: "ingest",
      label: "Ingesting",
      detail: `${ingestActive} note ingestion${ingestActive === 1 ? "" : "s"} running.`,
    };
  }

  if (payload.community_detection?.running) {
    const pending = Number(payload.community_detection.pending_nodes || 0);
    return {
      tone: "community",
      label: "Communities",
      detail:
        pending > 0
          ? `Community detection running (${pending} nodes pending).`
          : "Community detection running.",
    };
  }

  if (payload.temporal_digests?.running) {
    return {
      tone: "digest",
      label: "Digests",
      detail: "Temporal digest build in progress.",
    };
  }

  if (payload.community_detection?.timer_armed) {
    const secs = payload.community_detection.idle_seconds ?? 120;
    const pending = Number(payload.community_detection.pending_nodes || 0);
    return {
      tone: "community",
      label: "Queued",
      detail:
        pending > 0
          ? `Community rebuild armed — starts after ~${secs}s idle (${pending} nodes queued).`
          : `Community rebuild armed — starts after ~${secs}s idle.`,
    };
  }

  const last = payload.ingestion?.last_completed_at;
  return {
    tone: "idle",
    label: "Ready",
    detail: last
      ? `Idle. Last ingestion finished ${new Date(last).toLocaleString()}.`
      : "Idle — no ingestion or community jobs running.",
  };
}

const TONE_STYLES: Record<
  StatusTone,
  { wrap: string; dot: string; pulse: boolean }
> = {
  idle: {
    wrap: "bg-emerald-500/10 text-emerald-400",
    dot: "bg-emerald-400",
    pulse: false,
  },
  ingest: {
    wrap: "bg-amber-500/15 text-amber-300",
    dot: "bg-amber-400",
    pulse: true,
  },
  community: {
    wrap: "bg-violet-500/15 text-violet-300",
    dot: "bg-violet-400",
    pulse: true,
  },
  digest: {
    wrap: "bg-sky-500/15 text-sky-300",
    dot: "bg-sky-400",
    pulse: true,
  },
  error: {
    wrap: "bg-rose-500/15 text-rose-300",
    dot: "bg-rose-400",
    pulse: true,
  },
};

/** Global activity light for the left sidebar (ingestion / community / idle). */
export function SystemStatusIndicator() {
  const { currentKB } = useKB();
  const [payload, setPayload] = useState<Awaited<
    ReturnType<typeof api.getMaintenanceStatus>
  > | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const data = await api.getMaintenanceStatus(currentKB);
        if (!cancelled) {
          setPayload(data);
          setFailed(false);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    };

    void poll();
    const id = window.setInterval(poll, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [currentKB]);

  const view = useMemo(() => {
    if (failed) {
      return {
        tone: "error" as const,
        label: "Offline",
        detail: "Could not reach maintenance status. Backend may be restarting.",
      };
    }
    return buildStatus(payload);
  }, [payload, failed]);

  const styles = TONE_STYLES[view.tone];

  return (
    <div
      className={cn(
        "group relative flex h-12 w-12 flex-col items-center justify-center gap-1 rounded-xl transition-colors",
        styles.wrap,
      )}
      aria-label={`${view.label}. ${view.detail}`}
    >
      <div
        className={cn(
          "h-2.5 w-2.5 rounded-full",
          styles.dot,
          styles.pulse && "animate-pulse",
        )}
      />
      <span className="max-w-[2.75rem] truncate text-[8px] font-semibold uppercase leading-none tracking-wide opacity-80">
        {view.label}
      </span>
      {/* Open into the main pane — centered-above tooltips clip on the narrow left rail. */}
      <div className="pointer-events-none absolute left-full top-1/2 z-[100] ml-3 hidden w-60 -translate-y-1/2 rounded-lg border border-white/10 bg-black/95 px-3 py-2 text-left shadow-xl group-hover:block">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
          System
        </p>
        <p className="mt-0.5 text-xs font-semibold text-white">{view.label}</p>
        <p className="mt-1 text-[11px] leading-snug text-white/65">{view.detail}</p>
        <p className="mt-1.5 truncate text-[10px] text-white/35">KB: {currentKB}</p>
      </div>
    </div>
  );
}
