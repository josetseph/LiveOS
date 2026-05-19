"use client";

import { useState, useEffect, useRef } from "react";
import { Settings, Check, Loader2, AlertCircle, ChevronDown } from "lucide-react";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { ShaderBackground } from "@/components/shader-background";

const LOCAL_PROVIDERS = new Set(["local", "lm_studio", "ollama"]);

const PROVIDERS = [
    { value: "local", label: "Local / LM Studio" },
    { value: "ollama", label: "Ollama" },
    { value: "gemini", label: "Google Gemini" },
    { value: "openai", label: "OpenAI" },
    { value: "anthropic", label: "Anthropic" },
    { value: "huggingface", label: "HuggingFace" },
];

interface LLMSettings {
    provider: string;
    model: string;
    ingestion_model: string;
    base_url: string;
}

export default function SettingsPage() {
    const [settings, setSettings] = useState<LLMSettings | null>(null);
    const [form, setForm] = useState({ provider: "", model: "", ingestion_model: "", base_url: "" });
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        api
            .getLLMSettings()
            .then((s) => {
                setSettings(s);
                setForm({ provider: s.provider, model: s.model, ingestion_model: s.ingestion_model, base_url: s.base_url });
            })
            .catch(() => setError("Could not load settings. Is the backend running?"))
            .finally(() => setLoading(false));
    }, []);

    const isLocal = LOCAL_PROVIDERS.has(form.provider);

    async function handleSave() {
        if (!settings) return;
        setSaving(true);
        setError(null);
        setSaved(false);
        try {
            const patch: Partial<typeof form> = {};
            if (form.provider !== settings.provider) patch.provider = form.provider;
            if (form.model !== settings.model) patch.model = form.model;
            if (form.ingestion_model !== settings.ingestion_model) patch.ingestion_model = form.ingestion_model;
            if (isLocal && form.base_url !== settings.base_url) patch.base_url = form.base_url;

            if (Object.keys(patch).length === 0) {
                setSaved(true);
                if (savedTimer.current) clearTimeout(savedTimer.current);
                savedTimer.current = setTimeout(() => setSaved(false), 2000);
                return;
            }

            const updated = await api.updateLLMSettings(patch);
            setSettings(updated);
            setForm({ provider: updated.provider, model: updated.model, ingestion_model: updated.ingestion_model, base_url: updated.base_url });
            setSaved(true);
            if (savedTimer.current) clearTimeout(savedTimer.current);
            savedTimer.current = setTimeout(() => setSaved(false), 2000);
        } catch {
            setError("Failed to save. Check the server logs.");
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="relative min-h-screen bg-black text-white">
            <ShaderBackground />

            <div className="relative z-10 max-w-2xl mx-auto px-6 py-16">
                {/* Header */}
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mb-10"
                >
                    <div className="flex items-center gap-3 mb-2">
                        <Settings className="h-7 w-7 text-purple-400" />
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-white/60 bg-clip-text text-transparent">
                            Settings
                        </h1>
                    </div>
                    <p className="text-white/50 text-sm">
                        Configure the LLM provider and models. Changes take effect immediately — no restart needed.
                    </p>
                </motion.div>

                {loading ? (
                    <div className="flex items-center gap-2 text-white/40">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span className="text-sm">Loading…</span>
                    </div>
                ) : (
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.05 }}
                        className="space-y-6"
                    >
                        {/* Provider */}
                        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 space-y-4">
                            <h2 className="text-sm font-semibold text-white/70 uppercase tracking-wide">Provider</h2>
                            <div className="relative">
                                <select
                                    value={form.provider}
                                    onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))}
                                    className="w-full appearance-none rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 pr-10 text-sm text-white outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
                                >
                                    {PROVIDERS.map((p) => (
                                        <option key={p.value} value={p.value} className="bg-[#0d0d12]">
                                            {p.label}
                                        </option>
                                    ))}
                                </select>
                                <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
                            </div>

                            {isLocal && (
                                <div className="space-y-1.5">
                                    <label className="text-xs text-white/40">Server URL</label>
                                    <input
                                        type="text"
                                        value={form.base_url}
                                        onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                                        placeholder="http://127.0.0.1:1234"
                                        className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 font-mono text-sm text-white placeholder-white/25 outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
                                    />
                                    <p className="text-xs text-white/30">LM Studio: http://127.0.0.1:1234 · Ollama: http://127.0.0.1:11434</p>
                                </div>
                            )}

                            {!isLocal && (
                                <p className="text-xs text-amber-300/60 bg-amber-500/5 border border-amber-500/15 rounded-xl px-4 py-3">
                                    API keys for cloud providers are set in <code className="font-mono">backend/.env</code> and cannot be changed here.
                                </p>
                            )}
                        </div>

                        {/* Models */}
                        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 space-y-4">
                            <h2 className="text-sm font-semibold text-white/70 uppercase tracking-wide">Models</h2>

                            <div className="space-y-1.5">
                                <label className="text-xs text-white/40">Chat model</label>
                                <input
                                    type="text"
                                    value={form.model}
                                    onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                                    placeholder={isLocal ? "e.g. google/gemma-4-e4b" : "e.g. gemini-2.5-pro"}
                                    className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/25 outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
                                />
                                <p className="text-xs text-white/30">Used for all chat queries.</p>
                            </div>

                            <div className="space-y-1.5">
                                <label className="text-xs text-white/40">Ingestion model</label>
                                <input
                                    type="text"
                                    value={form.ingestion_model}
                                    onChange={(e) => setForm((f) => ({ ...f, ingestion_model: e.target.value }))}
                                    placeholder={isLocal ? "e.g. google/gemma-4-e4b" : "e.g. gemini-2.5-pro"}
                                    className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/25 outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
                                />
                                <p className="text-xs text-white/30">Used during note ingestion (extraction, entity reasoning). Leave blank to use the chat model.</p>
                            </div>
                        </div>

                        {/* Error */}
                        {error && (
                            <div className="flex items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                                <AlertCircle className="h-4 w-4 shrink-0" />
                                {error}
                            </div>
                        )}

                        {/* Save */}
                        <div className="flex justify-end">
                            <button
                                onClick={handleSave}
                                disabled={saving || saved}
                                className="inline-flex w-36 items-center justify-center gap-2 rounded-xl bg-purple-600 px-6 py-2.5 text-sm font-medium text-white transition hover:bg-purple-500 disabled:opacity-60"
                            >
                                {saving ? (
                                    <><Loader2 className="h-4 w-4 animate-spin" /> Saving…</>
                                ) : saved ? (
                                    <><Check className="h-4 w-4" /> Saved</>
                                ) : (
                                    "Save changes"
                                )}
                            </button>
                        </div>
                    </motion.div>
                )}
            </div>
        </div>
    );
}
