import type { ReactNode } from "react";

export function Panel({
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
