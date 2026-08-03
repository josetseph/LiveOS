"use client";

import type { RefObject } from "react";
import { nodeColor } from "@/components/graph3d/nodeColors";

export function GraphSearchOverlay({
  searchOpen,
  setSearchOpen,
  searchQuery,
  setSearchQuery,
  searchResults,
  searchInputRef,
  flyToNode,
}: {
  searchOpen: boolean;
  setSearchOpen: (open: boolean) => void;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  searchResults: any[];
  searchInputRef: RefObject<HTMLInputElement | null>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  flyToNode: (node: any) => void;
}) {
  return (
    <div
      style={{
        position: "absolute",
        top: "1.5rem",
        right: "1.5rem",
        zIndex: 50,
        display: "flex",
        flexDirection: "column",
        gap: "0.25rem",
        alignItems: "flex-end",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      {!searchOpen ? (
        <button
          onClick={() => setSearchOpen(true)}
          style={{
            background: "rgba(10,10,20,0.75)",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 12,
            padding: "0.45rem 0.9rem",
            color: "#94a3b8",
            fontSize: "0.75rem",
            letterSpacing: "0.04em",
            backdropFilter: "blur(8px)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: "0.4rem",
          }}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          Search
          <kbd
            style={{
              background: "rgba(255,255,255,0.08)",
              border: "1px solid rgba(255,255,255,0.15)",
              borderRadius: 4,
              padding: "0 0.3rem",
              fontSize: "0.68rem",
              lineHeight: "1.6",
            }}
          >
            /
          </kbd>
        </button>
      ) : (
        <div
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) {
              setSearchOpen(false);
              setSearchQuery("");
            }
          }}
          style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}
        >
          <input
            ref={searchInputRef}
            autoFocus
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setSearchOpen(false);
                setSearchQuery("");
              }
              if (e.key === "Enter" && searchResults.length > 0) {
                flyToNode(searchResults[0]);
                setSearchOpen(false);
                setSearchQuery("");
              }
            }}
            placeholder="Search nodes…"
            style={{
              background: "rgba(10,10,20,0.92)",
              border: "1px solid rgba(255,255,255,0.2)",
              borderRadius: 10,
              padding: "0.5rem 1rem",
              color: "#f1f5f9",
              fontSize: "0.85rem",
              width: 260,
              outline: "none",
              boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
            }}
          />
          {searchResults.length > 0 && (
            <div
              style={{
                background: "rgba(10,10,20,0.96)",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 10,
                overflow: "hidden",
                width: 260,
                boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
              }}
            >
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              {searchResults.map((n: any, i: number) => (
                <button
                  key={n.node_id ?? i}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    flyToNode(n);
                    setSearchOpen(false);
                    setSearchQuery("");
                  }}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    width: "100%",
                    padding: "0.5rem 1rem",
                    border: "none",
                    borderBottom:
                      i < searchResults.length - 1
                        ? "1px solid rgba(255,255,255,0.06)"
                        : "none",
                    background: "transparent",
                    color: "#e2e8f0",
                    fontSize: "0.82rem",
                    cursor: "pointer",
                    textAlign: "left",
                    fontFamily: "system-ui, sans-serif",
                    gap: "0.1rem",
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background =
                      "rgba(255,255,255,0.07)")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background = "transparent")
                  }
                >
                  <span
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "0.4rem",
                    }}
                  >
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: nodeColor(n.node_type ?? ""),
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ fontWeight: 600 }}>{n.name}</span>
                  </span>
                  <span
                    style={{
                      color: "#475569",
                      fontSize: "0.70rem",
                      paddingLeft: "1.2rem",
                    }}
                  >
                    {n.node_type ?? ""}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
