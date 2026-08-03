import {
  ArrowDownLeft,
  ArrowRightLeft,
  ArrowUpRight,
  Landmark,
  Wallet,
} from "lucide-react";
import type { FinanceSummary, FinanceWorkspace } from "@/lib/types";
import { AccountList } from "../AccountList";
import { MetricCard } from "../MetricCard";
import { Panel } from "../Panel";
import { TransactionList } from "../TransactionList";

export function OverviewTab({
  summary,
  workspace,
  busy,
  onDeleteTransaction,
}: {
  summary: FinanceSummary;
  workspace: FinanceWorkspace;
  busy: boolean;
  onDeleteTransaction: (id: string) => void;
}) {
  return (
    <section className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={<Wallet className="h-4 w-4 text-teal-200" />}
          label="Tracked balance"
          value={summary.asset_balance}
          currency={workspace.currency}
        />
        <MetricCard
          icon={<ArrowUpRight className="h-4 w-4 text-emerald-200" />}
          label={`Income (${summary.days}d)`}
          value={summary.income_total}
          currency={workspace.currency}
        />
        <MetricCard
          icon={<ArrowDownLeft className="h-4 w-4 text-rose-200" />}
          label={`Expenses (${summary.days}d)`}
          value={summary.expense_total}
          currency={workspace.currency}
        />
        <MetricCard
          icon={<ArrowRightLeft className="h-4 w-4 text-sky-200" />}
          label="Net flow"
          value={summary.net_flow}
          currency={workspace.currency}
        />
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Accounts" icon={<Landmark className="h-5 w-5 text-white/60" />}>
          <AccountList
            accounts={summary.accounts}
            currency={workspace.currency}
            empty="No accounts yet — create one in the Accounts tab."
          />
        </Panel>
        <Panel title="Recent transactions">
          <TransactionList
            rows={summary.recent_transactions}
            currency={workspace.currency}
            onDelete={onDeleteTransaction}
            busy={busy}
          />
        </Panel>
      </div>
    </section>
  );
}
