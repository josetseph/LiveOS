/**
 * Packaged vs dev path contract for LiveOS desktop.
 * Packaged layout (under process.resourcesPath):
 *   backend/{python,app,...}  frontend/{server.js,...}  node/{bin/node,...}
 */
const path = require("path");
const fs = require("fs");
const os = require("os");

function isPackaged() {
  try {
    const { app } = require("electron");
    return app.isPackaged;
  } catch (_) {
    return process.env.LIVEOS_PACKAGED === "1";
  }
}

function getResourcesRoot() {
  if (isPackaged()) {
    return process.resourcesPath;
  }
  if (process.env.LIVEOS_RESOURCES) {
    return path.resolve(process.env.LIVEOS_RESOURCES);
  }
  const devResources = path.join(__dirname, "resources");
  if (fs.existsSync(path.join(devResources, "backend", "python"))) {
    return devResources;
  }
  return null;
}

function getRepoRoot() {
  if (process.env.LIVEOS_ROOT) return path.resolve(process.env.LIVEOS_ROOT);
  const candidates = [
    path.resolve(__dirname, ".."),
    path.resolve(process.cwd(), ".."),
    process.cwd(),
  ];
  for (const c of candidates) {
    if (
      fs.existsSync(path.join(c, "frontend")) &&
      fs.existsSync(path.join(c, "backend"))
    ) {
      return c;
    }
  }
  return path.resolve(__dirname, "..");
}

function hasPackagedRuntime(resourcesRoot) {
  if (!resourcesRoot) return false;
  const pyCandidates = [
    path.join(resourcesRoot, "backend", "python", "bin", "python3"),
    path.join(resourcesRoot, "backend", "python", "bin", "python"),
    path.join(resourcesRoot, "backend", "python", "python.exe"),
  ];
  return pyCandidates.some((p) => fs.existsSync(p));
}

function isPackagedLayout() {
  return hasPackagedRuntime(getResourcesRoot());
}

function getAppRoot() {
  const resources = getResourcesRoot();
  if (resources && hasPackagedRuntime(resources)) {
    return resources;
  }
  return getRepoRoot();
}

function getBackendDir() {
  const resources = getResourcesRoot();
  if (resources && fs.existsSync(path.join(resources, "backend", "app"))) {
    return path.join(resources, "backend");
  }
  return path.join(getRepoRoot(), "backend");
}

function getFrontendDir() {
  const resources = getResourcesRoot();
  if (resources && fs.existsSync(path.join(resources, "frontend", "server.js"))) {
    return path.join(resources, "frontend");
  }
  return path.join(getRepoRoot(), "frontend");
}

function firstExisting(candidates) {
  for (const c of candidates) {
    if (c && fs.existsSync(c)) return c;
  }
  return null;
}

function getPythonBinary() {
  if (process.env.LIVEOS_PYTHON) return process.env.LIVEOS_PYTHON;

  const backendDir = getBackendDir();
  const pyRoot = path.join(backendDir, "python");
  const win = process.platform === "win32";

  const bundled = firstExisting([
    win ? path.join(pyRoot, "python.exe") : null,
    path.join(pyRoot, "bin", "python3"),
    path.join(pyRoot, "bin", "python"),
    path.join(pyRoot, "Scripts", "python.exe"),
  ]);
  if (bundled) return bundled;

  const venvPython = win
    ? path.join(getRepoRoot(), "backend", ".venv", "Scripts", "python.exe")
    : path.join(getRepoRoot(), "backend", ".venv", "bin", "python");
  if (fs.existsSync(venvPython)) return venvPython;

  return win ? "python" : "python3";
}

function getNodeBinary() {
  if (process.env.LIVEOS_NODE) return process.env.LIVEOS_NODE;

  const resources = getResourcesRoot();
  const win = process.platform === "win32";
  if (resources) {
    const bundled = firstExisting([
      win ? path.join(resources, "node", "node.exe") : null,
      path.join(resources, "node", "bin", "node"),
    ]);
    if (bundled) return bundled;
  }

  return process.platform === "win32" ? "node.exe" : "node";
}

function appSupportRoot() {
  let primary;
  let legacy;
  if (process.platform === "darwin") {
    primary = path.join(os.homedir(), "Library", "Application Support", "LifeOS");
    legacy = path.join(os.homedir(), "Library", "Application Support", "LiveOS");
  } else if (process.platform === "win32") {
    const base =
      process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
    primary = path.join(base, "LifeOS");
    legacy = path.join(base, "LiveOS");
  } else {
    primary = path.join(os.homedir(), ".config", "LifeOS");
    legacy = path.join(os.homedir(), ".config", "LiveOS");
  }
  if (fs.existsSync(path.join(primary, "paths.json"))) return primary;
  if (fs.existsSync(path.join(legacy, "paths.json"))) return legacy;
  return primary;
}

function defaultDataDir() {
  return path.join(appSupportRoot(), "data");
}

function defaultModelsDir() {
  return path.join(appSupportRoot(), "models");
}

function useProductionFrontend() {
  if (process.env.LIVEOS_FRONTEND_DEV === "1") return false;
  if (isPackagedLayout()) return true;
  return fs.existsSync(path.join(getFrontendDir(), "server.js"));
}

module.exports = {
  isPackaged,
  isPackagedLayout,
  getResourcesRoot,
  getRepoRoot,
  getAppRoot,
  getBackendDir,
  getFrontendDir,
  getPythonBinary,
  getNodeBinary,
  appSupportRoot,
  defaultDataDir,
  defaultModelsDir,
  useProductionFrontend,
};
