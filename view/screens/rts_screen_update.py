"""Тик экрана, потери, исход боя и частицы."""

from __future__ import annotations

from .rts_screen_support import (
    MAP_RECT,
    Particle,
    REAL_SECONDS_PER_GAME_MINUTE,
    logger,
    math,
)


class RTSScreenUpdateMixin:

    def update(self, dt):
        self._prune_selection()
        self._feedback_timer = max(0.0, self._feedback_timer - dt)
        self._sync_render_positions(dt)
        self._update_display_positions(dt)
        self._particles = [p for p in self._particles if p.update(dt)]
        if self.paused or self.finished:
            return
        ts = getattr(self.app, "time_system", None)
        if ts is None:
            return
        if ts.pending_mandatory_scene is not None:
            return
        interval = REAL_SECONDS_PER_GAME_MINUTE / max(1, self.speed)
        self._tick_accum += dt
        guard = 0
        while self._tick_accum >= interval and guard < 240:
            guard += 1
            self._tick_accum -= interval
            before_turn = self.state.sim.turn
            ts.advance(60)
            if self.state.sim.turn != before_turn:
                self._after_tick()
            if (
                ts.pending_mandatory_scene is not None
                or self.state.sim.finished
                or self.app.pending_storyline_outcome
            ):
                break

    def _after_tick(self):
        if self.state.sim.finished:
            self.finished = True
            self.paused = True
            self._feedback("Операция завершена", 4.0)
            self._trigger_battle_outcome()
        elif hasattr(self.app, "check_storyline_end_of_day"):

            self.app.check_storyline_end_of_day()
        self._spawn_battle_particles()
        if self.state.tick_events:
            self._feedback(self.state.tick_events[-1].get("message", ""), 3.0)
        if not self.state.sim.finished:
            self._report_loss_status()

    def _report_loss_status(self):
        loss = self.state.division_loss_percent()
        limit = self._loss_limit_percent()
        milestone = (int(loss) // 5) * 5
        if milestone > self._last_loss_milestone:
            self._last_loss_milestone = milestone
            logger.info(
                "Потери дивизии: %.1f%% (порог поражения %d%%)", loss, limit
            )
        if limit <= 0:
            return
        ratio = loss / float(limit)
        if ratio >= 0.5 and not self._loss_warned_50:
            self._loss_warned_50 = True
            self._feedback(
                "Потери дивизии: %.1f%% из %d%% — берегите людей"
                % (loss, limit),
                4.0,
            )
        if ratio >= 0.75 and not self._loss_warned_75:
            self._loss_warned_75 = True
            self._feedback(
                "КРИТИЧНО: потери %.1f%% из %d%% до поражения" % (loss, limit),
                5.0,
            )

    def _trigger_battle_outcome(self):
        if getattr(self.app, "storyline_interpreter", None) is None:
            return
        winner = getattr(self.state.sim, "winner", None)
        player_side = getattr(self.state, "player_side", "red")
        outcome = "win" if winner == player_side else "lose"
        if hasattr(self.app, "finish_storyline_outcome"):
            self.app.finish_storyline_outcome(outcome)
        else:
            self.app.pending_storyline_outcome = outcome

    def _spawn_battle_particles(self):
        for pair in getattr(self.engine, "engagements", []):
            a = next(
                (
                    d
                    for d in self.state.units
                    if d.name == pair.get("attacker")
                ),
                None,
            )
            b = next(
                (
                    d
                    for d in self.state.units
                    if d.name == pair.get("defender")
                ),
                None,
            )
            if a is None or b is None:
                continue
            pa = self._display_pos.get(a.name) or self._render_pos.get(a.name)
            pb = self._display_pos.get(b.name) or self._render_pos.get(b.name)
            if pa is None or pb is None:
                continue
            distance = abs(a.position[0] - b.position[0]) + abs(
                a.position[1] - b.position[1]
            )
            angle = math.atan2(pb[1] - pa[1], pb[0] - pa[0])
            if distance <= 2:
                self._particles.append(
                    Particle(
                        "melee",
                        pb[0] - 4,
                        pb[1] - 6,
                        life=0.30,
                        color=(255, 230, 170),
                        size=3,
                        angle=angle - 0.8,
                    )
                )
                self._particles.append(
                    Particle(
                        "melee",
                        pb[0] + 4,
                        pb[1] + 2,
                        life=0.24,
                        color=(255, 190, 120),
                        size=2,
                        angle=angle + 1.0,
                    )
                )
                for _ in range(4):
                    self._particles.append(
                        Particle(
                            "spark",
                            pb[0],
                            pb[1] - 4,
                            life=self._rng.uniform(0.25, 0.55),
                            color=(255, 210, 120),
                            size=self._rng.randint(2, 4),
                            vx=self._rng.uniform(-70, 70),
                            vy=self._rng.uniform(-90, -20),
                        )
                    )
            else:
                self._particles.append(
                    Particle(
                        "muzzle",
                        pa[0],
                        pa[1] - 6,
                        life=0.18,
                        color=(255, 220, 130),
                        size=2,
                        angle=angle,
                    )
                )
                for _ in range(2):
                    self._particles.append(
                        Particle(
                            "tracer",
                            pa[0],
                            pa[1] - 6,
                            pb[0],
                            pb[1] - 4,
                            life=self._rng.uniform(0.22, 0.38),
                            color=(255, 220, 140),
                            size=2,
                        )
                    )
                self._particles.append(
                    Particle(
                        "spark",
                        pb[0],
                        pb[1] - 4,
                        life=0.3,
                        color=(255, 170, 90),
                        size=3,
                    )
                )

    def _combat_interval_real(self):
        ts = getattr(self.app, "time_system", None)
        game_seconds = (
            getattr(ts, "combat_tick_seconds", 300) if ts is not None else 300
        )
        game_minutes = float(game_seconds) / 60.0
        return max(
            0.12,
            REAL_SECONDS_PER_GAME_MINUTE
            * game_minutes
            / max(1, int(self.speed)),
        )

    def _sync_render_positions(self, dt=0.0, snap=False):
        duration = self._combat_interval_real()
        for det in self.state.units:
            target = self._project(det.position)
            current = self._render_pos.get(det.name)
            if snap or current is None:
                self._render_pos[det.name] = target
                self._render_anim[det.name] = {
                    "from": target,
                    "to": target,
                    "elapsed": duration,
                    "duration": duration,
                }
                self._moving[det.name] = False
                continue
            anim = self._render_anim.get(det.name)
            if anim is None:
                anim = {
                    "from": current,
                    "to": current,
                    "elapsed": duration,
                    "duration": duration,
                }
            if (
                abs(target[0] - anim["to"][0]) > 0.5
                or abs(target[1] - anim["to"][1]) > 0.5
            ):

                anim = {
                    "from": current,
                    "to": target,
                    "elapsed": 0.0,
                    "duration": duration,
                }
                self._render_anim[det.name] = anim
            else:
                anim["elapsed"] = min(
                    anim["duration"], anim["elapsed"] + max(0.0, dt)
                )
            progress = min(1.0, anim["elapsed"] / max(0.001, anim["duration"]))
            self._render_pos[det.name] = (
                anim["from"][0] + (target[0] - anim["from"][0]) * progress,
                anim["from"][1] + (target[1] - anim["from"][1]) * progress,
            )
            anim["to"] = target

            self._moving[det.name] = (
                anim["elapsed"] < anim["duration"] - 1e-4
                and math.dist(anim["from"], anim["to"]) > 0.5
            )

    def _update_display_positions(self, dt=0.0):
        entries = []
        follow = 0.0
        if dt > 0.0:
            follow = 1.0 - math.exp(-max(0.0, float(dt)) * 20.0)
        for i, det in enumerate(self.state.units):
            if getattr(det, "broken", False):
                continue
            p = self._render_pos.get(det.name)
            if p is None:
                continue
            moving = bool(self._moving.get(det.name, False))
            previous = self._display_pos.get(det.name)
            if previous is not None and dt > 0.0:
                if moving:

                    x = previous[0] + (float(p[0]) - previous[0]) * follow
                    y = previous[1] + (float(p[1]) - previous[1]) * follow
                else:
                    x, y = float(previous[0]), float(previous[1])
            else:
                x, y = float(p[0]), float(p[1])
            entries.append([det.name, x, y, i, moving])

        min_dist = 30.0
        left = MAP_RECT.left + 18
        right = MAP_RECT.right - 18
        top = MAP_RECT.top + 38

        bottom = min(MAP_RECT.bottom - 24, 598)

        def clamp(item):
            item[1] = max(left, min(right, item[1]))
            item[2] = max(top, min(bottom, item[2]))

        for item in entries:
            clamp(item)
        for _ in range(14):
            moved = False
            for a in range(len(entries)):
                for b in range(a + 1, len(entries)):
                    ax, ay = entries[a][1], entries[a][2]
                    bx, by = entries[b][1], entries[b][2]
                    dx, dy = bx - ax, by - ay
                    distance = math.hypot(dx, dy)
                    if distance >= min_dist:
                        continue
                    if distance < 0.01:
                        angle = (entries[a][3] * 2.399) % math.tau
                        dx, dy = math.cos(angle), math.sin(angle)
                        distance = 1.0
                    overlap = min_dist - distance
                    ux, uy = dx / distance, dy / distance
                    a_moving = entries[a][4]
                    b_moving = entries[b][4]
                    if a_moving and b_moving:
                        wa, wb = 0.5, 0.5
                    elif a_moving:
                        wa, wb = 1.0, 0.0
                    elif b_moving:
                        wa, wb = 0.0, 1.0
                    else:

                        if dt > 0.0:
                            continue
                        wa, wb = 0.5, 0.5
                    entries[a][1] -= ux * overlap * wa
                    entries[a][2] -= uy * overlap * wa
                    entries[b][1] += ux * overlap * wb
                    entries[b][2] += uy * overlap * wb
                    clamp(entries[a])
                    clamp(entries[b])
                    moved = True
            if not moved:
                break
        if dt > 0.0:

            smooth = 1.0 - math.exp(-max(0.0, float(dt)) * 12.0)
            for item in entries:
                previous = self._display_pos.get(item[0])
                if previous is None:
                    continue
                item[1] = previous[0] + (item[1] - previous[0]) * smooth
                item[2] = previous[1] + (item[2] - previous[1]) * smooth
        self._display_pos = {
            name: (x, y) for name, x, y, _idx, _moving in entries
        }
