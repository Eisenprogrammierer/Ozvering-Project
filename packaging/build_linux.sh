#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

cd "$ROOT"

if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "PyInstaller не установлен. Выполните:" >&2
  echo "  $PYTHON -m pip install -e '.[build]'" >&2
  exit 1
fi

"$PYTHON" -m PyInstaller --noconfirm --clean packaging/ozvering.spec

echo "Готово: $ROOT/dist/ozvering/"
echo "Запуск: $ROOT/dist/ozvering/ozvering"
