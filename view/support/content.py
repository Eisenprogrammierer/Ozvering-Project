from pathlib import Path

from .log_journal import get_logger

logger = get_logger("view.content")
ROOT = Path(__file__).resolve().parents[2]


class Content:

    def __init__(self, root=None):
        self.root = Path(root) if root else ROOT / "configs" / "content"
        self.order_types = self._load("orders.json", [])
        self.notebook = self._load("notebook.json", {"tabs": []})
        self.documents = self._load("documents.json", [])
        self.dialogues = self._load("dialogues.json", {})
        self.decisions = self._load("decisions.json", [])
        logger.info(
            "Контент UI загружен: приказов=%d, документов=%d, диалогов=%d",
            len(self.order_types),
            len(self.documents),
            len(self.dialogues),
        )

    def _load(self, name, default):
        import json

        path = self.root / name
        if not path.exists():
            logger.warning("Контент не найден: %s", path)
            return default
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Не удалось прочитать %s: %s", path, exc)
            return default
