"use client";

import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: string | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(e: Error) {
    return { error: e.message };
  }
  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            background: "#000",
            gap: "1rem",
            color: "#f87171",
          }}
        >
          <p
            style={{
              fontSize: "0.9rem",
              maxWidth: "32rem",
              textAlign: "center",
              color: "#94a3b8",
            }}
          >
            {this.state.error}
          </p>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              padding: "0.4rem 1rem",
              background: "rgba(168,85,247,0.2)",
              border: "1px solid rgba(168,85,247,0.5)",
              borderRadius: "0.4rem",
              color: "#c084fc",
              cursor: "pointer",
              fontSize: "0.8rem",
            }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
