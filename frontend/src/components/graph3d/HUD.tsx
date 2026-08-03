"use client";

export function HUD({
  nodeCount,
  edgeCount,
}: {
  nodeCount: number;
  edgeCount: number;
}) {
  return (
    <>
      <div
        style={{
          position: "absolute",
          top: "1.5rem",
          left: "1.5rem",
          zIndex: 40,
          background: "rgba(10,10,20,0.75)",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: 12,
          padding: "0.5rem 1rem",
          color: "#94a3b8",
          fontSize: "0.75rem",
          letterSpacing: "0.04em",
          backdropFilter: "blur(8px)",
          userSelect: "none",
          pointerEvents: "none",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <span style={{ color: "#e879f9", fontWeight: 700 }}>
          {nodeCount.toLocaleString()}
        </span>
        <span style={{ margin: "0 0.4em" }}>nodes</span>
        <span style={{ color: "#475569" }}>·</span>
        <span
          style={{ color: "#22d3ee", fontWeight: 700, marginLeft: "0.4em" }}
        >
          {edgeCount.toLocaleString()}
        </span>
        <span style={{ marginLeft: "0.4em" }}>edges</span>
      </div>
      <div
        style={{
          position: "absolute",
          bottom: "1.5rem",
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 40,
          background: "rgba(10,10,20,0.7)",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: "999px",
          padding: "0.45rem 1.2rem",
          color: "#94a3b8",
          fontSize: "0.75rem",
          letterSpacing: "0.04em",
          backdropFilter: "blur(8px)",
          userSelect: "none",
          pointerEvents: "none",
          whiteSpace: "nowrap",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        Drag to look &nbsp;·&nbsp; Right drag to pan &nbsp;·&nbsp; Scroll to fly
        &nbsp;·&nbsp; WASD to move &nbsp;·&nbsp; Q/E for up/down &nbsp;·&nbsp;
        Click node for details &nbsp;·&nbsp; / to search
      </div>
    </>
  );
}
