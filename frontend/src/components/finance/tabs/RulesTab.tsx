import type { FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import type { FinanceRule, FinanceRuleGroup } from "@/lib/types";
import { DeletableList } from "../DeletableList";
import { Field } from "../Field";
import { Panel } from "../Panel";
import { FIELD_INPUT } from "../utils";

type RuleGroupForm = { title: string; description: string };
type RuleForm = {
  title: string;
  rule_group_id: string;
  trigger_type: string;
  trigger_value: string;
  action_type: string;
  action_value: string;
};

export function RulesTab({
  ruleGroups,
  rules,
  ruleGroupForm,
  setRuleGroupForm,
  ruleForm,
  setRuleForm,
  onCreateGroup,
  onCreateRule,
  onDeleteGroup,
  onDeleteRule,
  busy,
}: {
  ruleGroups: FinanceRuleGroup[];
  rules: FinanceRule[];
  ruleGroupForm: RuleGroupForm;
  setRuleGroupForm: React.Dispatch<React.SetStateAction<RuleGroupForm>>;
  ruleForm: RuleForm;
  setRuleForm: React.Dispatch<React.SetStateAction<RuleForm>>;
  onCreateGroup: (e: FormEvent) => void;
  onCreateRule: (e: FormEvent) => void;
  onDeleteGroup: (id: string) => void;
  onDeleteRule: (id: string) => void;
  busy: boolean;
}) {
  return (
    <section className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        <form
          onSubmit={onCreateGroup}
          className="space-y-4 rounded-2xl border border-white/10 bg-black/35 p-5"
        >
          <h2 className="flex items-center gap-2 text-lg font-medium">
            <Plus className="h-4 w-4 text-teal-300" /> Rule group
          </h2>
          <Field label="Title">
            <input
              required
              value={ruleGroupForm.title}
              onChange={(e) => setRuleGroupForm((p) => ({ ...p, title: e.target.value }))}
              className={FIELD_INPUT}
            />
          </Field>
          <Field label="Description">
            <input
              value={ruleGroupForm.description}
              onChange={(e) =>
                setRuleGroupForm((p) => ({ ...p, description: e.target.value }))
              }
              className={FIELD_INPUT}
            />
          </Field>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-100 hover:bg-teal-500/30 disabled:opacity-60"
          >
            Create group
          </button>
        </form>
        <form
          onSubmit={onCreateRule}
          className="space-y-4 rounded-2xl border border-white/10 bg-black/35 p-5"
        >
          <h2 className="flex items-center gap-2 text-lg font-medium">
            <Plus className="h-4 w-4 text-teal-300" /> Rule
          </h2>
          <Field label="Title">
            <input
              required
              value={ruleForm.title}
              onChange={(e) => setRuleForm((p) => ({ ...p, title: e.target.value }))}
              className={FIELD_INPUT}
            />
          </Field>
          <Field label="Rule group">
            <select
              required
              value={ruleForm.rule_group_id}
              onChange={(e) =>
                setRuleForm((p) => ({ ...p, rule_group_id: e.target.value }))
              }
              className={FIELD_INPUT}
            >
              <option value="">Select group</option>
              {ruleGroups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.title}
                </option>
              ))}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="If description contains">
              <input
                required
                value={ruleForm.trigger_value}
                onChange={(e) =>
                  setRuleForm((p) => ({ ...p, trigger_value: e.target.value }))
                }
                className={FIELD_INPUT}
                placeholder="UBER"
              />
            </Field>
            <Field label="Then set category">
              <input
                required
                value={ruleForm.action_value}
                onChange={(e) =>
                  setRuleForm((p) => ({ ...p, action_value: e.target.value }))
                }
                className={FIELD_INPUT}
                placeholder="Transport"
              />
            </Field>
          </div>
          <button
            type="submit"
            disabled={busy || !ruleForm.rule_group_id}
            className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-100 hover:bg-teal-500/30 disabled:opacity-60"
          >
            Create rule
          </button>
        </form>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Rule groups">
          <DeletableList
            rows={ruleGroups.map((g) => ({
              id: g.id,
              title: g.title,
              subtitle: g.description || undefined,
            }))}
            empty="No rule groups yet."
            busy={busy}
            onDelete={onDeleteGroup}
          />
        </Panel>
        <Panel title="Rules">
          <ul className="space-y-2">
            {rules.map((rule) => (
              <li
                key={rule.id}
                className="flex items-center justify-between gap-3 rounded-xl border border-white/5 px-4 py-3 text-sm"
              >
                <div className="min-w-0">
                  <div className="truncate">{rule.title}</div>
                  <div className="text-xs text-white/40">
                    {rule.triggers[0]?.type || "trigger"}:{rule.triggers[0]?.value || "—"}{" "}
                    → {rule.actions[0]?.type || "action"}:{rule.actions[0]?.value || "—"}
                  </div>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onDeleteRule(rule.id)}
                  className="rounded p-1 text-white/35 hover:bg-white/5 hover:text-rose-200 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
            {rules.length === 0 && (
              <li className="rounded-xl border border-dashed border-white/10 px-4 py-6 text-sm text-white/40">
                No rules yet.
              </li>
            )}
          </ul>
        </Panel>
      </div>
    </section>
  );
}
