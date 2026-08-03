import { Wallet } from "lucide-react";

export function FinanceHeader({ currentKB }: { currentKB: string }) {
  return (
    <div className="mb-8 flex items-center gap-3">
      <Wallet className="h-7 w-7 text-teal-300" />
      <div>
        <h1 className="text-2xl font-semibold">Finance</h1>
        <p className="text-sm text-white/50">
          Native Firefly III ledger — scoped to {currentKB}
        </p>
      </div>
    </div>
  );
}
