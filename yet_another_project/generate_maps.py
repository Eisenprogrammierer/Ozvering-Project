"""
generate_maps.py
Оффлайн-генератор карт.
Творческий инструмент, в рантайме игры не вызывается.
Генерирует карты 256x256, где одна клетка равна одному километру.
Поддерживаемые биомы:
1 — Вода
2 — Равнина
3 — Холмы
4 — Горы
5 — Лес
6 — Пустыня
7 — Болото
8 — Тундра
9 — Городская застройка
10 — Сельская застройка
Высота, влажность, температура, речная сеть и плотность
расселения вычисляются независимо фрактальным шумом,
после чего комбинируются в карту биомов.
"""
import numpy as np
from pathlib import Path

OUT_DIR = Path("scenarios/maps")
ROWS = 256
COLS = 256
KM_PER_CELL = 1.0


def _value_noise(rng, rows, cols, cell):
    """
    Генерирует один октавный слой value-noise.
    Создаёт случайную сетку узлов с шагом cell и выполняет
    билинейную интерполяцию до полного разрешения карты.
    Args:
        rng: Генератор случайных чисел numpy.
        rows: Количество строк карты.
        cols: Количество столбцов карты.
        cell: Размер ячейки сетки в клетках карты.
    Returns:
        np.ndarray: Массив значений шума [0, 1] формы (rows, cols).
    """
    gr = rows // cell + 2
    gc = cols // cell + 2
    grid = rng.random((gr, gc))
    ys = np.linspace(0, gr - 2, rows)
    xs = np.linspace(0, gc - 2, cols)
    y0 = ys.astype(int)
    x0 = xs.astype(int)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    top = grid[y0][:, x0] * (1 - fx) + grid[y0][:, x0 + 1] * fx
    bot = grid[y0 + 1][:, x0] * (1 - fx) + grid[y0 + 1][:, x0 + 1] * fx
    return top * (1 - fy) + bot * fy


def fractal_noise(rng, rows, cols, start_cell=64, min_cell=4, gain=0.5):
    """
    Генерирует фрактальный шум суммированием октав value-noise.
    Каждая следующая октава имеет вдвое меньший масштаб ячейки
    и вдвое меньший вес. Результат нормализуется в [0, 1].
    Args:
        rng: Генератор случайных чисел numpy.
        rows: Количество строк карты.
        cols: Количество столбцов карты.
        start_cell: Размер ячейки первой (крупнейшей) октавы.
        min_cell: Минимальный размер ячейки последней октавы.
        gain: Коэффициент убывания амплитуды октав.
    Returns:
        np.ndarray: Нормализованный массив шума формы (rows, cols).
    """
    total = np.zeros((rows, cols))
    amp = 1.0
    amp_sum = 0.0
    cell = start_cell
    while cell >= min_cell:
        total += amp * _value_noise(rng, rows, cols, cell)
        amp_sum += amp
        amp *= gain
        cell //= 2
    total /= amp_sum
    return (total - total.min()) / (total.max() - total.min())


def rivers_from(river_noise, heights):
    """
    Выделяет русла рек как узкую полосу вокруг уровня 0.5
    речного шума. Реки прокладываются только по суше
    в диапазоне высот от уровня воды до предгорий.
    Args:
        river_noise: Массив речного шума [0, 1].
        heights: Массив высот [0, 1].
    Returns:
        np.ndarray: Булева маска русел рек.
    """
    band = np.abs(river_noise - 0.5) < 0.015
    return band & (heights >= 0.25) & (heights < 0.55)


def biomes_from(heights, moisture, temperature, settlement, rivers, rng):
    """
    Комбинирует поля высот, влажности, температуры, расселения
    и речной сети в карту биомов.
    Порядок наложения:
    1. Базовая сетка по высоте (вода, равнина, холмы, горы).
    2. Лес на влажных умеренных равнинах и холмах.
    3. Болото в низинах с высокой влажностью.
    4. Пустыня в сухих жарких низинах.
    5. Тундра в холодных зонах.
    6. Реки поверх суши.
    7. Сельская застройка на равнинах и вырубленном лесу
       в зонах расселения.
    8. Городская застройка в центрах расселения.
    Args:
        heights: Массив высот [0, 1].
        moisture: Массив влажности [0, 1].
        temperature: Массив температуры [0, 1].
        settlement: Массив плотности расселения [0, 1].
        rivers: Булева маска русел рек.
        rng: Генератор случайных чисел numpy.
    Returns:
        np.ndarray: Массив биомов int8 формы (rows, cols).
    """
    b = np.full(heights.shape, 2, dtype=np.int8)
    b[heights < 0.25] = 1
    b[(heights > 0.5) & (heights <= 0.7)] = 3
    b[heights > 0.7] = 4
    land = b != 1
    forest = (
        land
        & (moisture > 0.55)
        & (temperature > 0.35)
        & (heights <= 0.7)
    )
    b[forest & (rng.random(heights.shape) < 0.7)] = 5
    swamp = land & (heights < 0.33) & (moisture > 0.65)
    b[swamp] = 7
    desert = (
        land
        & (moisture < 0.3)
        & (temperature > 0.6)
        & (heights <= 0.5)
    )
    b[desert] = 6
    tundra = land & (temperature < 0.3) & (heights <= 0.5)
    b[tundra] = 8
    b[rivers & land] = 1
    rural = (
        ((b == 2) | (b == 5))
        & (settlement > 0.6)
        & (temperature > 0.3)
        & (moisture > 0.3)
    )
    b[rural] = 10
    city = (
        (b == 2)
        & (settlement > 0.72)
        & (temperature > 0.35)
        & (moisture > 0.35)
    )
    b[city] = 9
    return b


MAPS = {
    "valley_01": {"seed": 42},
    "ridge_02": {"seed": 77},
    "river_03": {"seed": 13},
}


def main():
    """
    Генерирует все карты из словаря MAPS и сохраняет их
    в scenarios/maps/<name>.npz. Выводит сводку по биомам
    для каждой карты.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, cfg in MAPS.items():
        rng = np.random.default_rng(cfg["seed"])
        heights = fractal_noise(rng, ROWS, COLS)
        moisture = fractal_noise(rng, ROWS, COLS, start_cell=32)
        river_noise = fractal_noise(rng, ROWS, COLS, min_cell=8)
        settlement = fractal_noise(rng, ROWS, COLS, start_cell=32, min_cell=8)
        lat = np.broadcast_to(
            np.linspace(0.0, 1.0, ROWS)[:, None], (ROWS, COLS)
        )
        temperature = 0.65 * lat + 0.35 * fractal_noise(rng, ROWS, COLS)
        temperature = (
            (temperature - temperature.min())
            / (temperature.max() - temperature.min())
        )
        rivers = rivers_from(river_noise, heights)
        biomes = biomes_from(
            heights, moisture, temperature, settlement, rivers, rng
        )
        np.savez_compressed(
            OUT_DIR / f"{name}.npz",
            heights=heights.astype(np.float32),
            biomes=biomes,
        )
        counts = {
            int(k): int((biomes == k).sum())
            for k in np.unique(biomes)
        }
        print(
            f"[MAPGEN] {name}.npz {ROWS}x{COLS} "
            f"({KM_PER_CELL} км/клетка) biomes={counts}"
        )


if __name__ == "__main__":
    main()