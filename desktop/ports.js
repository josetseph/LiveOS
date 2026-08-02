/**
 * LiveOS desktop local ports — kept off the usual 8000 / 6333 / 7700 / 3000
 * ranges so developers can run other stacks alongside LiveOS.
 *
 * Override any value with LIVEOS_*_PORT env vars if needed.
 */
const PORTS = {
  ui: Number(process.env.LIVEOS_UI_PORT || 17400),
  api: Number(process.env.LIVEOS_API_PORT || 17401),
  firefly: Number(process.env.LIVEOS_FIREFLY_PORT || 17412),
  qdrant: Number(process.env.LIVEOS_QDRANT_PORT || 17433),
  meilisearch: Number(process.env.LIVEOS_MEILI_PORT || 17470),
  // Legacy multimodal sidecar ports — freed on boot to kill old processes only.
  // Models now load in-process; do not start listeners here.
  marlin: Number(process.env.LIVEOS_MARLIN_PORT || 17490),
  localModels: Number(process.env.LIVEOS_LOCAL_MODELS_PORT || 17491),
};

function localhost(port) {
  return `http://127.0.0.1:${port}`;
}

module.exports = {
  PORTS,
  localhost,
  uiUrl: () => localhost(PORTS.ui),
  apiUrl: () => localhost(PORTS.api),
  apiV1Url: () => `${localhost(PORTS.api)}/api/v1`,
  fireflyUrl: () => localhost(PORTS.firefly),
  qdrantUrl: () => `${localhost(PORTS.qdrant)}/`,
  meiliHealthUrl: () => `${localhost(PORTS.meilisearch)}/health`,
  marlinUrl: () => localhost(PORTS.marlin),
  localModelsUrl: () => localhost(PORTS.localModels),
  corsOrigins: () =>
    [
      localhost(PORTS.ui),
      `http://localhost:${PORTS.ui}`,
    ].join(","),
};
