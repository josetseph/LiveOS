import type { FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import type { FinanceAccount, FinanceRecurrence, FinanceWorkspace } from "@/lib/types";
import { Field } from "../Field";
import { Panel } from "../Panel";
import { FIELD_INPUT, money } from "../utils";

type RecurrenceForm = {
  title: string;
  amount: string;
  type: string;
  source_id: string;
  destination_id: string;
  description: string;
  first_date: string;
  repeat_freq: string;
};

export function RecurringTab({
  recurrences,
  assetAccounts,
  expenseAccounts,
  revenueAccounts,
  workspace,
  recurrenceForm,
  setRecurrenceForm,
  onCreate,
  onDelete,
  busy,
}: {
  recurrences: FinanceRecurrence[];
  assetAccounts: FinanceAccount[];
  expenseAccounts: FinanceAccount[];
  revenueAccounts: FinanceAccount[];
  workspace: FinanceWorkspace;
  recurrenceForm: RecurrenceForm;
  setRecurrenceForm: React.Dispatch<React.SetStateAction<RecurrenceForm>>;
  onCreate: (e: FormEvent) => void;
  onDelete: (id: string) => void;
  busy: boolean;
}) {
  return (
    <section className="grid gap-6 xl:grid-cols-[0.95fr,1.05fr]">
      <form
        onSubmit={onCreate}
        className="space-y-4 rounded-2xl border border-white/10 bg-black/35 p-5"
      >
        <h2 className="flex items-center gap-2 text-lg font-medium">
          <Plus className="h-4 w-4 text-teal-300" /> New recurring transaction
        </h2>
        <Field label="Title">
          <input
            required
            value={recurrenceForm.title}
            onChange={(e) => setRecurrenceForm((p) => ({ ...p, title: e.target.value }))}
            className={FIELD_INPUT}
            placeholder="Monthly rent"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type">
            <select
              value={recurrenceForm.type}
              onChange={(e) => setRecurrenceForm((p) => ({ ...p, type: e.target.value }))}
              className={FIELD_INPUT}
            >
              <option value="withdrawal">Expense</option>
              <option value="deposit">Income</option>
              <option value="transfer">Transfer</option>
            </select>
          </Field>
          <Field label="Amount">
            <input
              required
              type="number"
              min="0.01"
              step="0.01"
              value={recurrenceForm.amount}
              onChange={(e) =>
                setRecurrenceForm((p) => ({ ...p, amount: e.target.value }))
              }
              className={FIELD_INPUT}
            />
          </Field>
        </div>
        <Field label="From account">
          <select
            required
            value={recurrenceForm.source_id}
            onChange={(e) =>
              setRecurrenceForm((p) => ({ ...p, source_id: e.target.value }))
            }
            className={FIELD_INPUT}
          >
            <option value="">Select source</option>
            {(recurrenceForm.type === "deposit" ? revenueAccounts : assetAccounts).map(
              (a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ),
            )}
          </select>
        </Field>
        <Field label="To account">
          <select
            required
            value={recurrenceForm.destination_id}
            onChange={(e) =>
              setRecurrenceForm((p) => ({ ...p, destination_id: e.target.value }))
            }
            className={FIELD_INPUT}
          >
            <option value="">Select destination</option>
            {(recurrenceForm.type === "withdrawal"
              ? expenseAccounts
              : recurrenceForm.type === "deposit"
                ? assetAccounts
                : assetAccounts.filter((a) => a.id !== recurrenceForm.source_id)
            ).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="First date">
            <input
              type="date"
              value={recurrenceForm.first_date}
              onChange={(e) =>
                setRecurrenceForm((p) => ({ ...p, first_date: e.target.value }))
              }
              className={FIELD_INPUT}
            />
          </Field>
          <Field label="Frequency">
            <select
              value={recurrenceForm.repeat_freq}
              onChange={(e) =>
                setRecurrenceForm((p) => ({ ...p, repeat_freq: e.target.value }))
              }
              className={FIELD_INPUT}
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="yearly">Yearly</option>
            </select>
          </Field>
        </div>
        <button
          type="submit"
          disabled={
            busy || !recurrenceForm.source_id || !recurrenceForm.destination_id
          }
          className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-100 hover:bg-teal-500/30 disabled:opacity-60"
        >
          {busy ? "Creating…" : "Create recurring"}
        </button>
        {(recurrenceForm.type === "withdrawal" && expenseAccounts.length === 0) ||
        (recurrenceForm.type === "deposit" && revenueAccounts.length === 0) ? (
          <p className="text-xs text-amber-200/80">
            Create matching expense/revenue accounts first under Accounts.
          </p>
        ) : null}
      </form>
      <Panel title="Recurring transactions">
        <ul className="space-y-2">
          {recurrences.map((row) => (
            <li
              key={row.id}
              className="flex items-center justify-between gap-3 rounded-xl border border-white/5 px-4 py-3 text-sm"
            >
              <div className="min-w-0">
                <div className="truncate">{row.title}</div>
                <div className="text-xs text-white/40">
                  {row.repetition_type || "—"} · {row.type || "tx"}
                  {row.first_date ? ` · from ${row.first_date}` : ""}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-teal-200">
                  {money(row.amount, row.currency || workspace.currency)}
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onDelete(row.id)}
                  className="rounded p-1 text-white/35 hover:bg-white/5 hover:text-rose-200 disabled:opacity-50"
                  aria-label="Delete recurrence"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </li>
          ))}
          {recurrences.length === 0 && (
            <li className="rounded-xl border border-dashed border-white/10 px-4 py-6 text-sm text-white/40">
              No recurring transactions yet.
            </li>
          )}
        </ul>
      </Panel>
    </section>
  );
}
