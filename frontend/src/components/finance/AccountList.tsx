import type { FinanceAccount } from "@/lib/types";
import { money } from "./utils";

export function AccountList({
  accounts,
  currency,
  empty,
}: {
  accounts: FinanceAccount[];
  currency?: string;
  empty: string;
}) {
  return (
    <ul className="space-y-2">
      {accounts.map((account) => (
        <li
          key={account.id}
          className="flex items-center justify-between gap-3 rounded-xl border border-white/5 px-4 py-3 text-sm"
        >
          <div className="min-w-0">
            <div className="truncate">{account.name}</div>
            <div className="text-xs uppercase tracking-wide text-white/40">
              {account.account_type}
            </div>
          </div>
          <div className="text-right font-mono text-teal-200">
            {money(account.balance, currency || account.currency)}
          </div>
        </li>
      ))}
      {accounts.length === 0 && (
        <li className="rounded-xl border border-dashed border-white/10 px-4 py-6 text-sm text-white/40">
          {empty}
        </li>
      )}
    </ul>
  );
}
