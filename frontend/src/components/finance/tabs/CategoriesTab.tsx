import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import type { FinanceCategory } from "@/lib/types";
import { DeletableList } from "../DeletableList";
import { Field } from "../Field";
import { Panel } from "../Panel";
import { FIELD_INPUT } from "../utils";

export function CategoriesTab({
  categories,
  categoryForm,
  setCategoryForm,
  onCreate,
  onDelete,
  busy,
}: {
  categories: FinanceCategory[];
  categoryForm: { name: string; notes: string };
  setCategoryForm: React.Dispatch<React.SetStateAction<{ name: string; notes: string }>>;
  onCreate: (e: FormEvent) => void;
  onDelete: (id: string) => void;
  busy: boolean;
}) {
  return (
    <section className="grid gap-6 xl:grid-cols-[0.9fr,1.1fr]">
      <form
        onSubmit={onCreate}
        className="space-y-4 rounded-2xl border border-white/10 bg-black/35 p-5"
      >
        <h2 className="flex items-center gap-2 text-lg font-medium">
          <Plus className="h-4 w-4 text-teal-300" /> New category
        </h2>
        <Field label="Name">
          <input
            required
            value={categoryForm.name}
            onChange={(e) => setCategoryForm((p) => ({ ...p, name: e.target.value }))}
            className={FIELD_INPUT}
            placeholder="Groceries"
          />
        </Field>
        <Field label="Notes (optional)">
          <input
            value={categoryForm.notes}
            onChange={(e) => setCategoryForm((p) => ({ ...p, notes: e.target.value }))}
            className={FIELD_INPUT}
          />
        </Field>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-100 hover:bg-teal-500/30 disabled:opacity-60"
        >
          {busy ? "Creating…" : "Create category"}
        </button>
      </form>
      <Panel title="Categories">
        <DeletableList
          rows={categories.map((c) => ({
            id: c.id,
            title: c.name,
            subtitle: c.notes || undefined,
          }))}
          empty="No categories yet."
          busy={busy}
          onDelete={onDelete}
        />
      </Panel>
    </section>
  );
}
