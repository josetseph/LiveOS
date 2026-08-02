#!/usr/bin/env bash
# Hotfix LifeOS.app so note image+audio ingest works again.
# 1) Restores numpy/_core/tests (stripped by an old pruneBackendTree bug)
# 2) Syncs multimodal_runtime.py + multimodal_services.py from this repo
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP_BE="/Applications/LifeOS.app/Contents/Resources/backend"
APP_PY="$APP_BE/python/bin/python3"
SITE="$APP_BE/python/lib/python3.12/site-packages"
WHEEL_DIR="$ROOT/.tmp/numpy-fix"
EXTRACT="$WHEEL_DIR/extract"

if [[ ! -x "$APP_PY" ]]; then
  echo "LifeOS.app python not found at $APP_PY" >&2
  exit 1
fi

mkdir -p "$WHEEL_DIR"
if [[ ! -f "$EXTRACT/numpy/_core/tests/_natype.py" ]]; then
  echo "Downloading numpy 2.2.6 wheel for tests tree…"
  "$APP_PY" -m pip download --no-deps --only-binary=:all: -d "$WHEEL_DIR" "numpy==2.2.6"
  mkdir -p "$EXTRACT"
  (cd "$EXTRACT" && unzip -qo "$WHEEL_DIR"/numpy-*.whl 'numpy/_core/tests/*')
fi

echo "Restoring $SITE/numpy/_core/tests …"
rm -rf "$SITE/numpy/_core/tests"
cp -R "$EXTRACT/numpy/_core/tests" "$SITE/numpy/_core/tests"

echo "Syncing multimodal modules…"
cp "$ROOT/backend/app/services/multimodal_runtime.py" \
  "$APP_BE/app/services/multimodal_runtime.py"
cp "$ROOT/backend/app/services/multimodal_services.py" \
  "$APP_BE/app/services/multimodal_services.py"

echo "Verifying imports…"
"$APP_PY" -c "
import numpy._core.tests._natype
from transformers import AutoModelForCausalLM, AutoModelForSpeechSeq2Seq
print('ok: numpy tests + transformers AutoModel')
"

echo "Done. Quit and reopen LifeOS, then Retry the failed note."
