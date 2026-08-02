#!/usr/bin/env node
/**
 * Download portable Node.js into desktop/resources/node (matches host OS/arch).
 */
const fs = require("fs");
const path = require("path");
const https = require("https");
const { execFileSync } = require("child_process");

const NODE_VERSION = process.env.ORB_NODE_VERSION || "24.4.1";
const outRoot = path.join(__dirname, "..", "resources", "node");
const tmpDir = path.join(__dirname, "..", "resources", ".tmp");

function nodeAsset() {
  const v = NODE_VERSION;
  if (process.platform === "darwin") {
    const arch = process.arch === "arm64" ? "arm64" : "x64";
    return {
      url: `https://nodejs.org/dist/v${v}/node-v${v}-darwin-${arch}.tar.gz`,
      archive: `node-v${v}-darwin-${arch}.tar.gz`,
      innerDir: `node-v${v}-darwin-${arch}`,
    };
  }
  if (process.platform === "win32") {
    const arch = process.arch === "arm64" ? "arm64" : "x64";
    return {
      url: `https://nodejs.org/dist/v${v}/node-v${v}-win-${arch}.zip`,
      archive: `node-v${v}-win-${arch}.zip`,
      innerDir: `node-v${v}-win-${arch}`,
    };
  }
  const arch = process.arch === "arm64" ? "arm64" : "x64";
  return {
    url: `https://nodejs.org/dist/v${v}/node-v${v}-linux-${arch}.tar.xz`,
    archive: `node-v${v}-linux-${arch}.tar.xz`,
    innerDir: `node-v${v}-linux-${arch}`,
  };
}

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    https
      .get(url, { timeout: 180000 }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          file.close();
          fs.unlinkSync(dest);
          download(res.headers.location, dest).then(resolve).catch(reject);
          return;
        }
        if (res.statusCode !== 200) {
          reject(new Error(`Download failed ${res.statusCode}: ${url}`));
          return;
        }
        res.pipe(file);
        file.on("finish", () => file.close(() => resolve(dest)));
      })
      .on("error", reject);
  });
}

async function main() {
  const asset = nodeAsset();
  fs.mkdirSync(tmpDir, { recursive: true });
  const archivePath = path.join(tmpDir, asset.archive);
  console.log(`Downloading Node ${NODE_VERSION}…`);
  await download(asset.url, archivePath);

  fs.rmSync(outRoot, { recursive: true, force: true });
  fs.mkdirSync(outRoot, { recursive: true });
  const extractTo = path.join(tmpDir, "node-extract");
  fs.rmSync(extractTo, { recursive: true, force: true });
  fs.mkdirSync(extractTo, { recursive: true });

  if (asset.archive.endsWith(".zip")) {
    execFileSync(
      "powershell",
      [
        "-Command",
        `Expand-Archive -Path '${archivePath}' -DestinationPath '${extractTo}' -Force`,
      ],
      { stdio: "inherit" },
    );
  } else if (asset.archive.endsWith(".tar.xz")) {
    execFileSync("tar", ["-xf", archivePath, "-C", extractTo], { stdio: "inherit" });
  } else {
    execFileSync("tar", ["-xzf", archivePath, "-C", extractTo], { stdio: "inherit" });
  }

  const inner = path.join(extractTo, asset.innerDir);
  fs.cpSync(inner, outRoot, { recursive: true });

  // Drop headers/docs — not needed at runtime
  for (const drop of ["include", "share", "CHANGELOG.md", "README.md", "LICENSE"]) {
    fs.rmSync(path.join(outRoot, drop), { recursive: true, force: true });
  }

  fs.rmSync(archivePath, { force: true });
  fs.rmSync(extractTo, { recursive: true, force: true });
  console.log("Node ready at", outRoot);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
