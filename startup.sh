#!/bin/sh
# Deployment startup only. Does not modify Composer or the dashboard.
# Resolves repo-root private/ even if APP_BASE_DIR was set to the Python package directory "app".
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"

fail() {
  echo "FATAL: $1" >&2
  exit 1
}

# Repo root contains ./app/composer.py. The Python package directory is ./app and is not the root.
BASE="$SCRIPT_DIR"
if [ -n "${APP_BASE_DIR:-}" ]; then
  if [ -f "$APP_BASE_DIR/app/composer.py" ] && [ -f "$APP_BASE_DIR/app/app.py" ]; then
    BASE="$(CDPATH= cd -- "$APP_BASE_DIR" && pwd)"
  else
    echo "DSB: ignoring APP_BASE_DIR='${APP_BASE_DIR}' because it is not the repository root. Using ${SCRIPT_DIR}" >&2
  fi
fi

if [ -n "${DSB_PRIVATE_DIR:-}" ]; then
  [ -d "$DSB_PRIVATE_DIR" ] || fail "DSB_PRIVATE_DIR does not exist: $DSB_PRIVATE_DIR"
  PRIVATE="$(CDPATH= cd -- "$DSB_PRIVATE_DIR" && pwd)"
else
  PRIVATE=""
  for candidate in "$BASE/private" "$SCRIPT_DIR/private"; do
    if [ -f "$candidate/fonts/xenos/Helvetica.ttf" ]; then
      PRIVATE="$(CDPATH= cd -- "$candidate" && pwd)"
      break
    fi
  done
  if [ -z "$PRIVATE" ]; then
    PRIVATE="$BASE/private"
  fi
fi

echo "DSB: repo root ${BASE}"
echo "DSB: private dir ${PRIVATE}"

need_file() {
  if [ ! -f "$1" ]; then
    fail "missing required private runtime asset: $1"
  fi
  echo "DSB: found $1"
}

need_file "$PRIVATE/fonts/xenos/Helvetica.ttf"
need_file "$PRIVATE/fonts/xenos/Helvetica-Bold.ttf"
need_file "$PRIVATE/fonts/xenos/Helvetica-Oblique.ttf"
need_file "$PRIVATE/fonts/xenos/Arial-BoldMT.otf"
need_file "$PRIVATE/Chase Statement.pdf"

if [ ! -f "$BASE/app/composer.py" ] || [ ! -f "$BASE/app/app.py" ]; then
  fail "application files missing under $BASE/app"
fi

mkdir -p /home/workdir/attachments /home/workdir/artifacts
ln -sfn "$PRIVATE/fonts" /home/workdir/artifacts/fonts
ln -sfn "$PRIVATE/Chase Statement.pdf" "/home/workdir/attachments/Chase Statement.pdf"

if [ ! -f /home/workdir/artifacts/fonts/xenos/Helvetica.ttf ]; then
  fail "font link did not resolve"
fi
if [ ! -f "/home/workdir/attachments/Chase Statement.pdf" ]; then
  fail "template link did not resolve"
fi

echo "DSB: private assets OK"
echo "DSB: binding ${HOST}:${PORT}"
echo "DSB: health check path /health"

cd "$BASE/app"
export HOST PORT
exec python3 app.py
