const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const crypto = require("crypto");
const { execFileSync, spawnSync } = require("child_process");
const { nativeArch } = require("./download-binaries");
const { fireflyUrl } = require("./ports");
const { getRepoRoot, getResourcesRoot } = require("./paths");

const FIREFLY_VERSION = process.env.ORB_FIREFLY_VERSION || "v6.6.6";
const PHP_BIN_VERSION = process.env.ORB_PHP_BIN_VERSION || "1.2.0";
const PHP_RUNTIME_ID = `nativephp:${PHP_BIN_VERSION}:php-8.5`;

function fireflyDataRoot(dataDir) {
  return path.join(dataDir, "firefly");
}

function fireflyAppDir(dataDir) {
  return path.join(fireflyDataRoot(dataDir), "app");
}

function fireflyRuntimeFile(dataDir) {
  return path.join(fireflyDataRoot(dataDir), "runtime.json");
}

function phpBinaryPath(dataDir) {
  const root = path.join(fireflyDataRoot(dataDir), "php");
  const direct = process.platform === "win32"
    ? path.join(root, "bin", "php.exe")
    : path.join(root, "bin", "php");
  if (fs.existsSync(direct)) return direct;
  return findFirstFile(root, process.platform === "win32" ? "php.exe" : "php") || direct;
}

function phpRuntimeMarker(rootDir) {
  return path.join(rootDir, ".orb-php-runtime");
}

function bundledFireflyRoot() {
  const resources = getResourcesRoot();
  if (resources && fs.existsSync(path.join(resources, "firefly"))) {
    return path.join(resources, "firefly");
  }
  const devSeed = path.join(getRepoRoot(), "desktop", "resources", "firefly");
  if (fs.existsSync(devSeed)) return devSeed;
  return null;
}

function phpArchiveSpec() {
  const arch = nativeArch();
  if (process.platform === "darwin") {
    return {
      asset: "php-8.5.zip",
      archiveType: "zip",
      url:
        arch === "arm64"
          ? `https://raw.githubusercontent.com/NativePHP/php-bin/refs/tags/${PHP_BIN_VERSION}/bin/mac/arm64/php-8.5.zip`
          : `https://raw.githubusercontent.com/NativePHP/php-bin/refs/tags/${PHP_BIN_VERSION}/bin/mac/x64/php-8.5.zip`,
    };
  }
  if (process.platform === "linux") {
    return {
      asset: "php-8.5.zip",
      archiveType: "zip",
      url: `https://raw.githubusercontent.com/NativePHP/php-bin/refs/tags/${PHP_BIN_VERSION}/bin/linux/x64/php-8.5.zip`,
    };
  }
  if (process.platform === "win32") {
    return {
      asset: "php-8.5.zip",
      archiveType: "zip",
      url: `https://raw.githubusercontent.com/NativePHP/php-bin/refs/tags/${PHP_BIN_VERSION}/bin/win/x64/php-8.5.zip`,
    };
  }
  throw new Error(`Unsupported platform for Firefly PHP runtime: ${process.platform}`);
}

function downloadFile(url, dest, onProgress, redirectsLeft = 5) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    const getter = url.startsWith("https") ? https.get : http.get;
    const req = getter(url, { timeout: 180000 }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        file.close(() => fs.rmSync(dest, { force: true }));
        const next = new URL(res.headers.location, url).toString();
        if (redirectsLeft <= 0) {
          reject(new Error(`Too many redirects downloading ${url}`));
          return;
        }
        if (!next.startsWith("https:")) {
          // Never follow an https→http downgrade for executable payloads.
          reject(new Error(`Refusing non-https redirect: ${next}`));
          return;
        }
        downloadFile(next, dest, onProgress, redirectsLeft - 1).then(resolve).catch(reject);
        return;
      }
      if (res.statusCode !== 200) {
        file.close();
        try {
          fs.unlinkSync(dest);
        } catch (_) {
          /* ignore */
        }
        reject(new Error(`Download failed ${res.statusCode}: ${url}`));
        return;
      }
      const total = Number(res.headers["content-length"] || 0);
      let received = 0;
      res.on("data", (chunk) => {
        received += chunk.length;
        if (onProgress && total > 0) onProgress(Math.round((received / total) * 100));
      });
      res.pipe(file);
      file.on("finish", () => file.close(() => resolve(dest)));
    });
    req.on("error", (err) => {
      try {
        file.close();
        fs.unlinkSync(dest);
      } catch (_) {
        /* ignore */
      }
      reject(err);
    });
    req.on("timeout", () => {
      req.destroy(new Error(`Timeout downloading ${url}`));
    });
  });
}

function psSingleQuoted(value) {
  // PowerShell single-quoted string: escape ' by doubling.
  return String(value).replace(/'/g, "''");
}

function extractZipWindows(archivePath, destDir) {
  // Prefer Expand-Archive — available on all supported Windows builds and does
  // not require a system Python on PATH (prefetch-firefly used to fail here).
  try {
    execFileSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        `Expand-Archive -LiteralPath '${psSingleQuoted(archivePath)}' -DestinationPath '${psSingleQuoted(destDir)}' -Force`,
      ],
      { stdio: ["ignore", "pipe", "pipe"], encoding: "utf8" },
    );
    return;
  } catch (psErr) {
    const psDetail = [psErr.stderr, psErr.stdout, psErr.message]
      .filter(Boolean)
      .join("\n")
      .trim();
    // Windows 10+ tar (bsdtar) can extract zip as a fallback.
    try {
      execFileSync("tar", ["-xf", archivePath, "-C", destDir], {
        stdio: ["ignore", "pipe", "pipe"],
        encoding: "utf8",
      });
      return;
    } catch (tarErr) {
      const tarDetail = [tarErr.stderr, tarErr.stdout, tarErr.message]
        .filter(Boolean)
        .join("\n")
        .trim();
      throw new Error(
        `Failed to extract zip on Windows (${archivePath}).\n` +
          `PowerShell: ${psDetail || "unknown error"}\n` +
          `tar: ${tarDetail || "unknown error"}`,
      );
    }
  }
}

function extractZipUnix(archivePath, destDir) {
  try {
    execFileSync("unzip", ["-o", "-q", archivePath, "-d", destDir], {
      stdio: ["ignore", "pipe", "pipe"],
      encoding: "utf8",
    });
    return;
  } catch (_) {
    /* fall through to python3 */
  }
  try {
    execFileSync(
      "python3",
      [
        "-c",
        "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])",
        archivePath,
        destDir,
      ],
      { stdio: ["ignore", "pipe", "pipe"], encoding: "utf8" },
    );
  } catch (err) {
    const detail = [err.stderr, err.stdout, err.message].filter(Boolean).join("\n").trim();
    throw new Error(
      `Failed to extract zip (${archivePath}). Tried unzip and python3.\n${detail || "unknown error"}`,
    );
  }
}

function extractArchive(archivePath, destDir, archiveType) {
  fs.mkdirSync(destDir, { recursive: true });
  if (archiveType === "zip") {
    if (process.platform === "win32") {
      extractZipWindows(archivePath, destDir);
    } else {
      extractZipUnix(archivePath, destDir);
    }
    return;
  }
  execFileSync("tar", ["-xf", archivePath, "-C", destDir], { stdio: "ignore" });
}

function findFirstFile(rootDir, name, depth = 0) {
  if (depth > 8 || !fs.existsSync(rootDir)) return null;
  const direct = path.join(rootDir, name);
  if (fs.existsSync(direct) && fs.statSync(direct).isFile()) return direct;
  const entries = fs.readdirSync(rootDir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(rootDir, entry.name);
    if (entry.isFile() && entry.name === name) return full;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const found = findFirstFile(path.join(rootDir, entry.name), name, depth + 1);
    if (found) return found;
  }
  return null;
}

function chmodExec(filePath) {
  if (process.platform === "win32") return;
  try {
    fs.chmodSync(filePath, 0o755);
  } catch (_) {
    /* ignore */
  }
}

function ensureSymlink(aliasPath, targetName) {
  try {
    if (fs.existsSync(aliasPath)) return;
    try {
      const stat = fs.lstatSync(aliasPath);
      if (stat.isSymbolicLink() || stat.isFile()) {
        fs.rmSync(aliasPath, { force: true });
      }
    } catch (_) {
      /* ignore */
    }
    fs.symlinkSync(targetName, aliasPath);
  } catch (_) {
    /* ignore */
  }
}

function normalizeMacPhpLibs(rootDir) {
  if (process.platform !== "darwin") return;
  const libDir = path.join(rootDir, "bin", "php7", "lib");
  if (!fs.existsSync(libDir)) return;
  for (const entry of fs.readdirSync(libDir)) {
    const full = path.join(libDir, entry);
    let stat;
    try {
      stat = fs.lstatSync(full);
    } catch (_) {
      continue;
    }
    if (!stat.isSymbolicLink()) continue;
    let linkTarget;
    try {
      linkTarget = fs.readlinkSync(full);
    } catch (_) {
      continue;
    }
    if (!path.isAbsolute(linkTarget)) continue;
    const basename = path.basename(linkTarget);
    if (!fs.existsSync(path.join(libDir, basename))) continue;
    try {
      fs.rmSync(full, { force: true });
      fs.symlinkSync(basename, full);
    } catch (_) {
      /* ignore */
    }
  }
  ensureSymlink(path.join(libDir, "libleveldb.1.dylib"), "libleveldb.1.23.0.dylib");
  ensureSymlink(path.join(libDir, "libleveldb.dylib"), "libleveldb.1.23.0.dylib");
  ensureSymlink(path.join(libDir, "libzip.5.dylib"), "libzip.5.5.dylib");
}

function normalizePhpIni(rootDir) {
  const iniPath = findFirstFile(rootDir, "php.ini");
  const extRoot = path.join(rootDir, "bin", "php7", "lib", "php", "extensions");
  let extDir = null;
  if (fs.existsSync(extRoot)) {
    const dirs = fs.readdirSync(extRoot, { withFileTypes: true }).filter((d) => d.isDirectory());
    if (dirs[0]) extDir = path.join(extRoot, dirs[0].name);
  }
  if (!iniPath || !extDir) return;
  let text = fs.readFileSync(iniPath, "utf8");
  if (/^extension_dir\s*=.*$/m.test(text)) {
    text = text.replace(/^extension_dir\s*=.*$/m, `extension_dir="${extDir}"`);
  } else {
    text += `\nextension_dir="${extDir}"\n`;
  }
  fs.writeFileSync(iniPath, text, "utf8");
}

function stripQuarantine(filePath) {
  if (process.platform !== "darwin") return;
  try {
    execFileSync("xattr", ["-dr", "com.apple.quarantine", filePath], { stdio: "ignore" });
  } catch (_) {
    /* ignore */
  }
}

function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  // runtime.json carries the Firefly password / API token / APP_KEY and the
  // data dir may be cloud-synced — keep it owner-only.
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  try {
    fs.chmodSync(filePath, 0o600);
  } catch (_) {
    /* best effort on non-POSIX */
  }
}

function readJson(filePath, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (_) {
    return fallback;
  }
}

function randomSecret(size = 24) {
  return crypto.randomBytes(size).toString("base64url");
}

function randomLaravelAppKey() {
  return `base64:${crypto.randomBytes(32).toString("base64")}`;
}

function randomFixedToken(length = 32) {
  return crypto.randomBytes(length * 2).toString("base64url").slice(0, length);
}

function renderEnv(env) {
  return Object.entries(env)
    .map(([key, value]) => `${key}=${String(value ?? "")}`)
    .join("\n");
}

function ensureFireflyEnv(dataDir) {
  const appDir = fireflyAppDir(dataDir);
  const envFile = path.join(appDir, ".env");
  const runtime = readJson(fireflyRuntimeFile(dataDir), {}) || {};
  if (!runtime.appKey || !String(runtime.appKey).startsWith("base64:")) {
    runtime.appKey = randomLaravelAppKey();
  }
  if (!runtime.cronToken || String(runtime.cronToken).length !== 32) {
    runtime.cronToken = randomFixedToken(32);
  }
  const dbPath = path.join(appDir, "storage", "database", "firefly.sqlite");
  const env = {
    APP_ENV: "production",
    APP_DEBUG: "false",
    APP_KEY: runtime.appKey,
    APP_URL: fireflyUrl(),
    SITE_OWNER: runtime.email || "orb@local.invalid",
    TZ: "UTC",
    DEFAULT_LANGUAGE: "en_US",
    DEFAULT_LOCALE: "equal",
    TRUSTED_PROXIES: "127.0.0.1,::1",
    LOG_CHANNEL: "stack",
    DB_CONNECTION: "sqlite",
    DB_DATABASE: dbPath,
    CACHE_DRIVER: "file",
    SESSION_DRIVER: "file",
    QUEUE_CONNECTION: "sync",
    MAIL_MAILER: "log",
    DKR_CHECK_SQLITE: "true",
    DKR_RUN_MIGRATION: "false",
    STATIC_CRON_TOKEN: runtime.cronToken || randomFixedToken(32),
    AUTHENTICATION_GUARD: "web",
    APP_NAME: "Orb_Finance",
  };
  // .env carries APP_KEY — owner-only, same as runtime.json.
  fs.writeFileSync(envFile, `${renderEnv(env)}\n`, { encoding: "utf8", mode: 0o600 });
  try {
    fs.chmodSync(envFile, 0o600);
  } catch (_) {
    /* best effort on non-POSIX */
  }
  runtime.cronToken = String(env.STATIC_CRON_TOKEN);
  writeJson(fireflyRuntimeFile(dataDir), runtime);
}

function runPhp(dataDir, args, options = {}) {
  const php = phpBinaryPath(dataDir);
  const appDir = fireflyAppDir(dataDir);
  const result = spawnSync(php, args, {
    cwd: appDir,
    env: {
      ...process.env,
      HOME: fireflyDataRoot(dataDir),
      USERPROFILE: fireflyDataRoot(dataDir),
      ...(options.env || {}),
    },
    encoding: "utf8",
    stdio: options.capture ? ["ignore", "pipe", "pipe"] : "pipe",
    // Verbose migrations overflow the 1 MiB default and abort with ENOBUFS.
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.status !== 0) {
    const stderr = (result.stderr || "").trim();
    const stdout = (result.stdout || "").trim();
    throw new Error(stderr || stdout || `php ${args.join(" ")} exited ${result.status}`);
  }
  return result.stdout || "";
}

async function ensurePhpRuntime(dataDir, onStatus = () => {}) {
  const targetRoot = path.join(fireflyDataRoot(dataDir), "php");
  const marker = fs.existsSync(phpRuntimeMarker(targetRoot))
    ? fs.readFileSync(phpRuntimeMarker(targetRoot), "utf8").trim()
    : "";
  const phpPath = phpBinaryPath(dataDir);
  if (fs.existsSync(phpPath) && marker === PHP_RUNTIME_ID) {
    normalizeMacPhpLibs(targetRoot);
    normalizePhpIni(targetRoot);
    return phpPath;
  }
  // Don't delete the working runtime until a replacement is staged — a failed
  // download/extract used to leave Firefly with no PHP at all until back online.
  const bundledRoot = bundledFireflyRoot();
  const bundledPhpRoot = bundledRoot ? path.join(bundledRoot, "php") : null;
  const bundledMarker = bundledPhpRoot && fs.existsSync(phpRuntimeMarker(bundledPhpRoot))
    ? fs.readFileSync(phpRuntimeMarker(bundledPhpRoot), "utf8").trim()
    : "";
  if (bundledPhpRoot && bundledMarker === PHP_RUNTIME_ID) {
    fs.mkdirSync(fireflyDataRoot(dataDir), { recursive: true });
    fs.rmSync(targetRoot, { recursive: true, force: true });
    fs.cpSync(bundledPhpRoot, targetRoot, { recursive: true });
    normalizeMacPhpLibs(targetRoot);
    normalizePhpIni(targetRoot);
    fs.writeFileSync(phpRuntimeMarker(targetRoot), `${PHP_RUNTIME_ID}\n`, "utf8");
    chmodExec(phpBinaryPath(dataDir));
    stripQuarantine(targetRoot);
    onStatus("Using bundled PHP runtime seed");
    return phpBinaryPath(dataDir);
  }
  const spec = phpArchiveSpec();
  const tmpDir = path.join(fireflyDataRoot(dataDir), ".tmp");
  fs.mkdirSync(tmpDir, { recursive: true });
  const archive = path.join(tmpDir, spec.asset);
  let lastPct = -1;
  onStatus("Downloading embedded PHP runtime…");
  await downloadFile(spec.url, archive, (pct) => {
    if (pct >= lastPct + 10) {
      lastPct = pct;
      onStatus(`Downloading embedded PHP… ${pct}%`);
    }
  });
  const extractTo = path.join(tmpDir, "php");
  fs.rmSync(extractTo, { recursive: true, force: true });
  extractArchive(archive, extractTo, spec.archiveType);
  const found = findFirstFile(
    extractTo,
    process.platform === "win32" ? "php.exe" : "php",
  );
  if (!found) throw new Error("Portable PHP executable not found after extraction");
  fs.rmSync(targetRoot, { recursive: true, force: true });
  fs.cpSync(extractTo, targetRoot, { recursive: true });
  normalizeMacPhpLibs(targetRoot);
  normalizePhpIni(targetRoot);
  fs.writeFileSync(phpRuntimeMarker(targetRoot), `${PHP_RUNTIME_ID}\n`, "utf8");
  chmodExec(phpBinaryPath(dataDir));
  stripQuarantine(targetRoot);
  onStatus("Embedded PHP ready");
  return phpBinaryPath(dataDir);
}

// Everything under app/storage is user state (sqlite DB, Passport keys, uploads).
// Replacing the app tree must never take it with it.
const PRESERVED_APP_PATHS = [
  path.join("storage", "database"),
  path.join("storage", "upload"),
  path.join("storage", "oauth-private.key"),
  path.join("storage", "oauth-public.key"),
];

function stashAppState(appDir) {
  const stashDir = path.join(path.dirname(appDir), ".app-state-stash");
  // Build the new stash beside the old one and swap only if we captured
  // something: if a previous upgrade died after wiping appDir, the old stash
  // is the ONLY copy of the finance DB — never clobber it with emptiness.
  const building = `${stashDir}.new`;
  fs.rmSync(building, { recursive: true, force: true });
  const stashed = [];
  for (const rel of PRESERVED_APP_PATHS) {
    const source = path.join(appDir, rel);
    if (!fs.existsSync(source)) continue;
    const target = path.join(building, rel);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.cpSync(source, target, { recursive: true });
    stashed.push(rel);
  }
  if (stashed.length) {
    fs.rmSync(stashDir, { recursive: true, force: true });
    fs.renameSync(building, stashDir);
    return { stashDir, stashed };
  }
  fs.rmSync(building, { recursive: true, force: true });
  if (fs.existsSync(stashDir)) {
    const prior = PRESERVED_APP_PATHS.filter((rel) =>
      fs.existsSync(path.join(stashDir, rel)),
    );
    return { stashDir, stashed: prior };
  }
  return { stashDir, stashed: [] };
}

function restoreAppState({ stashDir, stashed }, appDir) {
  for (const rel of stashed) {
    const source = path.join(stashDir, rel);
    const target = path.join(appDir, rel);
    fs.rmSync(target, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.cpSync(source, target, { recursive: true });
  }
  fs.rmSync(stashDir, { recursive: true, force: true });
}

/**
 * Replace ``appDir`` with the tree produced by ``populate(appDir)``, keeping
 * the old tree as ``app.bak`` until the copy succeeds. A mid-copy failure
 * (disk full, cloud-sync lock) restores the previous tree instead of leaving
 * nothing behind.
 */
function swapInAppTree(appDir, populate) {
  const backup = `${appDir}.bak`;
  fs.rmSync(backup, { recursive: true, force: true });
  if (fs.existsSync(appDir)) fs.renameSync(appDir, backup);
  try {
    fs.mkdirSync(appDir, { recursive: true });
    populate(appDir);
  } catch (err) {
    fs.rmSync(appDir, { recursive: true, force: true });
    if (fs.existsSync(backup)) fs.renameSync(backup, appDir);
    throw err;
  }
  fs.rmSync(backup, { recursive: true, force: true });
}

function passportKeysExist(dataDir) {
  const storage = path.join(fireflyAppDir(dataDir), "storage");
  return ["oauth-private.key", "oauth-public.key"].every((name) => {
    const file = path.join(storage, name);
    try {
      return fs.statSync(file).size > 0;
    } catch (_) {
      return false;
    }
  });
}

async function ensureFireflyApp(dataDir, onStatus = () => {}) {
  const appDir = fireflyAppDir(dataDir);
  const versionMarker = path.join(appDir, ".orb-firefly-version");
  if (fs.existsSync(versionMarker) && fs.readFileSync(versionMarker, "utf8").trim() === FIREFLY_VERSION) {
    return appDir;
  }
  const stash = stashAppState(appDir);
  const bundledRoot = bundledFireflyRoot();
  if (bundledRoot && fs.existsSync(path.join(bundledRoot, "app", ".orb-firefly-version"))) {
    const bundledVersion = fs.readFileSync(
      path.join(bundledRoot, "app", ".orb-firefly-version"),
      "utf8",
    ).trim();
    if (bundledVersion === FIREFLY_VERSION) {
      fs.mkdirSync(path.dirname(appDir), { recursive: true });
      swapInAppTree(appDir, (dest) => {
        fs.cpSync(path.join(bundledRoot, "app"), dest, { recursive: true });
      });
      restoreAppState(stash, appDir);
      onStatus("Using bundled Firefly app seed");
      return appDir;
    }
  }
  const tmpDir = path.join(fireflyDataRoot(dataDir), ".tmp");
  fs.mkdirSync(tmpDir, { recursive: true });
  const archiveName = `FireflyIII-${FIREFLY_VERSION}.tar.gz`;
  const archive = path.join(tmpDir, archiveName);
  const url = `https://github.com/firefly-iii/firefly-iii/releases/download/${FIREFLY_VERSION}/${archiveName}`;
  let lastPct = -1;
  onStatus(`Downloading Firefly III ${FIREFLY_VERSION}…`);
  await downloadFile(url, archive, (pct) => {
    if (pct >= lastPct + 10) {
      lastPct = pct;
      onStatus(`Downloading Firefly III… ${pct}%`);
    }
  });
  const extractTo = path.join(tmpDir, "firefly-app");
  fs.rmSync(extractTo, { recursive: true, force: true });
  extractArchive(archive, extractTo, "tar.gz");
  const entries = fs.readdirSync(extractTo);
  if (!entries.length) throw new Error("Firefly archive extracted to an empty tree");
  swapInAppTree(appDir, (dest) => {
    for (const entry of entries) {
      fs.cpSync(path.join(extractTo, entry), path.join(dest, entry), { recursive: true });
    }
  });
  restoreAppState(stash, appDir);
  fs.writeFileSync(versionMarker, `${FIREFLY_VERSION}\n`, "utf8");
  onStatus("Firefly III app ready");
  return appDir;
}

function ensureBootstrapLayout(dataDir) {
  const appDir = fireflyAppDir(dataDir);
  for (const sub of ["storage", "storage/database", "storage/upload", "bootstrap/cache"]) {
    fs.mkdirSync(path.join(appDir, sub), { recursive: true });
  }
  const sqliteFile = path.join(appDir, "storage", "database", "firefly.sqlite");
  if (!fs.existsSync(sqliteFile)) fs.writeFileSync(sqliteFile, "");
}

function ensureRuntimeMetadata(dataDir) {
  const file = fireflyRuntimeFile(dataDir);
  const existing = readJson(file, {}) || {};
  if (!existing.email) existing.email = "orb@local.invalid";
  if (!existing.password) existing.password = randomSecret(16);
  if (!existing.instanceId) existing.instanceId = crypto.randomUUID();
  writeJson(file, existing);
  return existing;
}

function bootstrapStateScript(email) {
  const esc = (value) => String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  return [
    "require 'vendor/autoload.php';",
    "$app = require 'bootstrap/app.php';",
    "$app->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap();",
    `$user = \\FireflyIII\\User::where('email', '${esc(email)}')->first();`,
    "$clients = \\Illuminate\\Support\\Facades\\DB::table('oauth_clients')->count();",
    "echo json_encode(['user_id' => $user?->id, 'group_id' => $user?->user_group_id, 'clients' => $clients], JSON_UNESCAPED_SLASHES);",
  ].join(" ");
}

function readBootstrapState(dataDir, email) {
  // Migrations already succeeded by the time this probe runs, so a failure
  // here is real breakage. Treating it as "state absent" caused a fresh
  // Passport client + token reset on every boot while hiding the error.
  const raw = runPhp(dataDir, ["-r", bootstrapStateScript(email)], { capture: true }).trim();
  const jsonStart = raw.lastIndexOf("{");
  return JSON.parse(jsonStart >= 0 ? raw.slice(jsonStart) : raw);
}

function bootstrapUserScript(email, groupTitle) {
  const esc = (value) => String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  return [
    "require 'vendor/autoload.php';",
    "$app = require 'bootstrap/app.php';",
    "$app->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap();",
    `$email = '${esc(email)}';`,
    // Via env, not argv — command lines are world-visible in `ps` output.
    "$password = getenv('ORB_FIREFLY_BOOTSTRAP_PASSWORD');",
    "if (!$password) { fwrite(STDERR, 'Missing bootstrap password env'); exit(1); }",
    `$groupTitle = '${esc(groupTitle)}';`,
    "$group = \\FireflyIII\\Models\\UserGroup::firstOrCreate(['title' => $groupTitle]);",
    "$role = \\FireflyIII\\Models\\Role::firstOrCreate(['name' => 'owner'], ['display_name' => 'Owner', 'description' => 'Orb desktop owner']);",
    "$userRole = \\FireflyIII\\Models\\UserRole::firstOrCreate(['title' => 'owner']);",
    "$currency = \\FireflyIII\\Models\\TransactionCurrency::where('code', 'EUR')->first();",
    "if (!$currency) { fwrite(STDERR, 'Missing EUR currency seed'); exit(1); }",
    "$user = \\FireflyIII\\User::where('email', $email)->first();",
    "if (!$user) {",
    "  $user = \\FireflyIII\\User::create(['email' => $email, 'password' => bcrypt($password), 'blocked' => 0, 'blocked_code' => null, 'user_group_id' => $group->id]);",
    "}",
    "$user->user_group_id = $group->id;",
    "$user->password = bcrypt($password);",
    "$user->blocked = 0;",
    "$user->blocked_code = null;",
    "$user->save();",
    "if (!$user->roles()->where('roles.id', $role->id)->exists()) { $user->roles()->attach($role->id); }",
    "\\FireflyIII\\Models\\GroupMembership::firstOrCreate(['user_id' => $user->id, 'user_group_id' => $group->id, 'user_role_id' => $userRole->id]);",
    "$group->currencies()->syncWithoutDetaching([$currency->id => ['group_default' => true]]);",
    "$user->currencies()->syncWithoutDetaching([$currency->id => ['user_default' => true]]);",
    "$token = $user->createToken('Orb Desktop')->accessToken;",
    "echo json_encode(['user_id' => $user->id, 'group_id' => $group->id, 'token' => $token], JSON_UNESCAPED_SLASHES);",
  ].join(" ");
}

async function ensureFireflyRuntime(dataDir, onStatus = () => {}) {
  fs.mkdirSync(fireflyDataRoot(dataDir), { recursive: true });
  await ensurePhpRuntime(dataDir, onStatus);
  await ensureFireflyApp(dataDir, onStatus);
  ensureBootstrapLayout(dataDir);
  const runtime = ensureRuntimeMetadata(dataDir);
  ensureFireflyEnv(dataDir);

  onStatus("Migrating Firefly database…");
  runPhp(dataDir, ["artisan", "migrate", "--force"]);

  // Full base seed (account types, currencies, transaction types, roles, …).
  // Currency-only seeding left account_types empty and broke Asset account creates.
  onStatus("Seeding Firefly base data…");
  runPhp(dataDir, ["artisan", "db:seed", "--force"]);

  // Trust the DB and key files, not the runtime flags: an app upgrade or a
  // half-finished first run can leave the flags set while the state is gone.
  const state = readBootstrapState(dataDir, runtime.email);
  if (!passportKeysExist(dataDir)) {
    onStatus("Preparing Firefly API auth…");
    runPhp(dataDir, ["artisan", "passport:keys", "--force"]);
    // Tokens minted under the previous keypair no longer verify.
    runtime.apiToken = null;
  }
  if (!state.clients) {
    onStatus("Preparing Firefly API auth…");
    runPhp(dataDir, ["artisan", "passport:client", "--personal", "--no-interaction"]);
    runtime.apiToken = null;
  }
  runtime.passportReady = true;
  writeJson(fireflyRuntimeFile(dataDir), runtime);

  if (!state.user_id || !runtime.apiToken) {
    onStatus("Creating Firefly desktop user…");
    const raw = runPhp(
      dataDir,
      ["-r", bootstrapUserScript(runtime.email, "Orb")],
      { capture: true, env: { ORB_FIREFLY_BOOTSTRAP_PASSWORD: runtime.password } },
    ).trim();
    const jsonStart = raw.lastIndexOf("{");
    const parsed = JSON.parse(jsonStart >= 0 ? raw.slice(jsonStart) : raw);
    runtime.userReady = true;
    runtime.userId = parsed.user_id;
    runtime.groupId = parsed.group_id;
    runtime.apiToken = parsed.token;
    writeJson(fireflyRuntimeFile(dataDir), runtime);
  }

  return {
    dataRoot: fireflyDataRoot(dataDir),
    appDir: fireflyAppDir(dataDir),
    php: phpBinaryPath(dataDir),
    runtimeFile: fireflyRuntimeFile(dataDir),
    url: fireflyUrl(),
    email: runtime.email,
    token: runtime.apiToken,
  };
}

module.exports = {
  FIREFLY_VERSION,
  PHP_BIN_VERSION,
  fireflyUrl,
  fireflyDataRoot,
  fireflyAppDir,
  fireflyRuntimeFile,
  phpBinaryPath,
  ensurePhpRuntime,
  ensureFireflyApp,
  ensureFireflyRuntime,
};
