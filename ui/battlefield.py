from dataclasses import dataclass, field
import random

import simulation as S

GRID_W, GRID_H = 11, 9
TILE_W, TILE_H = 68, 34
MOVE_RANGE = 2
START_CP = 4
MAX_CP = 9


ATTACK = "ATTACK"
ATTACK_ORDERS = (ATTACK,)
ORDERS = ATTACK_ORDERS + ("REST", "HOLD")


def clamp(value, low, high):
    return max(low, min(high, value))


def in_bounds(col, row, cols=GRID_W, rows=GRID_H):
    return 0 <= col < cols and 0 <= row < rows


def grid_to_screen(col, row, origin=(0, 0), tile_w=TILE_W, tile_h=TILE_H):
    ox, oy = origin
    return (ox + (col - row) * tile_w / 2.0, oy + (col + row) * tile_h / 2.0)


def screen_to_grid(
    x, y, origin=(0, 0), tile_w=TILE_W, tile_h=TILE_H, cols=GRID_W, rows=GRID_H
):
    ox, oy = origin
    a = (x - ox) / (tile_w / 2.0)
    b = (y - oy) / (tile_h / 2.0)
    col = int(round((a + b) / 2.0))
    row = int(round((b - a) / 2.0))
    return (col, row) if in_bounds(col, row, cols, rows) else None


def chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def adjacent(a, b):
    return chebyshev(a, b) <= 1


def step_toward(start, target):
    best = start
    best_d = chebyshev(start, target)
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if dc == 0 and dr == 0:
                continue
            cand = (start[0] + dc, start[1] + dr)
            if not in_bounds(*cand):
                continue
            d = chebyshev(cand, target)
            if d < best_d:
                best, best_d = cand, d
    return best


@dataclass
class Commander:

    name: str
    side: str
    profile: str = "CANON"
    portrait: str = "commander"
    morale: int = 70
    stance: str = "balanced"
    ai: bool = False
    agent: S.Agent = field(init=False, repr=False)

    def __post_init__(self):
        self.agent = (
            S.UtilityAI(profile=self.profile)
            if self.ai
            else S.Agent(profile=self.profile)
        )

    @property
    def force(self):
        return self.agent.force

    @property
    def energy(self):
        return self.agent.energy_pool

    @property
    def ceiling(self):
        return max(1.0, self.agent.rest_ceiling)

    @property
    def force_ratio(self):
        return self.force / self.ceiling

    def set_profile(self, profile):
        if profile not in S.PROFILES:
            return
        self.profile = profile
        self.agent.set_profile(profile)

    def intention(self):
        return self.agent.form_intention() if self.ai else ("REST", 0)


@dataclass
class Unit:
    uid: str
    name: str
    side: str
    col: int
    row: int
    role: str
    commander: Commander
    portrait: str = "unit"

    @property
    def pos(self):
        return (self.col, self.row)


@dataclass(frozen=True)
class Choice:
    label: tuple
    effect: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Dialogue:
    key: str
    speaker: tuple
    text: tuple
    choices: tuple


DIALOGUES = {
    "intro": Dialogue(
        "intro",
        ("Советник", "Advisor"),
        (
            "Командир, фронт держится на двух метриках: силе и энергии. "
            "Выберите, как начать бой — от этого зависит и приказ, и доверие "
            "людей.",
            "Commander, the front rests on two metrics: force and energy. "
            "Choose how to open the battle - it shapes both the order and the "
            "trust of your people.",
        ),
        (
            Choice(
                ("Ударить в лоб", "Strike head-on"),
                {
                    "cp": 1,
                    "profile": "ZEALOT",
                    "morale": 4,
                    "trait": ("Дерзость", "Audacity"),
                    "log": (
                        "Вы выбрали дерзкий напор.",
                        "You chose audacity.",
                    ),
                },
            ),
            Choice(
                ("Держать строй", "Hold the line"),
                {
                    "morale": 10,
                    "profile": "ORTHODOX",
                    "trait": ("Дисциплина", "Discipline"),
                    "log": ("Вы выбрали дисциплину.", "You chose discipline."),
                },
            ),
            Choice(
                ("Играть от манёвра", "Play for manoeuvre"),
                {
                    "cp": 2,
                    "profile": "CANON",
                    "trait": ("Расчёт", "Calculation"),
                    "log": ("Вы выбрали расчёт.", "You chose calculation."),
                },
            ),
        ),
    ),
    "first_blood": Dialogue(
        "first_blood",
        ("Советник", "Advisor"),
        (
            "Первый контакт состоялся. Противник раскрывает вход, но и наш "
            "пул "
            "тает. Давить или перевести дыхание?",
            "First contact is made. The enemy opens up, but our pool is "
            "draining. "
            "Press or catch our breath?",
        ),
        (
            Choice(
                ("Давить, пока окно открыто", "Press while it is open"),
                {
                    "cp": 1,
                    "morale": 5,
                    "log": ("Вы продолжили давление.", "You kept pressing."),
                },
            ),
            Choice(
                ("Перевести дыхание", "Catch a breath"),
                {
                    "morale": 8,
                    "cp": 1,
                    "log": (
                        "Вы дали людям передышку.",
                        "You gave the troops a breather.",
                    ),
                },
            ),
            Choice(
                ("Сменить тип давления", "Switch the pressure type"),
                {
                    "cp": 2,
                    "stance": "balanced",
                    "log": (
                        "Вы сменили тип давления.",
                        "You switched pressure.",
                    ),
                },
            ),
        ),
    ),
    "objective": Dialogue(
        "objective",
        ("Советник", "Advisor"),
        (
            "Высота занята. Это не победа, но окно конъюнктуры теперь "
            "работает "
            "на нас. Удержим её?",
            "The height is taken. It is not victory, but the conjuncture now "
            "works for us. Do we hold it?",
        ),
        (
            Choice(
                ("Удерживать высоту", "Hold the height"),
                {
                    "cp": 1,
                    "morale": 6,
                    "log": (
                        "Вы приказали удерживать высоту.",
                        "You ordered the height held.",
                    ),
                },
            ),
            Choice(
                ("Оставить заслон и давить", "Leave a screen and press"),
                {
                    "cp": 2,
                    "morale": 2,
                    "log": (
                        "Вы оставили заслон.",
                        "You left a screening force.",
                    ),
                },
            ),
        ),
    ),
    "low_force": Dialogue(
        "low_force",
        ("Советник", "Advisor"),
        (
            "Сила у нижней трети потолка. Ещё один неверный шаг — и вход "
            "надорвётся. Отойти или стоять до конца?",
            "Force is in the lower third of the ceiling. One more wrong step "
            "and "
            "the input tears. Withdraw or stand to the end?",
        ),
        (
            Choice(
                ("Отойти и закрыть вход", "Withdraw and close the input"),
                {
                    "morale": 10,
                    "cp": 1,
                    "profile": "ORTHODOX",
                    "log": ("Вы выбрали отход.", "You chose to withdraw."),
                },
            ),
            Choice(
                ("Стоять до конца", "Stand to the end"),
                {
                    "morale": 5,
                    "profile": "ZEALOT",
                    "trait": ("Упорство", "Tenacity"),
                    "log": (
                        "Вы решили стоять до конца.",
                        "You chose to stand to the end.",
                    ),
                },
            ),
        ),
    ),
    "victory": Dialogue(
        "victory",
        ("Советник", "Advisor"),
        (
            "Противник потерял устойчивое доминирование. Поле наше. Что "
            "скажем "
            "людям?",
            "The enemy has lost sustained dominance. The field is ours. What "
            "do "
            "we tell the troops?",
        ),
        (
            Choice(
                ("Это была дисциплина", "It was discipline"),
                {
                    "morale": 10,
                    "profile": "ORTHODOX",
                    "log": (
                        "Победа приписана дисциплине.",
                        "Victory was attributed to discipline.",
                    ),
                },
            ),
            Choice(
                ("Это была дерзость", "It was audacity"),
                {
                    "morale": 6,
                    "profile": "ZEALOT",
                    "log": (
                        "Победа приписана дерзости.",
                        "Victory was attributed to audacity.",
                    ),
                },
            ),
        ),
    ),
    "defeat": Dialogue(
        "defeat",
        ("Советник", "Advisor"),
        (
            "Доминирование потеряно. Мы отступаем, но не исчезаем: сила не "
            "опускается ниже единицы. Что сохраним для следующего боя?",
            "Dominance is lost. We retreat, but do not vanish: force never "
            "falls "
            "below one. What do we keep for the next battle?",
        ),
        (
            Choice(
                ("Сохранить дисциплину", "Keep discipline"),
                {
                    "morale": 8,
                    "profile": "ORTHODOX",
                    "log": (
                        "Вы сохранили дисциплину.",
                        "You kept discipline.",
                    ),
                },
            ),
            Choice(
                ("Сохранить дерзость", "Keep audacity"),
                {
                    "morale": 4,
                    "profile": "ZEALOT",
                    "log": ("Вы сохранили дерзость.", "You kept audacity."),
                },
            ),
        ),
    ),
}


class RoleplayState:

    def __init__(self, model):
        self.model = model
        self.queue = []
        self.active = None
        self.history = []
        self.traits = []
        self.reputation = 0
        self.shown = set()

    def enqueue(self, key):
        if key in self.shown or key not in DIALOGUES:
            return False
        self.shown.add(key)
        self.queue.append(key)
        return True

    def next(self):
        if self.active is None and self.queue:
            self.active = self.queue.pop(0)
        return self.active

    def choose(self, index):
        if self.active is None:
            return None
        dialogue = DIALOGUES[self.active]
        if not (0 <= index < len(dialogue.choices)):
            return None
        choice = dialogue.choices[index]
        self._apply(choice.effect)
        self.history.append((self.active, index, choice.label))
        self.active = None
        self.next()
        return choice

    def _apply(self, effect):
        m = self.model
        if "cp" in effect:
            m.command_points = clamp(
                m.command_points + effect["cp"], 0, m.max_command_points
            )
        if "morale" in effect:
            m.player.morale = clamp(m.player.morale + effect["morale"], 0, 100)
        if "profile" in effect:
            m.player.set_profile(effect["profile"])
        if "stance" in effect:
            m.player.stance = effect["stance"]
        if "trait" in effect and effect["trait"] not in self.traits:
            self.traits.append(effect["trait"])
        if "reputation" in effect:
            self.reputation += int(effect["reputation"])
        if "log" in effect:
            m._log(*effect["log"])


class BattlefieldModel:

    def __init__(
        self,
        seed=0,
        player_profile="CANON",
        enemy_profile="CANON",
        with_env=True,
    ):
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.player = Commander(
            "Капитан", "player", player_profile, portrait="portrait_player"
        )
        self.enemy = Commander(
            "Визави",
            "enemy",
            enemy_profile,
            portrait="portrait_enemy",
            ai=True,
        )
        self.units = {
            "player": Unit(
                "player", "Авангард", "player", 3, 5, "vanguard", self.player
            ),
            "enemy": Unit(
                "enemy", "Тень", "enemy", 7, 3, "vanguard", self.enemy
            ),
        }
        self.selected = "player"
        self.objective = (5, 4)
        self._objective_owner = None
        self.command_points = START_CP
        self.max_command_points = MAX_CP
        self.turn = 1
        self.phase = "deployment"
        self.winner = None
        self.winner_side = None
        self.dom_player = 0
        self.dom_enemy = 0
        self.env = S.Environment() if with_env else None
        self.log = []
        self.roleplay = RoleplayState(self)
        self._attack_used = False
        self._low_force_seen = False
        self._message = ("", "")
        self._enemy_rest = False
        self._log(
            "Развёртывание: займите высоту или вынудите противника "
            "раскрыть вход.",
            "Deployment: take the height or force the enemy to open up.",
        )
        self.roleplay.enqueue("intro")
        self.roleplay.next()

    @property
    def selected_unit(self):
        return self.units[self.selected]

    @property
    def player_unit(self):
        return self.units["player"]

    @property
    def enemy_unit(self):
        return self.units["enemy"]

    @property
    def contact(self):
        return adjacent(self.player_unit.pos, self.enemy_unit.pos)

    @property
    def objective_owner(self):
        if self.player_unit.pos == self.objective:
            return "player"
        if self.enemy_unit.pos == self.objective:
            return "enemy"
        return None

    def unit_at(self, col, row):
        for uid, unit in self.units.items():
            if unit.pos == (col, row):
                return uid
        return None

    def move_targets(self, uid=None):
        uid = uid or self.selected
        unit = self.units[uid]
        out = []
        for col in range(GRID_W):
            for row in range(GRID_H):
                if (col, row) == unit.pos:
                    continue
                if chebyshev((col, row), unit.pos) > MOVE_RANGE:
                    continue
                if self.unit_at(col, row) is not None:
                    continue
                out.append((col, row))
        return out

    def move_unit(self, uid, col, row):
        if self.winner:
            return False, "Партия окончена.", "The match is over."
        if uid != "player":
            return False, "Это не ваш юнит.", "That is not your unit."
        if not in_bounds(col, row):
            return False, "Клетка вне поля.", "The tile is outside the field."
        unit = self.units[uid]
        if (col, row) == unit.pos:
            return False, "Юнит уже здесь.", "The unit is already here."
        if self.unit_at(col, row) is not None:
            return False, "Клетка занята.", "The tile is occupied."
        if chebyshev((col, row), unit.pos) > MOVE_RANGE:
            return (
                False,
                "Слишком далеко: ход до %d клеток." % MOVE_RANGE,
                "Too far: move range is %d." % MOVE_RANGE,
            )
        if self.command_points < 1:
            return False, "Нет очков команд.", "No command points."
        unit.col, unit.row = col, row
        self.command_points -= 1
        self.phase = "battle" if self.contact else "manoeuvre"
        self._update_objective()
        self._log(
            "Авангард выдвинулся на %s." % ((col, row),),
            "The vanguard moved to %s." % ((col, row),),
        )
        self._after_player_action("MOVE", duel=False)
        return True, "Приказ выполнен.", "Order executed."

    def issue_order(self, order):
        if self.winner:
            return False, "Партия окончена.", "The match is over."
        if order not in ORDERS:
            return False, "Неизвестный приказ.", "Unknown order."
        if order in ATTACK_ORDERS and not self.contact:
            return (
                False,
                "Нет контакта: сначала сблизьтесь.",
                "No contact: close the distance first.",
            )
        if order in ATTACK_ORDERS and self.command_points < 1:
            return False, "Нет очков команд.", "No command points."

        if order in ATTACK_ORDERS:
            self.command_points -= 1
            self._duel(order, 0.7, order, finish=True)
        elif order == "REST":
            if self.contact:
                self._duel("REST", 0.0, "REST", finish=True)
            else:
                self._duel("REST", 0.0, "REST", finish=False, enemy_rest=True)
                self._after_player_action("REST", duel=False)
        elif order == "HOLD":
            if self.contact:
                self._duel(ATTACK, 0.2, "HOLD", finish=True)
            else:
                self._duel("REST", 0.0, "HOLD", finish=False, enemy_rest=True)
                self._after_player_action("HOLD", duel=False)
        return True, "Приказ принят.", "Order accepted."

    def end_turn(self):
        if self.winner:
            return
        if self.contact:
            self._enemy_attack(finish=True)
        else:
            self._enemy_move()
            self._end_turn()

    def _player_intent(self, me, opp, rng):
        act, frac = getattr(self, "_player_act", ("REST", 0.0))
        work = int(me.energy_pool * frac) if frac > 0 else 0
        return act, work

    def _enemy_intent(self, me, opp, rng):
        if self._enemy_rest:
            return "REST", 0
        return self.enemy.intention()

    def _duel(
        self, player_act, player_frac, label, finish=True, enemy_rest=False
    ):
        before_p, before_e = self.player.force, self.enemy.force
        self._player_act = (player_act, player_frac)
        self._enemy_rest = enemy_rest
        S.run_tick(
            self.player.agent,
            self.enemy.agent,
            self._player_intent,
            self._enemy_intent,
            self.rng,
            self.env,
        )
        self._enemy_rest = False
        self._sync_morale(before_p, before_e)
        winner, self.dom_player, self.dom_enemy = S.check_capture(
            self.player.agent,
            self.enemy.agent,
            self.dom_player,
            self.dom_enemy,
        )
        if winner:
            self._set_winner(winner)
            return
        self._log(
            "Контакт: сила %d / %d, пул %d / %d."
            % (
                self.player.force,
                self.enemy.force,
                self.player.energy,
                self.enemy.energy,
            ),
            "Contact: force %d / %d, pool %d / %d."
            % (
                self.player.force,
                self.enemy.force,
                self.player.energy,
                self.enemy.energy,
            ),
        )
        if finish:
            self._after_player_action(label, duel=True)

    def _enemy_attack(self, finish=True):
        self._duel("REST", 0.0, "ENEMY", finish=False)
        if finish and not self.winner:
            self._after_player_action("ENEMY", duel=True)

    def _enemy_move(self):
        if self.winner:
            return
        unit = self.enemy_unit
        target = self.objective
        if self.unit_at(*self.objective) == "player":
            target = self.player_unit.pos
        cand = step_toward(unit.pos, target)
        if cand != unit.pos and self.unit_at(*cand) is None:
            unit.col, unit.row = cand
            self._update_objective()
            self._log(
                "Тень сместилась на %s." % ((cand),),
                "The shadow shifted to %s." % ((cand),),
            )
            if self.contact:
                self.phase = "battle"
                self._log(
                    "Противник вошёл в контакт.", "The enemy made contact."
                )

    def _sync_morale(self, before_p, before_e):
        dp = self.player.force - before_p
        de = self.enemy.force - before_e
        self.player.morale = clamp(
            self.player.morale + (4 if dp >= 0 else -8), 0, 100
        )
        self.enemy.morale = clamp(
            self.enemy.morale + (4 if de >= 0 else -8), 0, 100
        )

    def _after_player_action(self, label, duel):
        if label in ATTACK_ORDERS or label == "HOLD":
            if not self._attack_used:
                self._attack_used = True
                self.roleplay.enqueue("first_blood")
        if self.player.force_ratio < 0.35 and not self._low_force_seen:
            self._low_force_seen = True
            self.roleplay.enqueue("low_force")
        if self.roleplay.active is None:
            self.roleplay.next()
        if not duel and not self.winner:
            if self.contact:
                self._enemy_attack(finish=False)
            else:
                self._enemy_move()
        if not self.winner:
            self._end_turn()

    def _end_turn(self):
        if self.winner:
            return
        self.turn += 1
        bonus = 2 if self.objective_owner == "player" else 1
        self.command_points = clamp(
            self.command_points + bonus, 0, self.max_command_points
        )
        if self.objective_owner == "player":
            self.player.morale = clamp(self.player.morale + 2, 0, 100)
        if self.roleplay.active is None:
            self.roleplay.next()

    def _update_objective(self):
        owner = self.objective_owner
        if owner == self._objective_owner:
            return
        self._objective_owner = owner
        if owner == "player":
            self.roleplay.enqueue("objective")
            if self.roleplay.active is None:
                self.roleplay.next()
            self._log(
                "Высота занята авангардом.",
                "The height is held by the vanguard.",
            )
        elif owner == "enemy":
            self._log("Тень заняла высоту.", "The shadow took the height.")
        else:
            self._log("Высота свободна.", "The height is free.")

    def _set_winner(self, winner):
        self.winner = winner
        self.winner_side = "player" if winner == "RL" else "enemy"
        self.phase = "over"
        self.roleplay.enqueue(
            "victory" if self.winner_side == "player" else "defeat"
        )
        self.roleplay.next()
        self._log(
            "Захват: %s."
            % ("авангард" if self.winner_side == "player" else "тень"),
            "Capture: %s."
            % ("vanguard" if self.winner_side == "player" else "shadow"),
        )

    def _log(self, ru, en):
        self.log.append((self.turn, ru, en))
        if len(self.log) > 80:
            self.log.pop(0)

    def last_log(self, n=5):
        return self.log[-n:]

    def set_message(self, ru, en):
        self._message = (ru, en)

    @property
    def message(self):
        return self._message

    def snapshot(self):
        return {
            "seed": self.seed,
            "turn": self.turn,
            "winner": self.winner,
            "winner_side": self.winner_side,
            "command_points": self.command_points,
            "player": {
                "profile": self.player.profile,
                "morale": self.player.morale,
                "pos": list(self.player_unit.pos),
            },
            "enemy": {
                "profile": self.enemy.profile,
                "morale": self.enemy.morale,
                "pos": list(self.enemy_unit.pos),
            },
            "objective_owner": self.objective_owner,
            "traits": list(self.roleplay.traits),
            "log": list(self.log[-20:]),
        }
