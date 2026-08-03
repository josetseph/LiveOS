"use client";

import { useEffect, useRef, useState, type MutableRefObject } from "react";

export function useGraphSearch(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  nodesRef: MutableRefObject<any[]>,
) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchOpenRef = useRef(false);

  // ── Search results — filter nodes client-side as user types ──
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    const q = searchQuery.toLowerCase();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const results = (nodesRef.current as any[])
      .filter((n) => (n.name ?? "").toLowerCase().includes(q))
      .sort((a, b) => {
        const aStarts = (a.name ?? "").toLowerCase().startsWith(q);
        const bStarts = (b.name ?? "").toLowerCase().startsWith(q);
        if (aStarts && !bStarts) return -1;
        if (!aStarts && bStarts) return 1;
        return (a.name ?? "").localeCompare(b.name ?? "");
      })
      .slice(0, 8);
    setSearchResults(results);
  }, [searchQuery]); // nodesRef is a stable ref mirror of graph nodes

  return {
    searchOpen,
    setSearchOpen,
    searchQuery,
    setSearchQuery,
    searchResults,
    searchInputRef,
    searchOpenRef,
  };
}
