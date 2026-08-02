const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const {
  Supervisor,
  needsWizard,
  defaultPathsFile,
} = require("./supervisor");
const {
  getAppRoot,
  getRepoRoot,
  isPackaged,
  defaultDataDir,
  defaultModelsDir,
} = require("./paths");
const { uiUrl, apiV1Url } = require("./ports");

// Keep macOS menu / "Quit …" label as LifeOS (not package.json "liveos-desktop").
app.setName("LifeOS");
if (process.platform === "win32") {
  app.setAppUserModelId("com.liveos.app");
}

const APP_URL = process.env.LIVEOS_URL || uiUrl();
let mainWindow = null;
let splashWindow = null;
let supervisor = null;

function sendStatus(message) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send("status", message);
  }
}

function appIconPath() {
  const candidates = [
    path.join(__dirname, "build", "icon.png"),
    path.join(__dirname, "assets", "logo.png"),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return undefined;
}

function createSplash() {
  const icon = appIconPath();
  splashWindow = new BrowserWindow({
    width: 480,
    height: 360,
    resizable: false,
    title: "LifeOS",
    backgroundColor: "#0a0a0f",
    show: false,
    ...(icon ? { icon } : {}),
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });
  splashWindow.loadFile(path.join(__dirname, "splash.html"));
  splashWindow.once("ready-to-show", () => splashWindow.show());
  return splashWindow;
}

function createWizard() {
  const icon = appIconPath();
  const win = new BrowserWindow({
    width: 680,
    height: 820,
    minWidth: 560,
    minHeight: 640,
    title: "LifeOS Setup",
    backgroundColor: "#0a0a0f",
    ...(icon ? { icon } : {}),
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });
  win.loadFile(path.join(__dirname, "wizard.html"));
  return win;
}

function createMainWindow(initialPath = "/") {
  const icon = appIconPath();
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    title: "LifeOS",
    backgroundColor: "#0a0a0f",
    ...(icon ? { icon } : {}),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  const url = initialPath && initialPath !== "/"
    ? `${APP_URL.replace(/\/$/, "")}${initialPath.startsWith("/") ? initialPath : `/${initialPath}`}`
    : APP_URL;
  mainWindow.loadURL(url);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function dirHasGguf(dir, depth = 0) {
  if (!dir || depth > 4 || !fs.existsSync(dir)) return false;
  try {
    for (const name of fs.readdirSync(dir)) {
      const p = path.join(dir, name);
      let st;
      try {
        st = fs.statSync(p);
      } catch {
        continue;
      }
      if (st.isFile() && name.toLowerCase().endsWith(".gguf")) return true;
      if (st.isDirectory() && dirHasGguf(p, depth + 1)) return true;
    }
  } catch {
    return false;
  }
  return false;
}

function resolveBootPath() {
  // Full local without GGUFs yet → open Setup so download can auto-start.
  try {
    const pathsFile = process.env.LIVEOS_PATHS_FILE || defaultPathsFile();
    if (!fs.existsSync(pathsFile)) return "/";
    const j = JSON.parse(fs.readFileSync(pathsFile, "utf8"));
    const mode = String(j.ai_setup_mode || process.env.AI_SETUP_MODE || "none").toLowerCase();
    if (mode !== "local") return "/";
    const modelsDir = j.models_dir || process.env.MODELS_DIR;
    if (!dirHasGguf(modelsDir)) return "/setup";
  } catch (_) {
    /* ignore */
  }
  return "/";
}

function setupAutoUpdater() {
  // Opt-in only — unsigned builds must not hit GitHub Releases until Stage 6
  if (!isPackaged()) return;
  if (process.env.LIVEOS_ENABLE_UPDATER !== "1") return;
  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.autoDownload = false;
    autoUpdater.checkForUpdatesAndNotify().catch(() => {});
  } catch (_) {
    // electron-updater optional
  }
}

ipcMain.handle("pick-directory", async (event, opts = {}) => {
  // Parent window is required on macOS — otherwise the sheet can open behind
  // the wizard/main window and look like Browse "does nothing".
  const win =
    BrowserWindow.fromWebContents(event.sender) ||
    BrowserWindow.getFocusedWindow() ||
    undefined;
  const result = await dialog.showOpenDialog(win, {
    title: opts.title || "Choose folder",
    buttonLabel: opts.buttonLabel || "Select",
    properties: ["openDirectory", "createDirectory"],
    defaultPath: opts.defaultPath || undefined,
  });
  if (result.canceled || !result.filePaths[0]) return null;
  return result.filePaths[0];
});

ipcMain.handle("get-api-base-url", () => apiV1Url());

ipcMain.handle("reveal-in-folder", (_e, filePath) => {
  if (!filePath || typeof filePath !== "string") {
    return { ok: false, error: "Missing path" };
  }
  try {
    shell.showItemInFolder(filePath);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("get-default-paths", () => ({
  data_dir: defaultDataDir(),
  models_dir: defaultModelsDir(),
}));

ipcMain.handle("get-app-info", () => {
  const pkg = require("./package.json");
  return {
    version: pkg.version,
    packaged: isPackaged(),
    repoRoot: getRepoRoot(),
    appRoot: getAppRoot(),
  };
});

ipcMain.handle("save-wizard", async (_e, payload) => {
  const loc = defaultPathsFile();
  fs.mkdirSync(path.dirname(loc), { recursive: true });
  const data = {
    data_dir: payload.data_dir,
    models_dir: payload.models_dir,
  };
  if (payload.default_vault_path) data.default_vault_path = payload.default_vault_path;
  if (payload.ai_setup_mode) data.ai_setup_mode = payload.ai_setup_mode;
  fs.writeFileSync(loc, JSON.stringify(data, null, 2), "utf8");
  if (payload.ai_setup_mode) {
    process.env.AI_SETUP_MODE = payload.ai_setup_mode;
  }
  try {
    const dataDir = payload.data_dir;
    fs.mkdirSync(dataDir, { recursive: true });
    const rcPath = path.join(dataDir, "runtime_config.json");
    let rc = {};
    if (fs.existsSync(rcPath)) {
      try {
        rc = JSON.parse(fs.readFileSync(rcPath, "utf8"));
      } catch (_) {
        rc = {};
      }
    }
    if (payload.ai_setup_mode) rc.ai_setup_mode = payload.ai_setup_mode;
    fs.writeFileSync(rcPath, JSON.stringify(rc, null, 2), "utf8");
  } catch (err) {
    console.warn("Could not write runtime_config.json", err);
  }
  return { ok: true, pathsFile: loc };
});

async function bootStack(appRoot) {
  supervisor = new Supervisor(appRoot, sendStatus);
  if (process.env.LIVEOS_USE_DOCKER === "1") {
    sendStatus("Starting Docker services…");
    const { spawn } = require("child_process");
    const repoRoot = getRepoRoot();
    await new Promise((resolve, reject) => {
      const child = spawn("docker", ["compose", "up", "-d"], {
        cwd: repoRoot,
        shell: process.platform === "win32",
      });
      child.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`compose ${code}`))));
      child.on("error", reject);
    });
  } else {
    await supervisor.startAll();
  }
}

app.whenReady().then(async () => {
  const appRoot = getAppRoot();
  const pathsFile = process.env.LIVEOS_PATHS_FILE || defaultPathsFile();

  if (needsWizard(pathsFile) && !process.env.LIVEOS_SKIP_WIZARD) {
    const wizard = createWizard();
    await new Promise((resolve) => {
      ipcMain.once("wizard-done", () => {
        if (!wizard.isDestroyed()) wizard.close();
        resolve();
      });
    });
  }

  createSplash();
  try {
    await bootStack(appRoot);
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    createMainWindow(resolveBootPath());
    setupAutoUpdater();
  } catch (err) {
    const message = String(err.message || err);
    sendStatus(message);
    console.error(err);
    await dialog.showMessageBox({
      type: "error",
      title: "LifeOS failed to start",
      message: "Could not start local services.",
      detail: `${message}\n\nLogs: ~/Library/Application Support/LifeOS/data/logs/`,
      buttons: ["Quit"],
      defaultId: 0,
    });
    if (supervisor) supervisor.stopAll();
    app.quit();
  }
});

app.on("window-all-closed", () => {
  if (supervisor) supervisor.stopAll();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (supervisor) supervisor.stopAll();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createMainWindow(resolveBootPath());
});
