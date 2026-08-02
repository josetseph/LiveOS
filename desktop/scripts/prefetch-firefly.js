#!/usr/bin/env node
const fs = require("fs");
const path = require("path");
const os = require("os");
const {
  FIREFLY_VERSION,
  ensureFireflyApp,
  ensurePhpRuntime,
  fireflyAppDir,
  fireflyDataRoot,
} = require("../firefly-runtime");

async function main() {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "orb-firefly-seed-"));
  const seedRoot = path.join(__dirname, "..", "resources", "firefly");
  try {
    console.log(`Preparing Firefly seed from ${FIREFLY_VERSION}…`);
    await ensurePhpRuntime(tempRoot, (msg) => console.log(msg));
    await ensureFireflyApp(tempRoot, (msg) => console.log(msg));
    fs.rmSync(seedRoot, { recursive: true, force: true });
    fs.mkdirSync(seedRoot, { recursive: true });
    fs.cpSync(path.join(fireflyDataRoot(tempRoot), "php"), path.join(seedRoot, "php"), {
      recursive: true,
    });
    fs.cpSync(fireflyAppDir(tempRoot), path.join(seedRoot, "app"), { recursive: true });
    console.log(`Firefly seed written to ${seedRoot}`);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err.stack || err.message || String(err));
  process.exit(1);
});
