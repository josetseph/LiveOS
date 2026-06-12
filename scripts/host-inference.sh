#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARLIN_VENV="$ROOT_DIR/.host-inference-venv-marlin"
LOCAL_VENV="$ROOT_DIR/.host-inference-venv-local-models"
PID_FILE="$ROOT_DIR/.host-inference.pids"
LOG_DIR="$ROOT_DIR/.host-inference-logs"
PYTHON="${PYTHON:-}"

MARLIN_PORT="${MARLIN_PORT:-8790}"
LOCAL_MODELS_PORT="${LOCAL_MODELS_PORT:-8791}"
LAUNCHD_LABEL="${LAUNCHD_LABEL:-com.liveos.host-inference}"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/${LAUNCHD_LABEL}.plist"

log() {
  printf '==> %s\n' "$1" >&2
}

load_inference_env_defaults() {
  local env_file="$ROOT_DIR/backend/.env"
  [[ -f "$env_file" ]] || return

  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"

    case "$key" in
      FLORENCE_MAX_IMAGE_PIXELS|VIDEO_MAX_PIXELS|FPS|FPS_MAX_FRAMES|FPS_MIN_FRAMES)
        ;;
      *)
        continue
        ;;
    esac

    # Let explicit shell/launchd environment values win over backend/.env defaults.
    if [[ -z "${!key-}" ]]; then
      value="${value%\"}"
      value="${value#\"}"
      value="${value%\'}"
      value="${value#\'}"
      export "$key=$value"
    fi
  done <"$env_file"
}

usage() {
  cat <<'EOF'
LiveOS host inference

Usage:
  ./scripts/host-inference.sh <command>

Commands:
  install   Create/update native Python environments
  start     Start Marlin and local-models now
  stop      Stop Marlin and local-models now
  restart   Stop, then start
  status    Show process and health status
  enable    Start now and auto-start at macOS login/reboot via launchd
  disable   Stop and remove the macOS launchd auto-start entry
  logs      Follow Marlin and local-models logs
  run       Foreground mode used by launchd
EOF
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

ensure_macos() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "launchd auto-start is only supported on macOS. Use start/stop manually here." >&2
    exit 1
  fi
}

ensure_python() {
  if [[ -n "$PYTHON" && -x "$PYTHON" ]]; then
    return
  fi
  if [[ -n "$PYTHON" ]] && command_exists "$PYTHON"; then
    PYTHON="$(command -v "$PYTHON")"
    return
  fi
  for candidate in /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
    if [[ -x "$candidate" ]]; then
      PYTHON="$candidate"
      return
    fi
  done
  if ! command_exists python3.11; then
    echo "Python 3.11 not found. Install with: brew install python@3.11" >&2
    exit 1
  fi
  PYTHON="$(command -v python3.11)"
}

ensure_venv() {
  local venv_path="$1"
  local requirements="$2"
  local with_torch="${3:-0}"

  if [[ ! -d "$venv_path" ]]; then
    log "Creating venv at $venv_path"
    "$PYTHON" -m venv "$venv_path"
  fi

  # shellcheck source=/dev/null
  source "$venv_path/bin/activate"
  python -m pip install --upgrade pip >/dev/null

  if (( with_torch == 1 )); then
    if ! python -c "import torch" >/dev/null 2>&1; then
      log "Installing PyTorch (Apple Silicon / native) into $(basename "$venv_path")"
      pip install torch torchvision
    fi
  fi

  log "Installing requirements for $(basename "$venv_path")"
  pip install -r "$requirements"
  deactivate || true
}

install_envs() {
  mkdir -p "$LOG_DIR"
  ensure_python
  ensure_venv "$MARLIN_VENV" "$ROOT_DIR/backend/marlin_service/requirements.txt" 1
  ensure_venv "$LOCAL_VENV" "$ROOT_DIR/backend/local_models_service/requirements.txt" 1
}

wait_for_health() {
  local url="$1"
  local name="$2"
  for _ in $(seq 1 120); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name is healthy at $url"
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for $name at $url" >&2
  return 1
}

is_pid_running() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

load_pids() {
  MARLIN_PID=""
  LOCAL_MODELS_PID=""
  if [[ -f "$PID_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$PID_FILE"
  fi
}

write_pids() {
  cat >"$PID_FILE" <<EOF
MARLIN_PID=$1
LOCAL_MODELS_PID=$2
MARLIN_PORT=$MARLIN_PORT
LOCAL_MODELS_PORT=$LOCAL_MODELS_PORT
EOF
}

start_marlin() {
  log "Starting Marlin on 0.0.0.0:${MARLIN_PORT}"
  bash -lc "
    source '$MARLIN_VENV/bin/activate' && \
    export PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:'\"\$PATH\" && \
    export MARLIN_MODEL_PATH='$ROOT_DIR/backend/models/marlin-2b' && \
    export FORCE_QWENVL_VIDEO_READER=pyav && \
    export VIDEO_MAX_PIXELS='${VIDEO_MAX_PIXELS:-200704}' && \
    export FPS='${FPS:-2.0}' && \
    export FPS_MAX_FRAMES='${FPS_MAX_FRAMES:-240}' && \
    export FPS_MIN_FRAMES='${FPS_MIN_FRAMES:-4}' && \
    cd '$ROOT_DIR/backend/marlin_service' && \
    exec uvicorn app:app --host 0.0.0.0 --port '$MARLIN_PORT'
  " >"$LOG_DIR/marlin.log" 2>&1 &
  echo "$!"
}

start_local_models() {
  log "Starting local-models on 0.0.0.0:${LOCAL_MODELS_PORT}"
  bash -lc "
    source '$LOCAL_VENV/bin/activate' && \
    export PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:'\"\$PATH\" && \
    export FFMPEG_BINARY='${FFMPEG_BINARY:-/opt/homebrew/bin/ffmpeg}' && \
    export FFPROBE_BINARY='${FFPROBE_BINARY:-/opt/homebrew/bin/ffprobe}' && \
    export FLORENCE_MODEL_PATH='$ROOT_DIR/backend/models/florence-2-large' && \
    export WHISPER_MODEL_PATH='$ROOT_DIR/backend/models/whisper-large-v3-turbo' && \
    export RERANKER_MODEL_PATH='$ROOT_DIR/backend/models/qwen3-reranker-0.6b' && \
    export PDF_VISUAL_EXTRACTION_ENABLED='${PDF_VISUAL_EXTRACTION_ENABLED:-true}' && \
    export PDF_VISUAL_EXTRACTION_MAX_PAGES='${PDF_VISUAL_EXTRACTION_MAX_PAGES:-0}' && \
    export PDF_VISUAL_RENDER_DPI='${PDF_VISUAL_RENDER_DPI:-144}' && \
    export PDF_VISUAL_TEXT_THRESHOLD='${PDF_VISUAL_TEXT_THRESHOLD:-80}' && \
    export FLORENCE_MAX_IMAGE_PIXELS='${FLORENCE_MAX_IMAGE_PIXELS:-1500000}' && \
    cd '$ROOT_DIR/backend/local_models_service' && \
    exec uvicorn app:app --host 0.0.0.0 --port '$LOCAL_MODELS_PORT'
  " >"$LOG_DIR/local-models.log" 2>&1 &
  echo "$!"
}

start_services() {
  mkdir -p "$LOG_DIR"
  load_inference_env_defaults
  load_pids
  if is_pid_running "${MARLIN_PID:-}" && is_pid_running "${LOCAL_MODELS_PID:-}"; then
    echo "Host inference already running."
    print_endpoints
    return
  fi

  install_envs
  local marlin_pid local_models_pid
  marlin_pid="$(start_marlin)"
  local_models_pid="$(start_local_models)"
  write_pids "$marlin_pid" "$local_models_pid"

  wait_for_health "http://127.0.0.1:${MARLIN_PORT}/health" "Marlin"
  wait_for_health "http://127.0.0.1:${LOCAL_MODELS_PORT}/health" "local-models"
  print_endpoints
}

stop_pid() {
  local name="$1"
  local pid="$2"
  if is_pid_running "$pid"; then
    kill "$pid"
    echo "Stopped $name (pid=$pid)"
  fi
}

stop_port_listener() {
  local name="$1"
  local port="$2"
  command_exists lsof || return

  local pid
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    if is_pid_running "$pid"; then
      kill "$pid"
      echo "Stopped stale $name listener on port $port (pid=$pid)"
    fi
  done < <(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
}

stop_services() {
  if [[ "${HOST_INFERENCE_NO_LAUNCHD_BOOTOUT:-0}" != "1" && "$(uname -s)" == "Darwin" && -f "$LAUNCHD_PLIST" ]]; then
    launchctl bootout "$(launchd_domain)" "$LAUNCHD_PLIST" >/dev/null 2>&1 || true
  fi

  load_pids
  stop_pid "Marlin" "${MARLIN_PID:-}"
  stop_pid "local-models" "${LOCAL_MODELS_PID:-}"
  stop_port_listener "Marlin" "$MARLIN_PORT"
  stop_port_listener "local-models" "$LOCAL_MODELS_PORT"
  rm -f "$PID_FILE"
  echo "Host inference stopped."
}

status_services() {
  load_pids
  printf 'Marlin process:       '
  if is_pid_running "${MARLIN_PID:-}"; then
    echo "running (pid=$MARLIN_PID)"
  else
    echo "stopped"
  fi

  printf 'Local models process: '
  if is_pid_running "${LOCAL_MODELS_PID:-}"; then
    echo "running (pid=$LOCAL_MODELS_PID)"
  else
    echo "stopped"
  fi

  printf 'Marlin health:        '
  curl -fsS "http://127.0.0.1:${MARLIN_PORT}/health" >/dev/null 2>&1 && echo "ok" || echo "unreachable"
  printf 'Local models health:  '
  curl -fsS "http://127.0.0.1:${LOCAL_MODELS_PORT}/health" >/dev/null 2>&1 && echo "ok" || echo "unreachable"

  if [[ -f "$LAUNCHD_PLIST" ]]; then
    echo "Auto-start:           enabled ($LAUNCHD_PLIST)"
  else
    echo "Auto-start:           disabled"
  fi
}

print_endpoints() {
  cat <<EOF

Host inference is running:
  Marlin:        http://127.0.0.1:${MARLIN_PORT}
  Local models:  http://127.0.0.1:${LOCAL_MODELS_PORT}

Docker backend should use:
  MARLIN_SERVICE_URL=http://host.docker.internal:${MARLIN_PORT}
  LOCAL_MODELS_SERVICE_URL=http://host.docker.internal:${LOCAL_MODELS_PORT}

Logs:
  $LOG_DIR/marlin.log
  $LOG_DIR/local-models.log
EOF
}

write_launchd_plist() {
  mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
  cat >"$LAUNCHD_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${ROOT_DIR}/scripts/host-inference.sh</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>WorkingDirectory</key>
  <string>${ROOT_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd.log</string>
</dict>
</plist>
EOF
}

launchd_domain() {
  echo "gui/$(id -u)"
}

enable_launchd() {
  ensure_macos
  install_envs
  launchctl bootout "$(launchd_domain)" "$LAUNCHD_PLIST" >/dev/null 2>&1 || true
  HOST_INFERENCE_NO_LAUNCHD_BOOTOUT=1 stop_services
  write_launchd_plist
  launchctl bootout "$(launchd_domain)" "$LAUNCHD_PLIST" >/dev/null 2>&1 || true
  launchctl bootstrap "$(launchd_domain)" "$LAUNCHD_PLIST"
  launchctl enable "$(launchd_domain)/${LAUNCHD_LABEL}" >/dev/null 2>&1 || true
  launchctl kickstart -k "$(launchd_domain)/${LAUNCHD_LABEL}"
  wait_for_health "http://127.0.0.1:${MARLIN_PORT}/health" "Marlin"
  wait_for_health "http://127.0.0.1:${LOCAL_MODELS_PORT}/health" "local-models"
  echo "Host inference auto-start enabled at login/reboot."
  print_endpoints
}

disable_launchd() {
  ensure_macos
  launchctl bootout "$(launchd_domain)" "$LAUNCHD_PLIST" >/dev/null 2>&1 || true
  rm -f "$LAUNCHD_PLIST"
  stop_services
  echo "Host inference auto-start disabled."
}

run_foreground() {
  mkdir -p "$LOG_DIR"
  load_inference_env_defaults
  install_envs
  local marlin_pid local_models_pid
  marlin_pid="$(start_marlin)"
  local_models_pid="$(start_local_models)"
  write_pids "$marlin_pid" "$local_models_pid"

  trap 'HOST_INFERENCE_NO_LAUNCHD_BOOTOUT=1 stop_services; exit 0' TERM INT
  while is_pid_running "$marlin_pid" && is_pid_running "$local_models_pid"; do
    sleep 2
  done
  HOST_INFERENCE_NO_LAUNCHD_BOOTOUT=1
  stop_services
  exit 1
}

follow_logs() {
  mkdir -p "$LOG_DIR"
  touch "$LOG_DIR/marlin.log" "$LOG_DIR/local-models.log"
  tail -f "$LOG_DIR/marlin.log" "$LOG_DIR/local-models.log"
}

command="${1:-}"
case "$command" in
  install) install_envs ;;
  start) start_services ;;
  stop) stop_services ;;
  restart)
    stop_services
    start_services
    ;;
  status) status_services ;;
  enable) enable_launchd ;;
  disable) disable_launchd ;;
  logs) follow_logs ;;
  run) run_foreground ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "Unknown command: $command" >&2
    usage
    exit 1
    ;;
esac
