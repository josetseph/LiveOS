import type { FormEvent } from "react";
import { RefreshCw, Trash2 } from "lucide-react";
import type { FinanceWorkspace } from "@/lib/types";

export function FinanceWorkspaceBar({
  workspace,
  currentKB,
  currency,
  onCurrencyChange,
  onSubmit,
  onRefresh,
  onReset,
  busy,
}: {
  workspace: FinanceWorkspace;
  currentKB: string;
  currency: string;
  onCurrencyChange: (value: string) => void;
  onSubmit: (e: FormEvent) => void;
  onRefresh: () => void;
  onReset: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-white/10 bg-black/35 p-5">
      <div>
        <p className="text-sm text-white/50">Primary currency</p>
        <p className="font-mono text-lg text-teal-300">{workspace.currency || "—"}</p>
        <p className="mt-2 text-sm text-white/55">
          {workspace.administration_title || `KB “${currentKB}” finance`}
        </p>
      </div>
      <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
        <label className="text-sm text-white/70">
          <span className="mb-2 block text-white/50">Change currency</span>
          <input
            value={currency}
            onChange={(e) => onCurrencyChange(e.target.value.toUpperCase().slice(0, 3))}
            className="w-28 rounded-lg border border-white/15 bg-black/50 px-3 py-2 text-sm uppercase"
            maxLength={3}
            required
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg border border-white/10 px-4 py-2 text-sm text-white/85 hover:bg-white/5 disabled:opacity-60"
        >
          {busy ? "Saving…" : "Update"}
        </button>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-4 py-2 text-sm text-white/80 hover:bg-white/5"
        >
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onReset}
          className="inline-flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-200 hover:bg-red-500/20 disabled:opacity-60"
        >
          <Trash2 className="h-4 w-4" /> Clear finance data
        </button>
      </form>
    </div>
  );
}
