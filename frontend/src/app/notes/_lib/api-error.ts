export function getApiErrorDetail(error: unknown): string | null {
  if (!error || typeof error !== "object" || !("response" in error)) {
    return null;
  }
  const detail = (error as { response?: { data?: { detail?: unknown } } })
    .response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) =>
        typeof d === "object" && d && "msg" in d
          ? String((d as { msg: string }).msg)
          : String(d),
      )
      .join("; ");
  }
  return null;
}
