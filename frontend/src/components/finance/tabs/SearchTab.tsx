import type { FormEvent } from "react";
import type {
  FinanceAccount,
  FinanceSearchResult,
  FinanceTransaction,
  FinanceWorkspace,
} from "@/lib/types";
import { AccountList } from "../AccountList";
import { Field } from "../Field";
import { Panel } from "../Panel";
import { TransactionList } from "../TransactionList";
import { FIELD_INPUT } from "../utils";

export function SearchTab({
  searchForm,
  setSearchForm,
  searchResult,
  workspace,
  onSearch,
  busy,
}: {
  searchForm: { query: string; kind: "transactions" | "accounts" };
  setSearchForm: React.Dispatch<
    React.SetStateAction<{ query: string; kind: "transactions" | "accounts" }>
  >;
  searchResult: FinanceSearchResult | null;
  workspace: FinanceWorkspace;
  onSearch: (e: FormEvent) => void;
  busy: boolean;
}) {
  return (
    <section className="space-y-6">
      <form
        onSubmit={onSearch}
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
  );
}
