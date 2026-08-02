const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const crypto = require("crypto");
const { execFileSync, spawnSync } = require("child_process");
const { nativeArch } = require("./download-binaries");
const { PORTS, localhost } = require("./ports");
const { getRepoRoot, getResourcesRoot } = require("./paths");

const FIREFLY_VERSION = process.env.ORB_FIREFLY_VERSION || "v6.6.6";
const PHP_BIN_VERSION = process.env.ORB_PHP_BIN_VERSION || "1.2.0";
const PHP_RUNTIME_ID = `nativephp:${PHP_BIN_VERSION}:php-8.5`;

function fireflyUrl() {
  return localhost(PORTS.firefly);
}

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

function downloadFile(url, dest, onProgress) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    const getter = url.startsWith("https") ? https.get : http.get;
    const req = getter(url, { timeout: 180000 }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        file.close();
        try {
          fs.unlinkSync(dest);
        } catch (_) {
          /* ignore */
        }
        downloadFile(res.headers.location, dest, onProgress).then(resolve).catch(reject);
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

function extractArchive(archivePath, destDir, archiveType) {
  fs.mkdirSync(destDir, { recursive: true });
  if (archiveType === "zip") {
    const python = process.platform === "win32" ? "python" : "python3";
    execFileSync(python, ["-c", `import zipfile; zipfile.ZipFile(r'${archivePath}').extractall(r'${destDir}')`], {
      stdio: "ignore",
    });
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
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
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

function envToObject(source) {
  const out = {};
  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const idx = line.indexOf("=");
    if (idx === -1) continue;
    let value = line.slice(idx + 1);
    if (
      (value.startsWith("\"") && value.endsWith("\""))
      || (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[line.slice(0, idx)] = value;
  }
  return out;
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
    TRUSTED_PROXIES: "**",
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
  fs.writeFileSync(envFile, `${renderEnv(env)}\n`, "utf8");
  runtime.cronToken = String(env.STATIC_CRON_TOKEN);
  writeJson(fireflyRuntimeFile(dataDir), runtime);
}

function runPhp(dataDir, args, options = {}) {
  const php = phpBinaryPath(dataDir);
  const appDir = fireflyAppDir(dataDir);
  const result = spawnSync(php, args, {
    cwd: appDir,
    env: { ...process.env, HOME: fireflyDataRoot(dataDir), USERPROFILE: fireflyDataRoot(dataDir) },
    encoding: "utf8",
    stdio: options.capture ? ["ignore", "pipe", "pipe"] : "pipe",
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
  fs.rmSync(targetRoot, { recursive: true, force: true });
  const bundledRoot = bundledFireflyRoot();
  const bundledPhpRoot = bundledRoot ? path.join(bundledRoot, "php") : null;
  const bundledMarker = bundledPhpRoot && fs.existsSync(phpRuntimeMarker(bundledPhpRoot))
    ? fs.readFileSync(phpRuntimeMarker(bundledPhpRoot), "utf8").trim()
    : "";
  if (bundledPhpRoot && bundledMarker === PHP_RUNTIME_ID) {
    fs.mkdirSync(fireflyDataRoot(dataDir), { recursive: true });
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
  fs.cpSync(extractTo, targetRoot, { recursive: true });
  normalizeMacPhpLibs(targetRoot);
  normalizePhpIni(targetRoot);
  fs.writeFileSync(phpRuntimeMarker(targetRoot), `${PHP_RUNTIME_ID}\n`, "utf8");
  chmodExec(phpBinaryPath(dataDir));
  stripQuarantine(targetRoot);
  onStatus("Embedded PHP ready");
  return phpBinaryPath(dataDir);
}

async function ensureFireflyApp(dataDir, onStatus = () => {}) {
  const appDir = fireflyAppDir(dataDir);
  const versionMarker = path.join(appDir, ".orb-firefly-version");
  if (fs.existsSync(versionMarker) && fs.readFileSync(versionMarker, "utf8").trim() === FIREFLY_VERSION) {
    return appDir;
  }
  const bundledRoot = bundledFireflyRoot();
  if (bundledRoot && fs.existsSync(path.join(bundledRoot, "app", ".orb-firefly-version"))) {
    const bundledVersion = fs.readFileSync(
      path.join(bundledRoot, "app", ".orb-firefly-version"),
      "utf8",
    ).trim();
    if (bundledVersion === FIREFLY_VERSION) {
      fs.rmSync(appDir, { recursive: true, force: true });
      fs.mkdirSync(path.dirname(appDir), { recursive: true });
      fs.cpSync(path.join(bundledRoot, "app"), appDir, { recursive: true });
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
  fs.rmSync(appDir, { recursive: true, force: true });
  fs.mkdirSync(appDir, { recursive: true });
  const entries = fs.readdirSync(extractTo);
  for (const entry of entries) {
    fs.cpSync(path.join(extractTo, entry), path.join(appDir, entry), { recursive: true });
  }
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

function generateTokenScript(email) {
  return [
    "require 'vendor/autoload.php';",
    "$app = require_once 'bootstrap/app.php';",
    "$app->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap();",
    `$user = FireflyIII\\User::where('email', '${email.replace(/'/g, "\\'")}')->first();`,
    "if (!$user) { fwrite(STDERR, 'User not found'); exit(1); }",
    "$token = $user->createToken('Orb Desktop')->accessToken;",
    "echo $token;",
  ].join(" ");
}

function bootstrapUserScript(email, password, groupTitle) {
  const esc = (value) => String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  return [
    "require 'vendor/autoload.php';",
    "$app = require 'bootstrap/app.php';",
    "$app->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap();",
    `$email = '${esc(email)}';`,
    `$password = '${esc(password)}';`,
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

  onStatus("Seeding Firefly currencies…");
  runPhp(dataDir, [
    "artisan",
    "db:seed",
    "--class=Database\\Seeders\\TransactionCurrencySeeder",
    "--force",
  ]);

  if (!runtime.passportReady) {
    onStatus("Preparing Firefly API auth…");
    runPhp(dataDir, ["artisan", "passport:keys", "--force"]);
    runPhp(dataDir, ["artisan", "passport:client", "--personal", "--no-interaction"]);
    runtime.passportReady = true;
    writeJson(fireflyRuntimeFile(dataDir), runtime);
  }

  if (!runtime.userReady || !runtime.apiToken) {
    onStatus("Creating Firefly desktop user…");
    const raw = runPhp(
      dataDir,
      ["-r", bootstrapUserScript(runtime.email, runtime.password, "Orb")],
      { capture: true },
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
