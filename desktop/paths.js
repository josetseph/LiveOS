/**
 * Packaged vs dev path contract for Orb desktop.
 * Packaged layout (under process.resourcesPath):
 *   backend/{python,app,...}  frontend/{server.js,...}  node/{bin/node,...}
 */
const path = require("path");
const fs = require("fs");
const os = require("os");

function envFirst(...names) {
  for (const name of names) {
    const value = process.env[name];
    if (value) return value;
  }
  return undefined;
}

function isPackaged() {
  try {
    const { app } = require("electron");
    return app.isPackaged;
  } catch (_) {
    return envFirst("ORB_PACKAGED", "LIVEOS_PACKAGED") === "1";
  }
}

function getResourcesRoot() {
  if (isPackaged()) {
    return process.resourcesPath;
  }
  const override = envFirst("ORB_RESOURCES", "LIVEOS_RESOURCES");
  if (override) {
    return path.resolve(override);
  }
  const devResources = path.join(__dirname, "resources");
  if (fs.existsSync(path.join(devResources, "backend", "python"))) {
    return devResources;
  }
  return null;
}

function getRepoRoot() {
  const override = envFirst("ORB_ROOT", "LIVEOS_ROOT");
  if (override) return path.resolve(override);
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
  const override = envFirst("ORB_PYTHON", "LIVEOS_PYTHON");
  if (override) return override;

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
  const override = envFirst("ORB_NODE", "LIVEOS_NODE");
  if (override) return override;

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
  let candidates;
  if (process.platform === "darwin") {
    const base = path.join(os.homedir(), "Library", "Application Support");
    candidates = [
      path.join(base, "Orb"),
      path.join(base, "LifeOS"),
      path.join(base, "LiveOS"),
    ];
  } else if (process.platform === "win32") {
    const base =
      process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
    candidates = [
      path.join(base, "Orb"),
      path.join(base, "LifeOS"),
      path.join(base, "LiveOS"),
    ];
  } else {
    const base = path.join(os.homedir(), ".config");
    candidates = [
      path.join(base, "Orb"),
      path.join(base, "LifeOS"),
      path.join(base, "LiveOS"),
    ];
  }
  for (const candidate of candidates) {
    if (fs.existsSync(path.join(candidate, "paths.json"))) return candidate;
  }
  return candidates[0];
}

function defaultDataDir() {
  return path.join(appSupportRoot(), "data");
}

function defaultModelsDir() {
  return path.join(appSupportRoot(), "models");
}

function useProductionFrontend() {
  if (envFirst("ORB_FRONTEND_DEV", "LIVEOS_FRONTEND_DEV") === "1") return false;
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
