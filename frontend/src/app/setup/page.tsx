"use client";

import { useEffect, useState } from "react";
import { Sparkles, FolderOpen, Brain, Cloud, SkipForward, Check } from "lucide-react";
import { api } from "@/lib/api";
import { pickDesktopDirectory, getDesktopBridge } from "@/lib/desktop";
import { ShaderBackground } from "@/components/shader-background";
import type { SetupStatus } from "@/lib/types";

type AiMode = "local" | "cloud" | "hybrid" | "none";

type CatalogOption = {
  id: string;
  label: string;
  family: string;
  params: string;
  size_gb: number;
  min_ram_gb: number;
  recommended?: boolean;
  fits_budget?: boolean;
};

type ModelCatalog = {
  hardware: {
    ram_gb: number;
    usable_model_gb: number;
    accel?: { backend?: string };
  };
  embed: CatalogOption | null;
  reranker: CatalogOption | null;
  chat_options: CatalogOption[];
  suggested_chat: CatalogOption | null;
  selected_chat?: CatalogOption | null;
  budget_note: string;
};

export default function SetupPage() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [dataDir, setDataDir] = useState("");
  const [modelsDir, setModelsDir] = useState("");
  const [vaultPath, setVaultPath] = useState("");
  const [aiMode, setAiMode] = useState<AiMode>("none");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [chatId, setChatId] = useState<string>("");
  const [downloadMsg, setDownloadMsg] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [mmBusy, setMmBusy] = useState(false);
  const canBrowse = Boolean(getDesktopBridge()?.pickDirectory);

  useEffect(() => {
    api
      .getSetupStatus()
      .then((s) => {
        setStatus(s);
        setDataDir(s.data_dir);
        setModelsDir(s.models_dir);
        setVaultPath(s.default_vault_path || s.active_vault_path || "");
        setAiMode((s.ai_setup_mode as AiMode) || "none");
      })
      .catch(() => setError("Could not load setup status."));
  }, []);

  async function browseInto(
    setter: (v: string) => void,
    title: string,
    current: string,
  ) {
    const dir = await pickDesktopDirectory({
      title,
      defaultPath: current || undefined,
    });
    if (dir) setter(dir);
  }

  useEffect(() => {
    if (aiMode !== "local") return;
    api
      .getModelCatalog()
      .then((c: ModelCatalog) => {
        setCatalog(c);
        // Prefer last saved selection over hardware suggestion so reopening Setup
        // does not snap back to the suggested E4B.
        const saved = c.selected_chat?.id;
        const suggested = c.suggested_chat?.id;
        const firstFit =
          c.chat_options.find((o) => o.fits_budget !== false)?.id ||
          c.chat_options[0]?.id ||
          "";
        setChatId((prev) => prev || saved || suggested || firstFit);
      })
      .catch(() => setError("Could not load model catalog."));
  }, [aiMode]);

  function startBackgroundMultimodal() {
    setMmBusy(true);
    setDownloadMsg("Chat stack ready. Fetching Florence / Whisper / Marlin in the background…");
    void api
      .downloadModels(true, undefined, { multimodalOnly: true })
      .then(async () => {
        try {
          const mm = await api.getMultimodalStatus();
          const models = (mm as { models?: Record<string, boolean> })?.models || {};
          const ready = ["florence", "whisper", "marlin"]
            .filter((k) => models[k])
            .join(", ");
          const missing = ["florence", "whisper", "marlin"]
            .filter((k) => !models[k])
            .join(", ");
          setDownloadMsg(
            missing
              ? `Multimedia partial (${ready || "none"} ready; still missing: ${missing}). You can use Chat; retry download later for video/images.`
              : "All local models on disk. They load into memory only when you use Chat / ingest.",
          );
        } catch {
          setDownloadMsg(
            "Chat stack ready. Multimedia download finished (status check failed — open Setup again to verify).",
          );
        }
      })
      .catch(() => {
        setDownloadMsg(
          "Chat stack ready. Multimedia download had an issue — Chat still works; retry later for images/audio/video.",
        );
      })
      .finally(() => setMmBusy(false));
  }

  async function runDownload(selectedChatId: string) {
    if (!selectedChatId || downloading) return;
    setDownloading(true);
    setSaving(true);
    setError(null);
    setDownloadMsg(
      "Downloading selected chat GGUF + auto embed/rerank (required for search)…",
    );
    try {
      // GGUFs only — Florence/Whisper/Marlin must not block Setup / Chat.
      await api.downloadModels(false, selectedChatId);
      const s = await api.getSetupStatus();
      setStatus(s);
      setSaved(true);
      setDownloadMsg(
        s.local_models_ready
          ? "Models on disk. They load into memory only when you use Chat / ingest."
          : "Download finished. Check models directory if Chat is unavailable.",
      );
      startBackgroundMultimodal();
    } catch (err: unknown) {
      try {
        const s = await api.getSetupStatus();
        if (s.local_models_ready) {
          setStatus(s);
          setSaved(true);
          setDownloadMsg(
            "Models already on disk. They load into memory only when you use Chat / ingest.",
          );
          setError(null);
          startBackgroundMultimodal();
          return;
        }
      } catch {
        /* fall through */
      }
      let detail = "unknown error";
      if (err && typeof err === "object" && "response" in err) {
        const data = (err as { response?: { data?: { detail?: string } | string } })
          .response?.data;
        detail =
          typeof data === "string"
            ? data
            : data && typeof data === "object" && data.detail
              ? String(data.detail)
              : JSON.stringify(data ?? "").slice(0, 400);
      } else if (err instanceof Error) {
        detail = err.message;
      }
      setError(`Model download failed: ${detail}`);
      setDownloadMsg(null);
    } finally {
      setDownloading(false);
      setSaving(false);
    }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.saveSetupPaths({
        data_dir: dataDir,
        models_dir: modelsDir,
        default_vault_path: vaultPath || undefined,
        ai_setup_mode: aiMode,
      });
      setSaved(true);
      const s = await api.getSetupStatus();
      setStatus(s);
    } catch {
      setError("Failed to save paths. Check that directories are writable.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="relative min-h-screen text-white">
      <ShaderBackground />
      <div className="relative z-10 mx-auto max-w-2xl px-8 py-12">
        <div className="mb-8 flex items-center gap-3">
          <Sparkles className="h-7 w-7 text-amber-300" />
          <div>
            <h1 className="text-2xl font-semibold">Setup</h1>
            <p className="text-sm text-white/50">
              Data folders and AI mode — restart the desktop app after changing paths
            </p>
          </div>
        </div>

        {error && (
          <p className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-200">
            {error}
          </p>
        )}

        {(downloading || mmBusy || downloadMsg) && (
          <div className="mb-6 rounded-2xl border border-amber-400/30 bg-amber-500/10 px-5 py-4">
            <p className="text-sm font-medium text-amber-100">
              {downloading
                ? "Downloading selected chat + embed/rerank…"
                : mmBusy
                  ? "Fetching multimedia models in the background…"
                  : "Model download"}
            </p>
            {downloadMsg && <p className="mt-1 text-xs text-amber-100/70">{downloadMsg}</p>}
            {(downloading || mmBusy) && (
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-black/40">
                <div className="h-full w-1/3 animate-pulse rounded-full bg-amber-400/70" />
              </div>
            )}
          </div>
        )}

        <form onSubmit={save} className="space-y-8">
          <section className="rounded-2xl border border-white/10 bg-black/40 p-6 space-y-4">
            <h2 className="flex items-center gap-2 text-lg font-medium">
              <FolderOpen className="h-5 w-5" /> Paths
            </h2>
            <p className="text-xs text-white/40">
              Notes vault is the folder of markdown files LifeOS reads and writes. You can
              change it anytime — click Save setup after browsing.
            </p>
            <label className="block text-sm">
              <span className="text-white/50">Notes vault folder</span>
              <div className="mt-1 flex gap-2">
                <input
                  value={vaultPath}
                  onChange={(e) => setVaultPath(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-black/50 px-3 py-2 font-mono text-sm"
                  placeholder="~/Documents/LifeOS Vault"
                  disabled={downloading}
                />
                {canBrowse && (
                  <button
                    type="button"
                    disabled={downloading}
                    onClick={() =>
                      void browseInto(setVaultPath, "Choose notes vault folder", vaultPath)
                    }
                    className="shrink-0 rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:bg-white/5 disabled:opacity-50"
                  >
                    Browse…
                  </button>
                )}
              </div>
            </label>
            <label className="block text-sm">
              <span className="text-white/50">Data directory (indexes, SQLite)</span>
              <div className="mt-1 flex gap-2">
                <input
                  value={dataDir}
                  onChange={(e) => setDataDir(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-black/50 px-3 py-2 font-mono text-sm"
                  required
                  disabled={downloading}
                />
                {canBrowse && (
                  <button
                    type="button"
                    disabled={downloading}
                    onClick={() =>
                      void browseInto(setDataDir, "Choose data directory", dataDir)
                    }
                    className="shrink-0 rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:bg-white/5 disabled:opacity-50"
                  >
                    Browse…
                  </button>
                )}
              </div>
            </label>
            <label className="block text-sm">
              <span className="text-white/50">Models directory (local ML weights)</span>
              <div className="mt-1 flex gap-2">
                <input
                  value={modelsDir}
                  onChange={(e) => setModelsDir(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-black/50 px-3 py-2 font-mono text-sm"
                  required
                  disabled={downloading}
                />
                {canBrowse && (
                  <button
                    type="button"
                    disabled={downloading}
                    onClick={() =>
                      void browseInto(setModelsDir, "Choose models directory", modelsDir)
                    }
                    className="shrink-0 rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:bg-white/5 disabled:opacity-50"
                  >
                    Browse…
                  </button>
                )}
              </div>
            </label>
          </section>

          <section className="rounded-2xl border border-white/10 bg-black/40 p-6 space-y-3">
            <h2 className="text-lg font-medium">AI setup</h2>
            <p className="text-sm text-white/50">
              You can skip AI and use LifeOS like Obsidian (notes, wikilinks, finance). Chat,
              ingest, and entity graph stay unavailable until AI is configured.
            </p>
            {(
              [
                {
                  id: "local" as const,
                  icon: Brain,
                  title: "Full local",
                  desc: "Pick a chat GGUF; Qwen3 embed + reranker size to your RAM automatically.",
                },
                {
                  id: "cloud" as const,
                  icon: Cloud,
                  title: "Cloud / hybrid",
                  desc: "OpenAI / Gemini / Anthropic in Settings; optional local multimodal",
                },
                {
                  id: "none" as const,
                  icon: SkipForward,
                  title: "Skip for now",
                  desc: "Obsidian-like limited mode — set up AI later in Settings",
                },
              ] as const
            ).map((opt) => {
              const Icon = opt.icon;
              const active = aiMode === opt.id || (opt.id === "cloud" && aiMode === "hybrid");
              return (
                <button
                  key={opt.id}
                  type="button"
                  disabled={downloading}
                  onClick={() => setAiMode(opt.id)}
                  className={`flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left transition ${
                    active
                      ? "border-amber-400/40 bg-amber-400/10"
                      : "border-white/10 bg-black/30 hover:border-white/20"
                  }`}
                >
                  <Icon className="mt-0.5 h-5 w-5 shrink-0 text-amber-200" />
                  <div>
                    <div className="font-medium">{opt.title}</div>
                    <div className="text-xs text-white/45">{opt.desc}</div>
                  </div>
                </button>
              );
            })}
          </section>

          {aiMode === "local" && catalog && (
            <section className="rounded-2xl border border-white/10 bg-black/40 p-6 space-y-4">
              <h2 className="text-lg font-medium">Local models</h2>
              <p className="text-xs text-white/45">{catalog.budget_note}</p>
              <p className="text-xs text-white/40">
                After you click Download, LifeOS fetches your selected chat model plus the
                auto-sized Qwen3 embed/reranker (required for search — not extra chat LLMs).
                Florence-2, Whisper, and Marlin download in the background for images/audio/video.
              </p>
              <div className="grid gap-2 text-xs text-white/55 sm:grid-cols-2">
                <div className="rounded-lg border border-white/10 bg-black/30 px-3 py-2">
                  <div className="text-white/35 uppercase tracking-wide">Embed (auto)</div>
                  <div className="mt-1 text-sm text-white/80">{catalog.embed?.label || "—"}</div>
                </div>
                <div className="rounded-lg border border-white/10 bg-black/30 px-3 py-2">
                  <div className="text-white/35 uppercase tracking-wide">Reranker (auto)</div>
                  <div className="mt-1 text-sm text-white/80">
                    {catalog.reranker?.label || "—"}
                  </div>
                </div>
              </div>
              <div className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-white/55">
                <div className="text-white/35 uppercase tracking-wide">Multimedia (auto)</div>
                <div className="mt-1 text-sm text-white/80">
                  Florence-2 · Whisper large-v3-turbo · Marlin-2B
                </div>
              </div>

              <div className="space-y-2">
                <div className="text-sm text-white/60">Chat model</div>
                {catalog.chat_options.length === 0 && (
                  <p className="text-sm text-amber-200/80">
                    No chat models fit the detected RAM budget. Free memory or set{" "}
                    <code className="font-mono">LIVEOS_RAM_GB</code>.
                  </p>
                )}
                {catalog.chat_options.map((opt) => {
                  const active = chatId === opt.id;
                  const suggested = catalog.suggested_chat?.id === opt.id;
                  const tight = opt.fits_budget === false;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      disabled={downloading}
                      onClick={() => {
                        setChatId(opt.id);
                        void api.selectChatModel(opt.id).catch(() => undefined);
                      }}
                      className={`flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left transition ${
                        active
                          ? "border-amber-400/40 bg-amber-400/10"
                          : "border-white/10 bg-black/30 hover:border-white/20"
                      }`}
                    >
                      <div>
                        <div className="font-medium text-sm">
                          {opt.label}
                          {suggested ? (
                            <span className="ml-2 text-[10px] uppercase tracking-wide text-amber-300/80">
                              suggested
                            </span>
                          ) : null}
                          {tight ? (
                            <span className="ml-2 text-[10px] uppercase tracking-wide text-white/35">
                              may be tight
                            </span>
                          ) : null}
                        </div>
                        <div className="text-xs text-white/40">
                          {opt.family} · ~{opt.size_gb} GB download · needs ~{opt.min_ram_gb} GB
                        </div>
                      </div>
                      {active ? <Check className="h-4 w-4 text-amber-200" /> : null}
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          <button
            type="submit"
            disabled={saving || downloading}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-500/20 px-5 py-2.5 text-sm text-amber-100 hover:bg-amber-500/30 disabled:opacity-50"
          >
            {saved ? <Check className="h-4 w-4" /> : null}
            {saving && !downloading ? "Saving…" : saved ? "Saved" : "Save setup"}
          </button>

          {aiMode === "local" && (
            <div className="flex flex-col gap-2">
              <button
                type="button"
                disabled={saving || downloading || !chatId}
                onClick={() => void runDownload(chatId)}
                className="rounded-lg border border-amber-400/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-100 disabled:opacity-50"
              >
                {downloading
                  ? "Downloading…"
                  : mmBusy
                    ? "Multimedia still downloading…"
                  : status?.local_models_ready
                    ? "Re-download / verify models on disk"
                    : "Download selected models"}
              </button>
            </div>
          )}

          {status && (
            <p className="text-xs text-white/35">
              Backend: {status.database_backend} · AI mode: {status.ai_setup_mode || "none"} ·
              models: {status.local_models_ready ? "ready" : "missing"} · configured:{" "}
              {status.ai_configured ? "yes" : "no"}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}
