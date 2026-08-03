import type { ReactNode } from "react";
import { money } from "./utils";

export function MetricCard({
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
