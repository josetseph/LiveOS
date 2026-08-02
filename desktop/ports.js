/**
 * Desktop ports — dedicated high range to avoid clashing with common 8000/3000 stacks.
 * Override any value with ORB_*_PORT env vars (LIVEOS_*_PORT still accepted).
 */
function envPort(orbName, liveosName, fallback) {
  const raw = process.env[orbName] || process.env[liveosName];
  return Number(raw || fallback);
}

const PORTS = {
  ui: envPort("ORB_UI_PORT", "LIVEOS_UI_PORT", 17400),
  api: envPort("ORB_API_PORT", "LIVEOS_API_PORT", 17401),
  firefly: envPort("ORB_FIREFLY_PORT", "LIVEOS_FIREFLY_PORT", 17412),
  qdrant: envPort("ORB_QDRANT_PORT", "LIVEOS_QDRANT_PORT", 17433),
  meilisearch: envPort("ORB_MEILI_PORT", "LIVEOS_MEILI_PORT", 17470),
  // Reserved — multimodal runs in-process in the API (no HTTP sidecars).
  marlin: envPort("ORB_MARLIN_PORT", "LIVEOS_MARLIN_PORT", 17490),
  localModels: envPort("ORB_LOCAL_MODELS_PORT", "LIVEOS_LOCAL_MODELS_PORT", 17491),
};

function localhost(port) {
  return `http://127.0.0.1:${port}`;
}

module.exports = {
  PORTS,
  localhost,
  // Flat aliases (legacy callers)
  ui: PORTS.ui,
  api: PORTS.api,
  firefly: PORTS.firefly,
  qdrant: PORTS.qdrant,
  meilisearch: PORTS.meilisearch,
  marlin: PORTS.marlin,
  localModels: PORTS.localModels,
  uiUrl: () => localhost(PORTS.ui),
  apiUrl: () => localhost(PORTS.api),
  apiV1Url: () => `${localhost(PORTS.api)}/api/v1`,
  fireflyUrl: () => localhost(PORTS.firefly),
  qdrantUrl: () => `${localhost(PORTS.qdrant)}/`,
  meiliHealthUrl: () => `${localhost(PORTS.meilisearch)}/health`,
  marlinUrl: () => localhost(PORTS.marlin),
  localModelsUrl: () => localhost(PORTS.localModels),
  corsOrigins: () =>
    [localhost(PORTS.ui), `http://localhost:${PORTS.ui}`].join(","),
};
