export function BasicSummaryList({ basic }: { basic: Record<string, unknown> }) {
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
