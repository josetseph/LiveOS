import type { ReactNode } from "react";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm text-white/70">
      <span className="mb-1.5 block text-white/50">{label}</span>
      {children}
    </label>
  );
}
