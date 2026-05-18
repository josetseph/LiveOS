"use client";

import {
    createContext,
    useContext,
    useState,
    useEffect,
    useCallback,
    type ReactNode,
} from "react";

const STORAGE_KEY = "liveos_current_kb";

interface StoredKB {
    slug: string;
    name: string;
}

interface KBContextValue {
    /** Slug of the active KB — used as the `?kb=` query param. */
    currentKB: string;
    /** Human-readable display name of the active KB. */
    currentKBName: string;
    /** Switch to a KB by slug and display name. */
    setCurrentKB: (slug: string, displayName?: string) => void;
    /** Update only the display name (e.g. after a rename). */
    setCurrentKBName: (name: string) => void;
}

const KBContext = createContext<KBContextValue>({
    currentKB: "default",
    currentKBName: "default",
    setCurrentKB: () => { },
    setCurrentKBName: () => { },
});

function readStorage(): StoredKB {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return { slug: "default", name: "default" };
        // Handle old format (plain string slug).
        if (!raw.startsWith("{")) return { slug: raw, name: raw };
        const parsed = JSON.parse(raw) as StoredKB;
        return { slug: parsed.slug || "default", name: parsed.name || parsed.slug || "default" };
    } catch {
        return { slug: "default", name: "default" };
    }
}

function writeStorage(kb: StoredKB) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(kb));
    } catch {
        // Ignore write failures.
    }
}

export function KBProvider({ children }: { children: ReactNode }) {
    const [current, setCurrent] = useState<StoredKB>({ slug: "default", name: "default" });

    useEffect(() => {
        setCurrent(readStorage());
    }, []);

    const setCurrentKB = useCallback((slug: string, displayName?: string) => {
        const normalized = slug.trim() || "default";
        const name = displayName?.trim() || normalized;
        const kb: StoredKB = { slug: normalized, name };
        setCurrent(kb);
        writeStorage(kb);
    }, []);

    const setCurrentKBName = useCallback((name: string) => {
        setCurrent((prev) => {
            const updated = { ...prev, name: name.trim() || prev.slug };
            writeStorage(updated);
            return updated;
        });
    }, []);

    return (
        <KBContext.Provider
            value={{
                currentKB: current.slug,
                currentKBName: current.name,
                setCurrentKB,
                setCurrentKBName,
            }}
        >
            {children}
        </KBContext.Provider>
    );
}

/** Hook: returns the current KB slug, display name, and setters. */
export function useKB(): KBContextValue {
    return useContext(KBContext);
}
