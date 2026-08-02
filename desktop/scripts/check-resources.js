#!/usr/bin/env node
/** Fail fast if prepare-dist was not run before electron-builder. */
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..", "resources");
const nodePath =
  process.platform === "win32"
    ? path.join(root, "node", "node.exe")
    : path.join(root, "node", "bin", "node");
const pythonPath =
  process.platform === "win32"
    ? path.join(root, "backend", "python", "python.exe")
    : path.join(root, "backend", "python", "bin", "python3");
const pythonAlt = path.join(root, "backend", "python", "bin", "python");

const required = [
  path.join(root, "backend", "app"),
  path.join(root, "frontend", "server.js"),
  path.join(root, "frontend", "run-server.js"),
  path.join(root, "frontend", "node_deps", "next"),
  path.join(root, "firefly", "app"),
  nodePath,
];

const missing = required.filter((p) => !fs.existsSync(p));
if (!fs.existsSync(pythonPath) && !fs.existsSync(pythonAlt)) {
  missing.push(pythonPath);
}

if (missing.length) {
  console.error("Missing packaged resources. Run: npm run prepare-dist");
  for (const m of missing) console.error(" -", m);
  process.exit(1);
}

console.log("Packaged resources OK");
