import { Trash2 } from "lucide-react";

export function DeletableList({
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
