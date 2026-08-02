#!/usr/bin/env node
/**
 * Prefetch Qdrant + Meilisearch into ./data/bin (or ORB_DATA_DIR).
 * Used by packaging / CI; the Electron supervisor also downloads on first run.
 * Local LLM GGUFs are fetched by the Python setup API (llama-cpp-python in-process).
 */
const path = require("path");
const { ensureBinaries, QDRANT_VERSION, MEILI_VERSION } = require("../download-binaries");

async function main() {
  const dataDir =
    process.env.ORB_DATA_DIR ||
    path.resolve(__dirname, "..", "data");
  console.log(`Prefetching binaries into ${dataDir}/bin`);
  console.log(`Qdrant ${QDRANT_VERSION}, Meilisearch ${MEILI_VERSION}`);
  const result = await ensureBinaries(dataDir, (msg) => console.log(msg));
  console.log("Done:", result);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
