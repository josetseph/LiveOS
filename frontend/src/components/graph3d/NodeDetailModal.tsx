"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { KnowledgeNode } from "@/components/graph3d/types";
import { nodeColor } from "@/components/graph3d/nodeColors";

export function NodeDetailModal({
  node,
  onClose,
  kb,
}: {
  node: KnowledgeNode;
  onClose: () => void;
  kb: string;
}) {
  const color = nodeColor(node.node_type);
  const cardRef = useRef<HTMLDivElement>(null);
  const [detail, setDetail] = useState<KnowledgeNode | null>(null);
  const [fetching, setFetching] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFetching(true);
    api
      .getNodeDetail(node.node_id, kb)
      .then((d) => {
        if (!cancelled) setDetail({ ...node, ...d });
      })
      .catch(() => {
        if (!cancelled) setDetail(node);
      })
      .finally(() => {
        if (!cancelled) setFetching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [node.node_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const display = detail ?? node;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.78)",
        backdropFilter: "blur(6px)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          position: "relative",
          maxWidth: 400,
          width: "100%",
          margin: "0 1.5rem",
        }}
      >
        <button
          onClick={onClose}
          style={{
            position: "absolute",
            top: -44,
            right: 0,
            background: "none",
            border: "none",
            color: "#fff",
            cursor: "pointer",
            padding: 4,
            lineHeight: 1,
          }}
          aria-label="Close"
        >
          <svg
            width={28}
            height={28}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
          >
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>

        <div style={{ width: "100%" }}>
          <div
            ref={cardRef}
            style={{
              borderRadius: 16,
              background: "#0a0e1a",
              border: `1px solid ${color}55`,
              padding: "20px 22px",
              boxShadow: `0 0 40px ${color}22, rgba(0,0,0,0.29) 0px 21px 46px`,
              cursor: "default",
            }}
          >
            <div
              style={{
                fontSize: 10,
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                color,
                fontWeight: 700,
                marginBottom: 8,
                fontFamily: "system-ui, sans-serif",
              }}
            >
              {display.node_type}
            </div>
            <h2
              style={{
                margin: "0 0 12px",
                fontSize: 20,
                fontWeight: 800,
                color: "#f8fafc",
                lineHeight: 1.25,
                fontFamily: "system-ui, sans-serif",
              }}
            >
              {display.name}
            </h2>
            {fetching && (
              <div
                style={{
                  fontSize: 12,
                  color: "#475569",
                  fontFamily: "system-ui, sans-serif",
                  marginBottom: 8,
                }}
              >
                Loading details…
              </div>
            )}
            {display.description && (
              <p
                style={{
                  margin: "0 0 12px",
                  fontSize: 13,
                  color: "#94a3b8",
                  lineHeight: 1.6,
                  fontFamily: "system-ui, sans-serif",
                }}
              >
                {display.description}
              </p>
            )}
            {display.isolated_contexts && display.isolated_contexts.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <div
                  style={{
                    fontSize: 9,
                    textTransform: "uppercase",
                    letterSpacing: "0.1em",
                    color: "#475569",
                    fontWeight: 700,
                    marginBottom: 6,
                    fontFamily: "system-ui, sans-serif",
                  }}
                >
                  Contexts
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {display.isolated_contexts.slice(0, 4).map((ctx, i) => (
                    <div
                      key={i}
                      style={{
                        fontSize: 12,
                        color: "#cbd5e1",
                        lineHeight: 1.55,
                        fontFamily: "system-ui, sans-serif",
                        borderLeft: "2px solid #334155",
                        paddingLeft: 10,
                        fontStyle: "italic",
                      }}
                    >
                      {ctx}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {(display as { community_name?: string; community_id?: string })
              .community_name ||
            (display as { community_id?: string }).community_id ? (
              <div
                style={{
                  fontSize: 12,
                  color: "#94a3b8",
                  fontFamily: "system-ui, sans-serif",
                  marginBottom: 10,
                }}
              >
                Community:{" "}
                {(display as { community_name?: string }).community_name ||
                  (display as { community_id?: string }).community_id}
              </div>
            ) : null}
            {Array.isArray(
              (
                display as {
                  connections?: {
                    node_id: string;
                    name: string;
                    relationship?: string;
                  }[];
                }
              ).connections,
            ) &&
              (
                (
                  display as {
                    connections?: {
                      node_id: string;
                      name: string;
                      relationship?: string;
                    }[];
                  }
                ).connections || []
              ).length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div
                    style={{
                      fontSize: 9,
                      textTransform: "uppercase",
                      letterSpacing: "0.1em",
                      color: "#475569",
                      fontWeight: 700,
                      marginBottom: 6,
                      fontFamily: "system-ui, sans-serif",
                    }}
                  >
                    Connections
                  </div>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
                      maxHeight: 140,
                      overflowY: "auto",
                    }}
                  >
                    {(
                      (
                        display as {
                          connections?: {
                            node_id: string;
                            name: string;
                            relationship?: string;
                          }[];
                        }
                      ).connections || []
                    )
                      .slice(0, 8)
                      .map((conn) => (
                        <div
                          key={conn.node_id}
                          style={{
                            fontSize: 12,
                            color: "#e2e8f0",
                            fontFamily: "system-ui, sans-serif",
                          }}
                        >
                          {conn.name}
                          {conn.relationship ? (
                            <span style={{ color: "#64748b" }}>
                              {" "}
                              · {conn.relationship}
                            </span>
                          ) : null}
                        </div>
                      ))}
                  </div>
                </div>
              )}
            {!fetching &&
              !display.description &&
              !(display.isolated_contexts && display.isolated_contexts.length) &&
              !(
                Array.isArray(
                  (display as { connections?: unknown[] }).connections,
                ) &&
                ((display as { connections?: unknown[] }).connections || [])
                  .length
              ) && (
                <p
                  style={{
                    margin: 0,
                    fontSize: 12,
                    color: "#64748b",
                    lineHeight: 1.55,
                    fontFamily: "system-ui, sans-serif",
                  }}
                >
                  No stored contexts yet for this node. Re-ingest related notes
                  if content should appear here.
                </p>
              )}
            {display.domain && (
              <div
                style={{
                  fontSize: 11,
                  color: "#7dd3fc",
                  fontFamily: "system-ui, sans-serif",
                }}
              >
                {display.domain}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
