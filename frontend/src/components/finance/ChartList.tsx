export function ChartList({ data }: { data: unknown }) {
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
