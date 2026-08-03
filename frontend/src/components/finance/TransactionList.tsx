import { Trash2 } from "lucide-react";
import type { FinanceTransaction } from "@/lib/types";
import { money } from "./utils";

export function TransactionList({
  rows,
  currency,
  onDelete,
  busy,
}: {
  rows: FinanceTransaction[];
  currency?: string;
  onDelete?: (id: string) => void;
  busy?: boolean;
}) {
  return (
    <ul className="space-y-2">
      {rows.map((tx) => (
        <li
          key={tx.id}
          className="flex items-start justify-between gap-3 rounded-xl border border-white/5 px-4 py-3 text-sm"
        >
          <div className="min-w-0">
            <div className="truncate">{tx.description || "(no description)"}</div>
            <div className="mt-1 text-xs text-white/40">
              {tx.date ? new Date(tx.date).toLocaleDateString() : "—"}
              {tx.account_name ? ` · ${tx.account_name}` : ""}
              {tx.counterparty_name ? ` → ${tx.counterparty_name}` : ""}
              {tx.category ? ` · ${tx.category}` : ""}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div
              className={
                tx.type === "deposit"
                  ? "font-mono text-emerald-200"
                  : tx.type === "withdrawal"
                    ? "font-mono text-rose-200"
                    : "font-mono text-sky-200"
              }
            >
              {money(tx.amount, tx.currency_code || currency)}
            </div>
            {onDelete && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onDelete(tx.group_id || tx.id)}
                className="rounded p-1 text-white/35 hover:bg-white/5 hover:text-rose-200 disabled:opacity-50"
                aria-label="Delete transaction"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </li>
      ))}
      {rows.length === 0 && (
        <li className="rounded-xl border border-dashed border-white/10 px-4 py-6 text-sm text-white/40">
          No transactions yet.
        </li>
      )}
    </ul>
  );
}
