"use client";

import type { SelectedEntity } from "./types";

interface NodeDetailPanelProps {
  entity: SelectedEntity | null;
  onClose: () => void;
}

export function NodeDetailPanel({ entity, onClose }: NodeDetailPanelProps) {
  if (!entity) return null;

  const isCommunity = entity.kind === "community";

  return (
    <div
      style={{
        position: "absolute",
        top: "1rem",
        right: "1rem",
        width: "min(22rem, calc(100vw - 7rem))",
        background: "rgba(10,10,20,0.88)",
        border: "1px solid rgba(192,132,252,0.35)",
        borderRadius: "0.75rem",
        padding: "1.2rem 1.4rem",
        color: "#e2e8f0",
        fontFamily: "var(--font-geist-sans, system-ui, sans-serif)",
        backdropFilter: "blur(12px)",
        boxShadow: "0 0 40px rgba(192,132,252,0.15)",
        zIndex: 50,
        maxHeight: "80vh",
        overflowY: "auto",
      }}
    >
      {/* Header */}
      <div
        style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}
      >
        <div style={{ flex: 1, marginRight: "0.5rem" }}>
          <span
            style={{
              fontSize: "0.65rem",
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              color: "#a855f7",
              fontWeight: 600,
            }}
          >
            {isCommunity ? "Community" : entity.data.node_type}
          </span>
          <h3
            style={{ margin: "0.2rem 0 0", fontSize: "1rem", fontWeight: 700, lineHeight: 1.3, color: "#f8fafc" }}
          >
            {entity.data.name}
          </h3>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          style={{
            background: "none",
            border: "1px solid rgba(255,255,255,0.15)",
            borderRadius: "50%",
            width: "1.6rem",
            height: "1.6rem",
            color: "#94a3b8",
            cursor: "pointer",
            fontSize: "0.85rem",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          ×
        </button>
      </div>

      <hr style={{ border: "none", borderTop: "1px solid rgba(255,255,255,0.08)", margin: "0 0 0.85rem" }} />

      {isCommunity && entity.kind === "community" ? (
        <>
          {entity.data.summary && (
            <Section label="Summary">
              <p style={textStyle}>{entity.data.summary}</p>
            </Section>
          )}
          {entity.data.themes?.length > 0 && (
            <Section label="Themes">
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
                {entity.data.themes.map((t) => (
                  <Tag key={t}>{t}</Tag>
                ))}
              </div>
            </Section>
          )}
          <Section label="Members">
            <p style={{ ...textStyle, color: "#a855f7" }}>{entity.data.member_count} nodes</p>
          </Section>
          <Section label="Level">
            <p style={textStyle}>{entity.data.community_level}</p>
          </Section>
        </>
      ) : entity.kind === "node" ? (
        <>
          {entity.data.description && (
            <Section label="Description">
              <p style={textStyle}>{entity.data.description}</p>
            </Section>
          )}
          {entity.data.facts && entity.data.facts.length > 0 && (
            <Section label="Facts">
              <ul style={{ margin: 0, paddingLeft: "1rem" }}>
                {entity.data.facts.map((fact, i) => (
                  <li key={i} style={{ ...textStyle, marginBottom: "0.35rem" }}>{fact}</li>
                ))}
              </ul>
            </Section>
          )}
          {entity.data.domain && (
            <Section label="Domain">
              <p style={{ ...textStyle, color: "#7dd3fc" }}>{entity.data.domain}</p>
            </Section>
          )}
          {entity.data.status && (
            <Section label="Status">
              <Tag>{entity.data.status}</Tag>
            </Section>
          )}
        </>
      ) : null}
    </div>
  );
}

// ── Small helpers ────────────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "0.85rem" }}>
      <p
        style={{
          margin: "0 0 0.25rem",
          fontSize: "0.65rem",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "#64748b",
          fontWeight: 600,
        }}
      >
        {label}
      </p>
      {children}
    </div>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-block",
        background: "rgba(192,132,252,0.12)",
        border: "1px solid rgba(192,132,252,0.25)",
        borderRadius: "999px",
        padding: "0.1rem 0.55rem",
        fontSize: "0.72rem",
        color: "#c084fc",
      }}
    >
      {children}
    </span>
  );
}

const textStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "0.82rem",
  lineHeight: 1.55,
  color: "#cbd5e1",
};
