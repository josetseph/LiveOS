"use client";

import { useEffect, useState } from "react";
import { X, Settings, Check, Loader2, AlertCircle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { api } from "@/lib/api";

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

interface Props {
    open: boolean;
    onClose: () => void;
}

export function ModelSettingsModal({ open, onClose }: Props) {
    const [settings, setSettings] = useState<LLMSettings | null>(null);
    const [form, setForm] = useState({ provider: "", model: "", ingestion_model: "", base_url: "" });
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Fetch current settings when modal opens
    useEffect(() => {
        if (!open) return;
        setLoading(true);
        setError(null);
        setSaved(false);
        api
            .getLLMSettings()
            .then((s) => {
                setSettings(s);
                setForm({ provider: s.provider, model: s.model, ingestion_model: s.ingestion_model, base_url: s.base_url });
            })
            .catch(() => setError("Could not load current settings."))
            .finally(() => setLoading(false));
    }, [open]);

    const isLocal = LOCAL_PROVIDERS.has(form.provider);

    const handleSave = async () => {
        if (!settings) return;
        setSaving(true);
        setError(null);
        setSaved(false);
        try {
            const patch: Partial<typeof form> = {};
            if (form.provider !== settings.provider) patch.provider = form.provider;
            if (form.model !== settings.model) patch.model = form.model;
            if (form.ingestion_model !== settings.ingestion_model)
                patch.ingestion_model = form.ingestion_model;
            if (isLocal && form.base_url !== settings.base_url)
                patch.base_url = form.base_url;

            if (Object.keys(patch).length === 0) {
                onClose();
                return;
            }

            const updated = await api.updateLLMSettings(patch);
            setSettings(updated);
            setForm({
                provider: updated.provider,
                model: updated.model,
                ingestion_model: updated.ingestion_model,
                base_url: updated.base_url,
            });
            setSaved(true);
            setTimeout(onClose, 800);
        } catch {
            setError("Failed to save settings. Check the server logs.");
        } finally {
            setSaving(false);
        }
    };

    return (
        <AnimatePresence>
            {open && (
                <>
                    {/* Backdrop */}
                    <motion.div
                        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={onClose}
                    />

                    {/* Modal */}
                    <motion.div
                        className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2"
                        initial={{ opacity: 0, scale: 0.95, y: 8 }}
                        animate={{ opacity: 1, scale: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.95, y: 8 }}
                        transition={{ duration: 0.15 }}
                    >
                        <div className="rounded-2xl border border-white/10 bg-[#0d0d12] shadow-2xl">
                            {/* Header */}
                            <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
                                <div className="flex items-center gap-2">
                                    <Settings className="h-4 w-4 text-purple-400" />
                                    <span className="font-semibold text-white">Model Settings</span>
                                </div>
                                <button
                                    onClick={onClose}
                                    className="rounded-lg p-1 text-white/40 transition-colors hover:bg-white/5 hover:text-white/70"
                                >
                                    <X className="h-4 w-4" />
                                </button>
                            </div>

                            {/* Body */}
                            <div className="space-y-5 p-6">
                                {loading ? (
                                    <div className="flex items-center justify-center py-8">
                                        <Loader2 className="h-5 w-5 animate-spin text-purple-400" />
                                    </div>
                                ) : (
                                    <>
                                        {/* Provider */}
                                        <div className="space-y-1.5">
                                            <label className="text-xs font-medium text-white/50 uppercase tracking-wide">
                                                Provider
                                            </label>
                                            <select
                                                value={form.provider}
                                                onChange={(e) =>
                                                    setForm((f) => ({ ...f, provider: e.target.value }))
                                                }
                                                className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
                                            >
                                                {PROVIDERS.map((p) => (
                                                    <option
                                                        key={p.value}
                                                        value={p.value}
                                                        className="bg-[#0d0d12]"
                                                    >
                                                        {p.label}
                                                    </option>
                                                ))}
                                            </select>
                                        </div>

                                        {/* Model name */}
                                        <div className="space-y-1.5">
                                            <label className="text-xs font-medium text-white/50 uppercase tracking-wide">
                                                Chat Model
                                            </label>
                                            <input
                                                type="text"
                                                value={form.model}
                                                onChange={(e) =>
                                                    setForm((f) => ({ ...f, model: e.target.value }))
                                                }
                                                placeholder={
                                                    isLocal
                                                        ? "e.g. google/gemma-4-e4b"
                                                        : "e.g. gemini-2.5-pro"
                                                }
                                                className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-white/25 outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
                                            />
                                            <p className="text-xs text-white/30">
                                                {isLocal
                                                    ? "Model name exactly as shown in your local server"
                                                    : "Model identifier for the selected cloud provider"}
                                            </p>
                                        </div>

                                        {/* Ingestion model */}
                                        <div className="space-y-1.5">
                                            <label className="text-xs font-medium text-white/50 uppercase tracking-wide">
                                                Ingestion Model
                                            </label>
                                            <input
                                                type="text"
                                                value={form.ingestion_model}
                                                onChange={(e) =>
                                                    setForm((f) => ({ ...f, ingestion_model: e.target.value }))
                                                }
                                                placeholder={
                                                    isLocal
                                                        ? "e.g. google/gemma-4-e4b"
                                                        : "e.g. gemini-2.5-pro"
                                                }
                                                className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-white/25 outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
                                            />
                                            <p className="text-xs text-white/30">
                                                Used during note ingestion (extraction, entity reasoning). Leave blank to use the chat model.
                                            </p>
                                        </div>

                                        {/* Base URL — local providers only */}
                                        {isLocal && (
                                            <div className="space-y-1.5">
                                                <label className="text-xs font-medium text-white/50 uppercase tracking-wide">
                                                    Server URL
                                                </label>
                                                <input
                                                    type="text"
                                                    value={form.base_url}
                                                    onChange={(e) =>
                                                        setForm((f) => ({ ...f, base_url: e.target.value }))
                                                    }
                                                    placeholder="http://127.0.0.1:1234"
                                                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 font-mono text-sm text-white placeholder-white/25 outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
                                                />
                                                <p className="text-xs text-white/30">
                                                    LM Studio: http://127.0.0.1:1234 · Ollama:
                                                    http://127.0.0.1:11434
                                                </p>
                                            </div>
                                        )}

                                        {/* Cloud provider note */}
                                        {!isLocal && (
                                            <p className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-300/70">
                                                API keys for cloud providers are configured in{" "}
                                                <code className="font-mono">backend/.env</code> and cannot be changed here.
                                            </p>
                                        )}

                                        {/* Error */}
                                        {error && (
                                            <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2">
                                                <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
                                                <p className="text-xs text-red-300">{error}</p>
                                            </div>
                                        )}
                                    </>
                                )}
                            </div>

                            {/* Footer */}
                            {!loading && (
                                <div className="flex items-center justify-end gap-3 border-t border-white/10 px-6 py-4">
                                    <button
                                        onClick={onClose}
                                        className="rounded-lg px-4 py-2 text-sm text-white/50 transition hover:bg-white/5 hover:text-white/70"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        onClick={handleSave}
                                        disabled={saving || saved}
                                        className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-purple-500 disabled:opacity-60"
                                    >
                                        {saving ? (
                                            <>
                                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                                Saving…
                                            </>
                                        ) : saved ? (
                                            <>
                                                <Check className="h-3.5 w-3.5" />
                                                Saved
                                            </>
                                        ) : (
                                            "Save"
                                        )}
                                    </button>
                                </div>
                            )}
                        </div>
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
}
