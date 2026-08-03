import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import type { FinanceBudget, FinanceWorkspace } from "@/lib/types";
import { Field } from "../Field";
import { Panel } from "../Panel";
import { FIELD_INPUT, money } from "../utils";

export function BudgetsTab({
  budgets,
  workspace,
  budgetForm,
  setBudgetForm,
  onCreate,
  busy,
}: {
  budgets: FinanceBudget[];
  workspace: FinanceWorkspace;
  budgetForm: { name: string; amount: string };
  setBudgetForm: React.Dispatch<React.SetStateAction<{ name: string; amount: string }>>;
  onCreate: (e: FormEvent) => void;
  busy: boolean;
}) {
  return (
    <section className="grid gap-6 xl:grid-cols-[0.9fr,1.1fr]">
      <form
        onSubmit={onCreate}
        className="space-y-4 rounded-2xl border border-white/10 bg-black/35 p-5"
      >
        <h2 className="flex items-center gap-2 text-lg font-medium">
          <Plus className="h-4 w-4 text-teal-300" /> New budget
        </h2>
        <Field label="Name">
          <input
            required
            value={budgetForm.name}
            onChange={(e) => setBudgetForm((p) => ({ ...p, name: e.target.value }))}
            className={FIELD_INPUT}
            placeholder="Groceries"
          />
        </Field>
        <Field label="Monthly amount (optional)">
          <input
            type="number"
            min="0.01"
            step="0.01"
            value={budgetForm.amount}
            onChange={(e) => setBudgetForm((p) => ({ ...p, amount: e.target.value }))}
            className={FIELD_INPUT}
            placeholder="500"
          />
        </Field>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-100 hover:bg-teal-500/30 disabled:opacity-60"
        >
          {busy ? "Creating…" : "Create budget"}
        </button>
      </form>
      <Panel title="Budgets">
        <ul className="space-y-2">
          {budgets.map((budget) => (
            <li
              key={budget.id}
              className="flex items-center justify-between gap-3 rounded-xl border border-white/5 px-4 py-3 text-sm"
            >
              <div>
                <div>{budget.name}</div>
                <div className="text-xs text-white/40">
                  {budget.auto_budget_amount
                    ? `${money(budget.auto_budget_amount, workspace.currency)} / ${budget.auto_budget_period || "month"}`
                    : "No auto amount"}
                </div>
              </div>
              <div className="font-mono text-rose-200">
                spent {money(budget.spent, budget.currency || workspace.currency)}
              </div>
            </li>
          ))}
          {budgets.length === 0 && (
            <li className="rounded-xl border border-dashed border-white/10 px-4 py-6 text-sm text-white/40">
              No budgets yet.
            </li>
          )}
        </ul>
      </Panel>
    </section>
  );
}
