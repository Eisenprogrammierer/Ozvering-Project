import json
from pathlib import Path

from .log_journal import get_logger

logger = get_logger("view.content")
ROOT = Path(__file__).resolve().parents[2]


class Content:

    def __init__(self, root=None):
        self.root = Path(root) if root else ROOT / "configs" / "content"
        self.files = {}
        self._load_all()
        self.order_types = self.get("orders", [])
        self.notebook = self.get("notebook", {"tabs": []})
        self.documents = self.get("documents", [])
        self.dialogues = self.get("dialogues", {})
        self.decisions = self.get("decisions", [])
        logger.info(
            "Контент UI загружен: файлов=%d, приказов=%d, "
            "документов=%d, диалогов=%d",
            len(self.files),
            len(self.order_types),
            len(self.documents),
            len(self.dialogues),
        )

    def _load_all(self):
        if not self.root.is_dir():
            logger.warning("Каталог контента не найден: %s", self.root)
            return
        for path in sorted(self.root.glob("*.json")):
            data = self._read(path)
            if data is not None:
                self.files[path.stem] = data

    def _read(self, path):
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:
            logger.warning("Не удалось прочитать %s: %s", path, exc)
            return None

    def get(self, name, default=None):
        """Документ контента по имени файла (с `.json` или без)."""
        key = str(name or "")
        if key.endswith(".json"):
            key = key[:-5]
        return self.files.get(key, default)

    def names(self):
        return sorted(self.files)
