#!/usr/bin/env node
/**
 * Prepare desktop/resources for electron-builder (Python + Node + frontend).
 */
const path = require("path");
const { execFileSync } = require("child_process");

const scriptsDir = __dirname;

function run(name, script) {
  console.log(`\n=== ${name} ===\n`);
  execFileSync(process.execPath, [path.join(scriptsDir, script)], {
    stdio: "inherit",
    cwd: path.join(scriptsDir, ".."),
  });
}

function main() {
  run("Bundle Python backend", "bundle-python.js");
  run("Build frontend standalone", "build-frontend.js");
  run("Bundle Node runtime", "bundle-node.js");
  run("Prefetch Firefly seed", "prefetch-firefly.js");
  console.log("\n=== prepare-dist complete ===\n");
  console.log("Run: npm run dist (or dist:mac / dist:win)");
}

main();
