import type { FormEvent } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import type { FinanceWorkspace } from "@/lib/types";

export function FinanceNotReady({
  workspace,
  statusTone,
  currency,
  onCurrencyChange,
  onSubmit,
  onRefresh,
  busy,
}: {
  workspace: FinanceWorkspace | null;
  statusTone: string;
  currency: string;
  onCurrencyChange: (value: string) => void;
  onSubmit: (e: FormEvent) => void;
  onRefresh: () => void;
  busy: boolean;
}) {
  return (
    <form
      onSubmit={onSubmit}
      className={`space-y-4 rounded-2xl border p-6 backdrop-blur ${statusTone}`}
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <h2 className="text-lg font-medium">
            {workspace?.status === "starting" && "Firefly is starting"}
            {workspace?.status === "bootstrapping" && "Finishing first-time setup"}
            {workspace?.status === "auth_mismatch" && "Finance auth needs attention"}
            {!workspace?.status && "Finance is not ready yet"}
          </h2>
          <p className="mt-1 text-sm text-white/60">
            {workspace?.detail ||
              "Orb is still preparing the embedded Firefly III runtime and API access."}
          </p>
        </div>
      </div>
      <p className="text-sm text-white/60">
        Set the primary currency to finish setup. You can manage accounts, transactions,
        budgets, and reports entirely inside Orb.
      </p>
      <div className="flex gap-3">
        <input
          value={currency}
          onChange={(e) => onCurrencyChange(e.target.value.toUpperCase().slice(0, 3))}
          className="w-24 rounded-lg border border-white/15 bg-black/50 px-3 py-2 text-sm uppercase"
          maxLength={3}
          required
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-200 hover:bg-teal-500/30 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Saving…" : "Set primary currency"}
        </button>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-4 py-2 text-sm text-white/80 hover:bg-white/5"
        >
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      </div>
    </form>
  );
}
