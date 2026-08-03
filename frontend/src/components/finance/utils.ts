export const FIELD_INPUT =
  "w-full rounded-lg border border-white/15 bg-black/50 px-3 py-2 text-sm text-white focus:border-teal-400/50 focus:outline-none";

export type TabId =
  | "overview"
  | "accounts"
  | "transactions"
  | "budgets"
  | "categories"
  | "recurring"
  | "rules"
  | "search"
  | "reports";

export function tomorrowIso() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

export function errMessage(err: unknown, fallback: string): string {
  if (typeof err === "object" && err && "response" in err) {
    const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map(String).join("; ");
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

export function money(value: number, currency?: string | null) {
  const amount = Number.isFinite(value) ? value.toFixed(2) : "0.00";
  return currency ? `${amount} ${currency}` : amount;
}

export function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export function monthStartIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}
