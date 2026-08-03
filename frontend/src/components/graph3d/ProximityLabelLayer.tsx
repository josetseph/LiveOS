"use client";

export type ProximityLabel = {
  id: string;
  name: string;
  nodeType: string;
  sx: number;
  sy: number;
  opacity: number;
};

export type LinkLabel = {
  id: string;
  label: string;
  sx: number;
  sy: number;
  opacity: number;
};

export function ProximityLabelLayer({
  proximityLabels,
  linkLabels,
}: {
  proximityLabels: ProximityLabel[];
  linkLabels: LinkLabel[];
}) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
        zIndex: 20,
      }}
    >
      {proximityLabels.map((lbl) => (
        <div
          key={lbl.id}
          style={{
            position: "absolute",
            left: lbl.sx,
            top: lbl.sy,
            transform: "translate(-50%, calc(-100% - 10px))",
            color: "#ffffff",
            background: "rgba(0,0,0,0.62)",
            border: "1px solid rgba(255,255,255,0.18)",
            borderRadius: "999px",
            padding: "0.15rem 0.5rem",
            fontSize: "0.72rem",
            fontFamily: "system-ui, sans-serif",
            fontWeight: 600,
            opacity: lbl.opacity,
            textShadow: "0 1px 2px #000",
            whiteSpace: "nowrap",
            letterSpacing: "0.03em",
            pointerEvents: "none",
            userSelect: "none",
          }}
        >
          {lbl.name}
        </div>
      ))}
      {linkLabels.map((lbl) => (
        <div
          key={lbl.id}
          style={{
            position: "absolute",
            left: lbl.sx,
            top: lbl.sy,
            transform: "translate(-50%, -50%)",
            color: "rgba(203,213,225,0.9)",
            fontSize: "0.62rem",
            fontFamily: "system-ui, sans-serif",
            fontStyle: "italic",
            fontWeight: 400,
            opacity: lbl.opacity,
            textShadow: "0 1px 3px rgba(0,0,0,0.9), 0 0 6px rgba(0,0,0,0.7)",
            whiteSpace: "nowrap",
            letterSpacing: "0.04em",
            pointerEvents: "none",
            userSelect: "none",
          }}
        >
          {lbl.label}
        </div>
      ))}
    </div>
  );
}
