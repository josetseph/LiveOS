"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowDownLeft,
  ArrowRightLeft,
  ArrowUpRight,
  Landmark,
  Loader2,
  PieChart,
  Plus,
  RefreshCw,
  Trash2,
  Wallet,
} from "lucide-react";
import { api } from "@/lib/api";
import { useKB } from "@/lib/kb-context";
import { ShaderBackground } from "@/components/shader-background";
import type {
  FinanceAccount,
  FinanceBudget,
  FinanceCategory,
  FinanceRecurrence,
  FinanceReport,
  FinanceRule,
  FinanceRuleGroup,
  FinanceSearchResult,
  FinanceSummary,
  FinanceTransaction,
  FinanceWorkspace,
} from "@/lib/types";

const FIELD_INPUT =
  "w-full rounded-lg border border-white/15 bg-black/50 px-3 py-2 text-sm text-white focus:border-teal-400/50 focus:outline-none";

type TabId =
  | "overview"
  | "accounts"
  | "transactions"
  | "budgets"
  | "categories"
        | "recurring"
  | "rules"
          | "search"
  | "reports";

function tomorrowIso() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

function errMessage(err: unknown, fallback: string): string {
  if (typeof err === "object" && err && "response" in err) {
    const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map(String).join("; ");
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

function money(value: number, currency?: string | null) {
  const amount = Number.isFinite(value) ? value.toFixed(2) : "0.00";
  return currency ? `${amount} ${currency}` : amount;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function monthStartIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

export default function FinancePage() {
  const { currentKB } = useKB();
  const [tab, setTab] = useState<TabId>("overview");
  const [workspace, setWorkspace] = useState<FinanceWorkspace | null>(null);
  const [summary, setSummary] = useState<FinanceSummary | null>(null);
  const [accounts, setAccounts] = useState<FinanceAccount[]>([]);
  const [transactions, setTransactions] = useState<FinanceTransaction[]>([]);
  const [budgets, setBudgets] = useState<FinanceBudget[]>([]);
  const [categories, setCategories] = useState<FinanceCategory[]>([]);
  const [recurrences, setRecurrences] = useState<FinanceRecurrence[]>([]);
  const [ruleGroups, setRuleGroups] = useState<FinanceRuleGroup[]>([]);
  const [rules, setRules] = useState<FinanceRule[]>([]);
  const [searchResult, setSearchResult] = useState<FinanceSearchResult | null>(null);
  const [report, setReport] = useState<FinanceReport | null>(null);
  const [currency, setCurrency] = useState("USD");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportStart, setReportStart] = useState(monthStartIso());
  const [reportEnd, setReportEnd] = useState(todayIso());

  const [accountForm, setAccountForm] = useState({
    name: "",
    account_type: "asset",
    opening_balance: "",
  });
  const [txForm, setTxForm] = useState({
    type: "withdrawal",
    description: "",
    amount: "",
    account_id: "",
    transfer_account_id: "",
    counterparty_name: "",
    category: "",
    budget_id: "",
    date: todayIso(),
  });
  const [budgetForm, setBudgetForm] = useState({ name: "", amount: "" });
  const [categoryForm, setCategoryForm] = useState({ name: "", notes: "" });
  const [recurrenceForm, setRecurrenceForm] = useState({
    title: "",
    amount: "",
    type: "withdrawal",
    source_id: "",
    destination_id: "",
    description: "",
    first_date: tomorrowIso(),
    repeat_freq: "monthly",
  });
  const [ruleGroupForm, setRuleGroupForm] = useState({ title: "", description: "" });
  const [ruleForm, setRuleForm] = useState({
    title: "",
    rule_group_id: "",
    trigger_type: "description_contains",
    trigger_value: "",
    action_type: "set_category",
    action_value: "",
  });
  const [searchForm, setSearchForm] = useState({
    query: "",
    kind: "transactions" as "transactions" | "accounts",
  });

  const assetAccounts = useMemo(
    () => accounts.filter((a) => a.account_type === "asset" || a.account_type === "Asset account"),
    [accounts],
  );
  const expenseAccounts = useMemo(
    () => accounts.filter((a) => a.account_type === "expense" || a.account_type === "Expense account"),
    [accounts],
  );
  const revenueAccounts = useMemo(
    () => accounts.filter((a) => a.account_type === "revenue" || a.account_type === "Revenue account"),
    [accounts],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const ws = await api.getFinanceWorkspace(currentKB);
      setWorkspace(ws);
      if (ws.currency) setCurrency(ws.currency);
      if (!ws.ready) {
        setSummary(null);
        setAccounts([]);
        setTransactions([]);
        setBudgets([]);
        setCategories([]);
        setRecurrences([]);
        setRuleGroups([]);
        setRules([]);
        setSearchResult(null);
        setReport(null);
        return;
      }

      async function loadOptional<T>(label: string, fn: () => Promise<T>, fallback: T): Promise<T> {
        try {
          return await fn();
        } catch (err) {
          console.warn(`Finance ${label} failed`, err);
          return fallback;
        }
      }

      const [
        financeSummary,
        accountRows,
        txRows,
        budgetRows,
        categoryRows,
        recurrenceRows,
        ruleGroupRows,
        ruleRows,
      ] = await Promise.all([
        api.getFinanceSummary(currentKB, 30),
        api.listFinanceAccounts(currentKB),
        api.listFinanceTransactions(currentKB),
        loadOptional("budgets", () => api.listFinanceBudgets(currentKB, 30), []),
        loadOptional("categories", () => api.listFinanceCategories(currentKB), []),
        loadOptional("recurrences", () => api.listFinanceRecurrences(currentKB), []),
        loadOptional("rule-groups", () => api.listFinanceRuleGroups(currentKB), []),
        loadOptional("rules", () => api.listFinanceRules(currentKB), []),
      ]);
      setSummary(financeSummary);
      setAccounts(accountRows);
      setTransactions(txRows);
      setBudgets(budgetRows);
      setCategories(categoryRows);
      setRecurrences(recurrenceRows);
      setRuleGroups(ruleGroupRows);
      setRules(ruleRows);
      const firstAsset =
        accountRows.find((a) => a.account_type === "asset") || accountRows[0];
      if (firstAsset) {
        setTxForm((prev) => (prev.account_id ? prev : { ...prev, account_id: firstAsset.id }));
        setRecurrenceForm((prev) =>
          prev.source_id ? prev : { ...prev, source_id: firstAsset.id },
        );
      }
      if (ruleGroupRows.length) {
        setRuleForm((prev) =>
          prev.rule_group_id ? prev : { ...prev, rule_group_id: ruleGroupRows[0].id },
        );
      }
    } catch (err) {
      console.error(err);
      setError(errMessage(err, "Could not load finance data."));
    } finally {
      setLoading(false);
    }
  }, [currentKB]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function setPrimaryCurrency(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createFinanceWorkspace(currency, currentKB);
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not set primary currency."));
    } finally {
      setBusy(false);
    }
  }

  async function createAccount(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createFinanceAccount(
        {
          name: accountForm.name,
          account_type: accountForm.account_type,
          opening_balance: Number(accountForm.opening_balance || 0),
          currency: workspace?.currency || currency,
        },
        currentKB,
      );
      setAccountForm({ name: "", account_type: "asset", opening_balance: "" });
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not create account."));
    } finally {
      setBusy(false);
    }
  }

  async function createTransaction(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createFinanceTransaction(
        {
          type: txForm.type,
          description: txForm.description,
          amount: Number(txForm.amount),
          account_id: txForm.account_id,
          transfer_account_id: txForm.transfer_account_id || undefined,
          counterparty_name: txForm.counterparty_name || undefined,
          category: txForm.category || undefined,
          budget_id: txForm.budget_id || undefined,
          currency: workspace?.currency || currency,
          date: txForm.date,
        },
        currentKB,
      );
      setTxForm((prev) => ({
        ...prev,
        description: "",
        amount: "",
        counterparty_name: "",
        category: "",
        budget_id: "",
        transfer_account_id: "",
      }));
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not create transaction."));
    } finally {
      setBusy(false);
    }
  }

  async function removeTransaction(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteFinanceTransaction(id, currentKB);
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not delete transaction."));
    } finally {
      setBusy(false);
    }
  }

  async function createBudget(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createFinanceBudget(
        {
          name: budgetForm.name,
          amount: budgetForm.amount ? Number(budgetForm.amount) : undefined,
          currency: workspace?.currency || currency,
        },
        currentKB,
      );
      setBudgetForm({ name: "", amount: "" });
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not create budget."));
    } finally {
      setBusy(false);
    }
  }

  async function createCategory(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createFinanceCategory(
        { name: categoryForm.name, notes: categoryForm.notes || undefined },
        currentKB,
      );
      setCategoryForm({ name: "", notes: "" });
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not create category."));
    } finally {
      setBusy(false);
    }
  }

  async function removeCategory(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteFinanceCategory(id, currentKB);
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not delete category."));
    } finally {
      setBusy(false);
    }
  }







  async function createRecurrence(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createFinanceRecurrence(
        {
          title: recurrenceForm.title,
          amount: Number(recurrenceForm.amount),
          type: recurrenceForm.type,
          source_id: recurrenceForm.source_id,
          destination_id: recurrenceForm.destination_id,
          description: recurrenceForm.description || undefined,
          first_date: recurrenceForm.first_date,
          repeat_freq: recurrenceForm.repeat_freq,
        },
        currentKB,
      );
      setRecurrenceForm((prev) => ({
        ...prev,
        title: "",
        amount: "",
        description: "",
        destination_id: "",
        first_date: tomorrowIso(),
      }));
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not create recurring transaction."));
    } finally {
      setBusy(false);
    }
  }

  async function removeRecurrence(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteFinanceRecurrence(id, currentKB);
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not delete recurring transaction."));
    } finally {
      setBusy(false);
    }
  }

  async function createRuleGroup(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createFinanceRuleGroup(
        { title: ruleGroupForm.title, description: ruleGroupForm.description || undefined },
        currentKB,
      );
      setRuleGroupForm({ title: "", description: "" });
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not create rule group."));
    } finally {
      setBusy(false);
    }
  }

  async function removeRuleGroup(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteFinanceRuleGroup(id, currentKB);
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not delete rule group."));
    } finally {
      setBusy(false);
    }
  }

  async function createRule(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createFinanceRule(ruleForm, currentKB);
      setRuleForm((prev) => ({
        ...prev,
        title: "",
        trigger_value: "",
        action_value: "",
      }));
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not create rule."));
    } finally {
      setBusy(false);
    }
  }

  async function removeRule(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteFinanceRule(id, currentKB);
      await refresh();
    } catch (err) {
      setError(errMessage(err, "Could not delete rule."));
    } finally {
      setBusy(false);
    }
  }










  async function runSearch(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.searchFinance(searchForm.query, searchForm.kind, currentKB);
      setSearchResult(result);
    } catch (err) {
      setError(errMessage(err, "Search failed."));
    } finally {
      setBusy(false);
    }
  }

  async function loadReport(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload = await api.getFinanceReport(currentKB, reportStart, reportEnd);
      setReport(payload);
    } catch (err) {
      setError(errMessage(err, "Could not load report."));
    } finally {
      setBusy(false);
    }
  }

  const statusTone =
    workspace?.status === "auth_mismatch"
      ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
      : "border-white/10 bg-black/40 text-white/80";

  const tabs: { id: TabId; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "accounts", label: "Accounts" },
    { id: "transactions", label: "Transactions" },
    { id: "budgets", label: "Budgets" },
    { id: "categories", label: "Categories" },
    { id: "recurring", label: "Recurring" },
    { id: "rules", label: "Rules" },
    { id: "search", label: "Search" },
    { id: "reports", label: "Reports" },
  ];

  return (
    <div className="relative min-h-screen text-white">
      <ShaderBackground />
      <div className="relative z-10 mx-auto max-w-5xl px-8 py-12">
        <div className="mb-8 flex items-center gap-3">
          <Wallet className="h-7 w-7 text-teal-300" />
          <div>
            <h1 className="text-2xl font-semibold">Finance</h1>
            <p className="text-sm text-white/50">
              Native Firefly III ledger — scoped to {currentKB}
            </p>
          </div>
        </div>

        {error && (
          <p className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-200">
            {error}
          </p>
        )}

        {loading ? (
          <div className="flex items-center gap-2 text-white/50">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : !workspace?.ready ? (
          <form
            onSubmit={setPrimaryCurrency}
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
                    "LifeOS is still preparing the embedded Firefly III runtime and API access."}
                </p>
              </div>
            </div>
            <p className="text-sm text-white/60">
              Set the primary currency to finish setup. You can manage accounts, transactions,
              budgets, and reports entirely inside LifeOS.
            </p>
            <div className="flex gap-3">
              <input
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase().slice(0, 3))}
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
                onClick={refresh}
                className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-4 py-2 text-sm text-white/80 hover:bg-white/5"
              >
                <RefreshCw className="h-4 w-4" /> Refresh
              </button>
            </div>
          </form>
        ) : (
          <div className="space-y-6">
            <div className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-white/10 bg-black/35 p-5">
              <div>
                <p className="text-sm text-white/50">Primary currency</p>
                <p className="font-mono text-lg text-teal-300">{workspace.currency || "—"}</p>
                <p className="mt-2 text-sm text-white/55">
                  {workspace.administration_title || `KB “${currentKB}” finance`}
                </p>
              </div>
              <form onSubmit={setPrimaryCurrency} className="flex flex-wrap items-end gap-3">
                <label className="text-sm text-white/70">
                  <span className="mb-2 block text-white/50">Change currency</span>
                  <input
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value.toUpperCase().slice(0, 3))}
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
                  onClick={refresh}
                  className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-4 py-2 text-sm text-white/80 hover:bg-white/5"
                >
                  <RefreshCw className="h-4 w-4" /> Refresh
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    if (
                      !window.confirm(
                        `Clear all finance data for knowledge base “${currentKB}”?\n\n` +
                          `This destroys the Firefly administration (accounts, transactions, budgets, …). ` +
                          `Opening Finance again creates a fresh empty administration.`,
                      )
                    ) {
                      return;
                    }
                    if (
                      !window.confirm(
                        "Confirm again: permanently delete this KB’s finance administration?",
                      )
                    ) {
                      return;
                    }
                    setBusy(true);
                    setError(null);
                    try {
                      await api.resetFinanceAdministration(currentKB);
                      await refresh();
                    } catch (err) {
                      setError(
                        err instanceof Error
                          ? err.message
                          : "Failed to clear finance data",
                      );
                    } finally {
                      setBusy(false);
                    }
                  }}
                  className="inline-flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-200 hover:bg-red-500/20 disabled:opacity-60"
                >
                  <Trash2 className="h-4 w-4" /> Clear finance data
                </button>
              </form>
            </div>

            <div className="flex flex-wrap gap-2 border-b border-white/10 pb-2">
              {tabs.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setTab(item.id);
                    if (item.id === "reports" && !report) void loadReport();
                  }}
                  className={
                    tab === item.id
                      ? "rounded-lg bg-teal-500/20 px-3 py-1.5 text-sm text-teal-100"
                      : "rounded-lg px-3 py-1.5 text-sm text-white/55 hover:bg-white/5 hover:text-white/85"
                  }
                >
                  {item.label}
                </button>
              ))}
            </div>

            {tab === "overview" && summary && (
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
                      onDelete={removeTransaction}
                      busy={busy}
                    />
                  </Panel>
                </div>
              </section>
            )}

            {tab === "accounts" && (
              <section className="grid gap-6 xl:grid-cols-[0.9fr,1.1fr]">
                <form
                  onSubmit={createAccount}
                  className="space-y-4 rounded-2xl border border-white/10 bg-black/35 p-5"
                >
                  <h2 className="flex items-center gap-2 text-lg font-medium">
                    <Plus className="h-4 w-4 text-teal-300" /> New account
                  </h2>
                  <Field label="Name">
                    <input
                      required
                      value={accountForm.name}
                      onChange={(e) => setAccountForm((p) => ({ ...p, name: e.target.value }))}
                      className={FIELD_INPUT}
                      placeholder="Checking"
                    />
                  </Field>
                  <Field label="Type">
                    <select
                      value={accountForm.account_type}
                      onChange={(e) =>
                        setAccountForm((p) => ({ ...p, account_type: e.target.value }))
                      }
                      className={FIELD_INPUT}
                    >
                      <option value="asset">Asset</option>
                      <option value="expense">Expense</option>
                      <option value="revenue">Revenue</option>
                      <option value="liability">Liability</option>
                      <option value="cash">Cash</option>
                    </select>
                  </Field>
                  {(accountForm.account_type === "asset" ||
                    accountForm.account_type === "liability") && (
                    <Field label="Opening balance">
                      <input
                        type="number"
                        step="0.01"
                        value={accountForm.opening_balance}
                        onChange={(e) =>
                          setAccountForm((p) => ({ ...p, opening_balance: e.target.value }))
                        }
                        className={FIELD_INPUT}
                        placeholder="0.00"
                      />
                    </Field>
                  )}
                  <button
                    type="submit"
                    disabled={busy}
                    className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-100 hover:bg-teal-500/30 disabled:opacity-60"
                  >
                    {busy ? "Creating…" : "Create account"}
                  </button>
                </form>
                <Panel title="All accounts" icon={<Landmark className="h-5 w-5 text-white/60" />}>
                  <AccountList
                    accounts={accounts}
                    currency={workspace.currency}
                    empty="No accounts yet."
                  />
                </Panel>
              </section>
            )}

            {tab === "transactions" && (
              <section className="grid gap-6 xl:grid-cols-[0.95fr,1.05fr]">
                <form
                  onSubmit={createTransaction}
                  className="space-y-4 rounded-2xl border border-white/10 bg-black/35 p-5"
                >
                  <h2 className="flex items-center gap-2 text-lg font-medium">
                    <Plus className="h-4 w-4 text-teal-300" /> New transaction
                  </h2>
                  <Field label="Type">
                    <select
                      value={txForm.type}
                      onChange={(e) => setTxForm((p) => ({ ...p, type: e.target.value }))}
                      className={FIELD_INPUT}
                    >
                      <option value="withdrawal">Expense (withdrawal)</option>
                      <option value="deposit">Income (deposit)</option>
                      <option value="transfer">Transfer</option>
                    </select>
                  </Field>
                  <Field label="Description">
                    <input
                      required
                      value={txForm.description}
                      onChange={(e) => setTxForm((p) => ({ ...p, description: e.target.value }))}
                      className={FIELD_INPUT}
                      placeholder="Groceries"
                    />
                  </Field>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Amount">
                      <input
                        required
                        type="number"
                        min="0.01"
                        step="0.01"
                        value={txForm.amount}
                        onChange={(e) => setTxForm((p) => ({ ...p, amount: e.target.value }))}
                        className={FIELD_INPUT}
                      />
                    </Field>
                    <Field label="Date">
                      <input
                        type="date"
                        value={txForm.date}
                        onChange={(e) => setTxForm((p) => ({ ...p, date: e.target.value }))}
                        className={FIELD_INPUT}
                      />
                    </Field>
                  </div>
                  <Field label={txForm.type === "deposit" ? "To account" : "From account"}>
                    <select
                      required
                      value={txForm.account_id}
                      onChange={(e) => setTxForm((p) => ({ ...p, account_id: e.target.value }))}
                      className={FIELD_INPUT}
                    >
                      <option value="">Select account</option>
                      {(txForm.type === "transfer" || txForm.type === "withdrawal"
                        ? assetAccounts
                        : assetAccounts
                      ).map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name} ({a.account_type})
                        </option>
                      ))}
                    </select>
                  </Field>
                  {txForm.type === "transfer" ? (
                    <Field label="To account">
                      <select
                        required
                        value={txForm.transfer_account_id}
                        onChange={(e) =>
                          setTxForm((p) => ({ ...p, transfer_account_id: e.target.value }))
                        }
                        className={FIELD_INPUT}
                      >
                        <option value="">Select destination</option>
                        {assetAccounts
                          .filter((a) => a.id !== txForm.account_id)
                          .map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name}
                            </option>
                          ))}
                      </select>
                    </Field>
                  ) : (
                    <Field
                      label={
                        txForm.type === "withdrawal" ? "Payee / expense account" : "Payer / income source"
                      }
                    >
                      <SuggestInput
                        value={txForm.counterparty_name}
                        onChange={(value) =>
                          setTxForm((p) => ({ ...p, counterparty_name: value }))
                        }
                        suggestions={(txForm.type === "withdrawal"
                          ? expenseAccounts
                          : revenueAccounts
                        ).map((a) => a.name)}
                        placeholder={txForm.type === "withdrawal" ? "Shop name" : "Employer"}
                      />
                    </Field>
                  )}
                  <Field label="Category (optional)">
                    <SuggestInput
                      value={txForm.category}
                      onChange={(value) => setTxForm((p) => ({ ...p, category: value }))}
                      suggestions={categories.map((c) => c.name)}
                      placeholder="Food"
                    />
                  </Field>
                  {txForm.type === "withdrawal" && (
                    <Field label="Budget (optional)">
                      <select
                        value={txForm.budget_id}
                        onChange={(e) => setTxForm((p) => ({ ...p, budget_id: e.target.value }))}
                        className={FIELD_INPUT}
                      >
                        <option value="">No budget</option>
                        {budgets.map((b) => (
                          <option key={b.id} value={b.id}>
                            {b.name}
                          </option>
                        ))}
                      </select>
                    </Field>
                  )}
                  <button
                    type="submit"
                    disabled={busy || !txForm.account_id}
                    className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-100 hover:bg-teal-500/30 disabled:opacity-60"
                  >
                    {busy ? "Saving…" : "Add transaction"}
                  </button>
                  {accounts.length === 0 && (
                    <p className="text-xs text-amber-200/80">
                      Create an asset account first before adding transactions.
                    </p>
                  )}
                </form>
                <Panel title="Transactions">
                  <TransactionList
                    rows={transactions}
                    currency={workspace.currency}
                    onDelete={removeTransaction}
                    busy={busy}
                  />
                </Panel>
              </section>
            )}

            {tab === "budgets" && (
              <section className="grid gap-6 xl:grid-cols-[0.9fr,1.1fr]">
                <form
                  onSubmit={createBudget}
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
            )}

            {tab === "categories" && (
              <section className="grid gap-6 xl:grid-cols-[0.9fr,1.1fr]">
                <form
                  onSubmit={createCategory}
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
                    onDelete={removeCategory}
                  />
                </Panel>
              </section>
            )}




            {tab === "recurring" && (
              <section className="grid gap-6 xl:grid-cols-[0.95fr,1.05fr]">
                <form
                  onSubmit={createRecurrence}
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
                            onClick={() => removeRecurrence(row.id)}
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
            )}

            {tab === "rules" && (
              <section className="space-y-6">
                <div className="grid gap-6 xl:grid-cols-2">
                  <form
                    onSubmit={createRuleGroup}
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
                    onSubmit={createRule}
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
                      onDelete={removeRuleGroup}
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
                            onClick={() => removeRule(rule.id)}
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
            )}





            {tab === "search" && (
              <section className="space-y-6">
                <form
                  onSubmit={runSearch}
                  className="flex flex-wrap items-end gap-3 rounded-2xl border border-white/10 bg-black/35 p-5"
                >
                  <Field label="Query">
                    <input
                      required
                      value={searchForm.query}
                      onChange={(e) => setSearchForm((p) => ({ ...p, query: e.target.value }))}
                      className={FIELD_INPUT}
                      placeholder="coffee OR amount>20"
                    />
                  </Field>
                  <Field label="Search in">
                    <select
                      value={searchForm.kind}
                      onChange={(e) =>
                        setSearchForm((p) => ({
                          ...p,
                          kind: e.target.value as "transactions" | "accounts",
                        }))
                      }
                      className={FIELD_INPUT}
                    >
                      <option value="transactions">Transactions</option>
                      <option value="accounts">Accounts</option>
                    </select>
                  </Field>
                  <button
                    type="submit"
                    disabled={busy}
                    className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-100 hover:bg-teal-500/30 disabled:opacity-60"
                  >
                    {busy ? "Searching…" : "Search"}
                  </button>
                </form>
                <Panel title="Results">
                  {searchResult?.kind === "accounts" ? (
                    <AccountList
                      accounts={searchResult.results as FinanceAccount[]}
                      currency={workspace.currency}
                      empty="No matching accounts."
                    />
                  ) : (
                    <TransactionList
                      rows={(searchResult?.results as FinanceTransaction[]) || []}
                      currency={workspace.currency}
                    />
                  )}
                </Panel>
              </section>
            )}

            {tab === "reports" && (
              <section className="space-y-6">
                <form
                  onSubmit={loadReport}
                  className="flex flex-wrap items-end gap-3 rounded-2xl border border-white/10 bg-black/35 p-5"
                >
                  <Field label="Start">
                    <input
                      type="date"
                      value={reportStart}
                      onChange={(e) => setReportStart(e.target.value)}
                      className={FIELD_INPUT}
                    />
                  </Field>
                  <Field label="End">
                    <input
                      type="date"
                      value={reportEnd}
                      onChange={(e) => setReportEnd(e.target.value)}
                      className={FIELD_INPUT}
                    />
                  </Field>
                  <button
                    type="submit"
                    disabled={busy}
                    className="inline-flex items-center gap-2 rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-100 hover:bg-teal-500/30 disabled:opacity-60"
                  >
                    <PieChart className="h-4 w-4" />
                    {busy ? "Loading…" : "Generate report"}
                  </button>
                </form>
                {report && (
                  <div className="grid gap-6 xl:grid-cols-2">
                    <Panel title="Basic summary">
                      <BasicSummaryList basic={report.basic} />
                    </Panel>
                    <Panel title="Category overview">
                      <ChartList data={report.category_chart} />
                    </Panel>
                    <Panel title="Budget overview">
                      <ChartList data={report.budget_chart} />
                    </Panel>
                    <Panel title="Accounts snapshot">
                      <AccountList
                        accounts={report.accounts}
                        currency={workspace.currency}
                        empty="No accounts."
                      />
                    </Panel>
                  </div>
                )}
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm text-white/70">
      <span className="mb-1.5 block text-white/50">{label}</span>
      {children}
    </label>
  );
}

function SuggestInput({
  value,
  onChange,
  suggestions,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  suggestions: string[];
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const filtered = suggestions
    .filter((item) => item.toLowerCase().includes((value || "").toLowerCase()))
    .slice(0, 8);
  return (
    <div className="relative">
      <input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          // Delay so click on suggestion registers.
          window.setTimeout(() => setOpen(false), 120);
        }}
        className={FIELD_INPUT}
        placeholder={placeholder}
        autoComplete="off"
      />
      {open && filtered.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-48 w-full overflow-auto rounded-lg border border-white/15 bg-[#12141c] py-1 shadow-lg">
          {filtered.map((item) => (
            <li key={item}>
              <button
                type="button"
                className="block w-full px-3 py-1.5 text-left text-sm text-white/85 hover:bg-teal-500/15"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(item);
                  setOpen(false);
                }}
              >
                {item}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DeletableList({
  rows,
  empty,
  busy,
  onDelete,
}: {
  rows: Array<{ id: string; title: string; subtitle?: string }>;
  empty: string;
  busy?: boolean;
  onDelete: (id: string) => void;
}) {
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li
          key={row.id}
          className="flex items-center justify-between gap-3 rounded-xl border border-white/5 px-4 py-3 text-sm"
        >
          <div className="min-w-0">
            <div className="truncate">{row.title}</div>
            {row.subtitle ? <div className="text-xs text-white/40">{row.subtitle}</div> : null}
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => onDelete(row.id)}
            className="rounded p-1 text-white/35 hover:bg-white/5 hover:text-rose-200 disabled:opacity-50"
            aria-label={`Delete ${row.title}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </li>
      ))}
      {rows.length === 0 && (
        <li className="rounded-xl border border-dashed border-white/10 px-4 py-6 text-sm text-white/40">
          {empty}
        </li>
      )}
    </ul>
  );
}

function Panel({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/35 p-6">
      <div className="mb-4 flex items-center gap-2">
        {icon}
        <h2 className="text-lg font-medium">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  currency,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  currency?: string;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/35 p-5">
      <div className="mb-3 flex items-center gap-2 text-sm text-white/55">
        {icon}
        <span>{label}</span>
      </div>
      <div className="font-mono text-2xl text-white">{money(value, currency)}</div>
    </div>
  );
}

function AccountList({
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

function TransactionList({
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

function BasicSummaryList({ basic }: { basic: Record<string, unknown> }) {
  const entries = Object.entries(basic || {});
  if (!entries.length) {
    return <p className="text-sm text-white/40">No summary data for this range.</p>;
  }
  return (
    <ul className="space-y-2">
      {entries.map(([key, value]) => {
        const row = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
        const label = String(row?.title || row?.monetary_value || key);
        const amount =
          row?.value_parsed ??
          row?.value ??
          (typeof value === "number" || typeof value === "string" ? value : null);
        return (
          <li
            key={key}
            className="flex items-center justify-between gap-3 rounded-xl border border-white/5 px-4 py-3 text-sm"
          >
            <span className="truncate text-white/70">{label}</span>
            <span className="font-mono text-teal-200">
              {amount == null ? "—" : String(amount)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function ChartList({ data }: { data: unknown }) {
  const rows = Array.isArray(data)
    ? data
    : data && typeof data === "object" && Array.isArray((data as { data?: unknown }).data)
      ? ((data as { data: unknown[] }).data)
      : [];
  if (!rows.length) {
    return <p className="text-sm text-white/40">No chart data for this range.</p>;
  }
  return (
    <ul className="space-y-2">
      {rows.map((item, idx) => {
        const row = item && typeof item === "object" ? (item as Record<string, unknown>) : {};
        const label = String(row.label || row.key || row.name || `Series ${idx + 1}`);
        const entries = Array.isArray(row.entries) ? row.entries : null;
        const value =
          row.y ??
          row.value ??
          (entries
            ? entries.reduce(
                (sum: number, entry: unknown) =>
                  sum +
                  Number(
                    (entry && typeof entry === "object"
                      ? (entry as { y?: unknown }).y
                      : 0) || 0,
                  ),
                0,
              )
            : null);
        return (
          <li
            key={`${label}-${idx}`}
            className="flex items-center justify-between gap-3 rounded-xl border border-white/5 px-4 py-3 text-sm"
          >
            <span className="truncate text-white/70">{label}</span>
            <span className="font-mono text-teal-200">
              {value == null ? "—" : Number(value).toFixed(2)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
