"""
view/ui/music_manager.py

Менеджер фоновой музыки с очередью категорий и мягким затуханием.

Категории: overture, ambient, victorious, tragic.
Треки категории лежат в music/<category>/.

Поведение:
- текущий трек всегда доигрывает до конца, затем стартует следующий
  трек текущей категории либо очередь сменой категории;
- смена категории без fade ждёт окончания текущего трека;
- смена категории с fade мягко глушит текущий трек и стартует новую.

События загрузки треков, переключения категорий и ошибок
воспроизведения записываются в журнал operation_ozverin.log
и дублируются в консоль средствами core.log_journal.
"""

import os

import pygame

from view.support.log_journal import get_logger

logger = get_logger("view.music")

CATEGORIES = ("overture", "ambient", "victorious", "tragic")
SUPPORTED_EXT = (".ogg", ".mp3", ".wav")
FADE_OUT_MS = 1500


class MusicManager:
    """
    Менеджер фоновой музыки по категориям.

    Сканирует поддиректории music/<category>/ при инициализации,
    поддерживает очередь смены категорий, мягкое затухание через
    pygame.mixer.music.fadeout и автоматический переход к следующему
    треку внутри категории. Метод update() должен вызываться каждый
    кадр из главного цикла приложения.

    Attributes:
        music_dir (str): Путь к корневой директории музыки.
        tracks (dict[str, list[str]]): Списки путей к трекам по категориям.
        _index (dict[str, int]): Текущие индексы воспроизведения по категориям.
        current_category (str | None): Текущая активная категория.
        pending_category (str | None): Категория, ожидающая запуска.
        fade_pending (bool): Флаг активного затухания.
        enabled (bool): Флаг доступности микшера pygame.
    """

    def __init__(self, music_dir: str):
        """
        Инициализирует менеджер музыки.

        Сканирует поддиректории категорий, инициализирует микшер
        pygame. При отсутствии директории или ошибке инициализации
        микшера устанавливает enabled=False и логирует предупреждение.

        Args:
            music_dir: Путь к корневой директории музыки.
        """
        self.music_dir = music_dir
        self.tracks: dict[str, list[str]] = {cat: [] for cat in CATEGORIES}
        self._index: dict[str, int] = {cat: 0 for cat in CATEGORIES}
        self.current_category: str | None = None
        self.pending_category: str | None = None
        self.fade_pending: bool = False
        self.enabled: bool = True
        self._scan()
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception as exc:
            logger.warning("Музыка отключена: %s", exc)
            self.enabled = False

    def _scan(self):
        """
        Сканирует поддиректории категорий и заполняет плейлисты.

        Для каждой категории из CATEGORIES ищет директорию
        music/<category>/, сортирует файлы по имени и фильтрует
        по поддерживаемым расширениям. Отсутствующие директории
        пропускаются с предупреждением.
        """
        if not os.path.isdir(self.music_dir):
            logger.warning(
                "Директория музыки не найдена: %s", self.music_dir
            )
            self.enabled = False
            return
        for cat in CATEGORIES:
            cat_dir = os.path.join(self.music_dir, cat)
            if not os.path.isdir(cat_dir):
                continue
            files = [
                os.path.join(cat_dir, f)
                for f in sorted(os.listdir(cat_dir))
                if f.lower().endswith(SUPPORTED_EXT)
            ]
            self.tracks[cat] = files
            logger.info("Категория %s: треков=%d", cat, len(files))

    def _has_tracks(self, cat: str) -> bool:
        """
        Проверяет наличие треков в указанной категории.

        Args:
            cat: Имя категории.

        Returns:
            bool: True, если в категории есть хотя бы один трек.
        """
        return bool(self.tracks.get(cat))

    def request_category(self, cat: str, fade: bool = False):
        """
        Запрашивает смену музыкальной категории.

        Без fade текущий трек доигрывается до конца, после чего
        запускается первый трек новой категории. С fade текущий
        трек мягко затухает через FADE_OUT_MS миллисекунд, и новая
        категория стартует после завершения затухания. Если запрошена
        та же категория и нет ожидающей смены, запрос игнорируется.
        Если категория пуста или микшер отключён, запрос игнорируется.

        Args:
            cat: Имя категории из CATEGORIES.
            fade: Если True, выполнить мягкое затухание текущего трека.
        """
        if not self.enabled or not self._has_tracks(cat):
            return
        if self.current_category == cat and self.pending_category is None:
            return
        if fade:
            self.pending_category = cat
            if pygame.mixer.music.get_busy():
                self.fade_pending = True
                pygame.mixer.music.fadeout(FADE_OUT_MS)
                logger.info("Затухание и переход к %s", cat)
            return
        if pygame.mixer.music.get_busy():
            self.pending_category = cat
            logger.info("Очередь: после текущего трека -> %s", cat)
        else:
            self._start_category(cat)

    def _start_category(self, cat: str):
        """
        Запускает воспроизведение категории с первого трека.

        Устанавливает текущую категорию, сбрасывает индекс
        воспроизведения и запускает первый трек.

        Args:
            cat: Имя категории для запуска.
        """
        self.current_category = cat
        self._index[cat] = 0
        self._play_track(cat, 0)

    def _play_track(self, cat: str, idx: int):
        """
        Загружает и однократно запускает трек по индексу.

        Индекс оборачивается по длине списка треков категории.
        При ошибке загрузки или воспроизведения логирует
        предупреждение и не меняет текущую категорию.

        Args:
            cat: Имя категории.
            idx: Индекс трека в списке категории.
        """
        files = self.tracks.get(cat, [])
        if not files:
            return
        idx = idx % len(files)
        path = files[idx]
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play(0)
            self.current_category = cat
            logger.info(
                "Играет трек %s [%s]", os.path.basename(path), cat
            )
        except Exception as exc:
            logger.warning("Не удалось сыграть %s: %s", path, exc)

    def update(self):
        """
        Обрабатывает переходы между треками и категориями.

        Должен вызываться каждый кадр из главного цикла.
        При активном затухании ждёт его завершения и запускает
        ожидающую категорию. При завершении текущего трека
        запускает ожидающую категорию или следующий трек текущей.
        Не выполняет никаких действий, если микшер отключён
        или музыка уже играет.
        """
        if not self.enabled:
            return
        if self.fade_pending:
            if not pygame.mixer.music.get_busy():
                self.fade_pending = False
                cat = self.pending_category
                self.pending_category = None
                if cat is not None:
                    self._start_category(cat)
            return
        if pygame.mixer.music.get_busy():
            return
        if self.pending_category is not None:
            cat = self.pending_category
            self.pending_category = None
            self._start_category(cat)
        elif self.current_category is not None:
            cat = self.current_category
            self._index[cat] += 1
            self._play_track(cat, self._index[cat])