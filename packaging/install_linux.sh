#!/usr/bin/env bash
# Установка уже собранного dist/ozvering в пользовательский каталог + ярлык.
# Сначала выполните packaging/build_linux.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/dist/ozvering"
DEST="${OZVERING_INSTALL_DIR:-$HOME/.local/opt/ozvering}"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [ ! -x "$SRC/ozvering" ]; then
  echo "Сборка не найдена: $SRC/ozvering" >&2
  echo "Сначала запустите packaging/build_linux.sh" >&2
  exit 1
fi

mkdir -p "$DEST"
cp -a "$SRC/." "$DEST/"

mkdir -p "$APPS"
sed "s|@INSTALL_DIR@|$DEST|g" \
  "$ROOT/packaging/ozvering.desktop.in" > "$APPS/ozvering.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS" >/dev/null 2>&1 || true
fi

echo "Установлено: $DEST"
echo "Запуск: $DEST/ozvering"
echo "Ярлык: $APPS/ozvering.desktop"
