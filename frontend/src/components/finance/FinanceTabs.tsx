import type { TabId } from "./utils";

const TABS: { id: TabId; label: string }[] = [
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

export function FinanceTabs({
  tab,
  onSelect,
}: {
  tab: TabId;
  onSelect: (id: TabId) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2 border-b border-white/10 pb-2">
      {TABS.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onSelect(item.id)}
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
  );
}
