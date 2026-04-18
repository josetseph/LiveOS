// Vivid palette for the long tail of unknown types.
// 24 saturated colors that are visually distinct from each other.
const TAIL_PALETTE = [
  "#f43f5e", "#fb923c", "#facc15", "#a3e635", "#34d399",
  "#22d3ee", "#38bdf8", "#818cf8", "#a78bfa", "#e879f9",
  "#f472b6", "#4ade80", "#2dd4bf", "#60a5fa", "#c084fc",
  "#fde047", "#fb7185", "#86efac", "#67e8f9", "#fca5a5",
  "#fdba74", "#fcd34d", "#d8b4fe", "#f9a8d4",
];

function hashColor(type: string): string {
  let h = 0;
  for (let i = 0; i < type.length; i++) {
    h = (h * 31 + type.charCodeAt(i)) >>> 0;
  }
  return TAIL_PALETTE[h % TAIL_PALETTE.length];
}

export function nodeColor(type: string): string {
  switch (type.toLowerCase()) {
    // ── Core system types ──────────────────────────────────────────────
    case "concept": return "#22d3ee";
    case "entity": return "#a855f7";
    case "community": return "#e879f9";
    case "task": return "#fb7185";
    case "reference": return "#fbbf24";
    case "person": return "#34d399";
    case "persona trait": return "#c084fc";
    case "note": return "#60a5fa";
    // ── Common graph node types ────────────────────────────────────────
    case "organization": return "#fb923c";
    case "place": return "#38bdf8";
    case "location": return "#4ade80";
    case "event": return "#f472b6";
    case "date": return "#a3e635";
    case "time_period": return "#bef264";
    case "year": return "#d9f99d";
    case "film": return "#f87171";
    case "album": return "#c084fc";
    case "song": return "#a78bfa";
    case "book": return "#fdba74";
    case "group": return "#67e8f9";
    case "band": return "#d8b4fe";
    case "profession": return "#fde68a";
    case "position": return "#fcd34d";
    case "role": return "#86efac";
    case "genre": return "#fca5a5";
    case "award": return "#fbbf24";
    case "country": return "#6ee7b7";
    case "city": return "#93c5fd";
    case "region": return "#7dd3fc";
    case "character": return "#f9a8d4";
    case "team": return "#fb923c";
    case "product": return "#e2e8f0";
    case "tournament": return "#fde68a";
    case "championship": return "#fcd34d";
    case "title": return "#a5f3fc";
    // ── Everything else: deterministic vivid color from type name ──────
    default: return type ? hashColor(type.toLowerCase()) : "#94a3b8";
  }
}
