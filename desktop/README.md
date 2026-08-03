# Orb Desktop

Electron shell that supervises a **Docker-free** local stack:

1. Wizard → `paths.json` (data dir, models dir, optional vault + AI mode)
2. Auto-downloads **Qdrant** + **Meilisearch** into `DATA_DIR/bin`
3. Bundled **Python API** + **Next.js UI** (when built with `prepare-dist`)
4. Local LLM: in-process `llama-cpp-python` + GGUF download via Setup

Desktop ports (avoid clash with typical `8000` / `3000` stacks): UI `17400`, API `17401`, Qdrant `17433`, Meilisearch `17470`. See [PACKAGING.md](./PACKAGING.md).

Product overview and installers: [root README](../README.md).

## Development

```bash
cd desktop && npm install && npm start
```

Uses repo `backend/.venv` (or system Python) and `frontend` via `next dev`.

Optional: `ORB_FRONTEND_DEV=1` forces dev server even when a standalone build exists.

## Installers (.dmg / .exe)

See [PACKAGING.md](./PACKAGING.md).

```bash
cd desktop
npm install
npm run prepare-dist   # bundle Python + Node + frontend (~10–20 min)
npm run dist:mac       # or dist:win on Windows
```

Test packaged layout without building an installer:

```bash
npm run prepare-dist
ORB_RESOURCES=./resources npm start
```
