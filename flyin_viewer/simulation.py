"""Turn-based drone simulation compliant with subject rules."""

from __future__ import annotations

import heapq
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from flyin_viewer.parser import Connection, MapData

INF = 10**18


@dataclass
class StepResult:
    """Result data returned after each simulation step."""

    drones_moved: int
    turn_index: int
    movements: list[str] = field(default_factory=list)


class SimulationError(RuntimeError):
    """Raised when simulation cannot be initialized correctly."""

    pass


@dataclass
class DroneState:
    """Single drone state, including in-flight restricted transitions."""

    zone: str
    last_zone: str | None = None
    in_flight_to: str | None = None
    in_flight_from: str | None = None
    remaining_turns: int = 0


class DroneSimulation:
    """Route drones start-to-end respecting capacities and movement costs."""

    def __init__(self, map_data: MapData) -> None:
        self._map = map_data
        self._goal = self._single_hub_of_kind(map_data, "end")
        self._start = self._single_hub_of_kind(map_data, "start")
        self._adj = self._build_adjacency(map_data)
        self._link_cap: dict[frozenset[str], int] = {
            frozenset({c.a, c.b}): c.max_link_capacity
            for c in map_data.connections
        }
        self._conn_by_pair: dict[frozenset[str], Connection] = {
            frozenset({c.a, c.b}): c for c in map_data.connections
        }
        self.dist: dict[str, int] = self._dijkstra_from_goal(map_data)
        self.turn_index = 0
        self.positions: list[str] = []
        self.states: list[DroneState] = []
        self._stagnation = 0
        self.unreachable_goal: bool = False
        self.reset()

    @staticmethod
    def _single_hub_of_kind(map_data: MapData, kind: str) -> str:
        names = [h.name for h in map_data.hubs.values() if h.kind == kind]
        if len(names) != 1:
            raise SimulationError(
                f"Exactly one '{kind}' hub is required (found {names!r})"
            )
        return names[0]

    @staticmethod
    def _hub_max_drones(md: MapData, hub_name: str) -> int:
        return md.hubs[hub_name].max_drones

    def _dijkstra_from_goal(self, md: MapData) -> dict[str, int]:
        """Compute weighted shortest distance-to-goal heuristic."""
        goal = self._goal
        dist: dict[str, int] = {goal: 0}
        pq: list[tuple[int, str]] = [(0, goal)]
        while pq:
            d, u = heapq.heappop(pq)
            if d != dist.get(u, INF):
                continue
            for v in self._adj[u]:
                if md.hubs[v].zone == "blocked" and v != goal:
                    continue
                w = 2 if md.hubs[v].zone == "restricted" else 1
                nd = d + w
                if nd < dist.get(v, INF):
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        return dist

    def _ordered_next_hops(self, u: str, last_zone: str | None) -> list[str]:
        """Return candidate neighbors sorted by score."""
        md = self._map
        if self.dist.get(u, INF) >= INF:
            return []
        options: list[tuple[tuple[int, int, int, str], str]] = []

        for v in self._adj[u]:
            hv = md.hubs[v]
            if hv.zone == "blocked" and v != self._goal:
                continue
            dv = self.dist.get(v, INF)
            if dv >= INF:
                continue
            back_penalty = 1 if last_zone is not None and v == last_zone else 0
            priority_penalty = 0 if hv.zone == "priority" else 1
            options.append(((dv, back_penalty, priority_penalty, v), v))

        options.sort(key=lambda x: x[0])
        return [v for _, v in options]

    @staticmethod
    def _build_adjacency(md: MapData) -> dict[str, list[str]]:
        """Build sorted adjacency lists from map connections."""
        adj: dict[str, list[str]] = defaultdict(list)
        for c in md.connections:
            adj[c.a].append(c.b)
            adj[c.b].append(c.a)
        for nodes in adj.values():
            nodes.sort()
        return dict(adj)

    def reset(self) -> None:
        """Reset simulation to initial drone positions at start hub."""
        md = self._map
        self.turn_index = 0
        self.positions = [self._start] * md.nb_drones
        self.states = [
            DroneState(zone=self._start) for _ in range(md.nb_drones)
        ]
        self._stagnation = 0
        self.unreachable_goal = md.nb_drones > 0 and (
            self.dist.get(self._start, INF) >= INF
        )

    def all_at_goal(self) -> bool:
        return all(
            s.zone == self._goal and s.in_flight_to is None
            for s in self.states
        )

    def stagnant(self, max_turns_without_move: int = 50) -> bool:
        """Return True when no drone has moved for too long."""

        return (
            not self.all_at_goal()
        ) and self._stagnation >= max_turns_without_move

    def goal_name(self) -> str:
        return self._goal

    def start_name(self) -> str:
        return self._start

    def step(self) -> StepResult:
        """Run one simulation turn and return movement output tokens."""
        if self.all_at_goal():
            return StepResult(0, self.turn_index)

        md = self._map
        snap = [DroneState(**vars(s)) for s in self.states]
        planned: Counter[str] = Counter(
            s.zone
            for s in snap
            if s.in_flight_to is None and s.zone != self._goal
        )
        edge_use: dict[frozenset[str], int] = defaultdict(int)
        new_states = [DroneState(**vars(s)) for s in snap]
        drones_moved = 0
        movement_tokens: list[str] = []

        for drone_id in range(md.nb_drones):
            state = snap[drone_id]
            if state.in_flight_to is None:
                continue
            ek = frozenset({state.in_flight_from or "", state.in_flight_to})
            edge_use[ek] += 1

        occupied_targets: Counter[str] = Counter(
            s.in_flight_to for s in snap if s.in_flight_to is not None
        )

        for drone_id in range(md.nb_drones):
            state = snap[drone_id]
            token_prefix = f"D{drone_id + 1}-"

            if state.zone == self._goal and state.in_flight_to is None:
                continue

            if state.in_flight_to is not None:
                dest = state.in_flight_to
                if state.remaining_turns <= 1:
                    occupied_targets[dest] -= 1
                    new_states[drone_id] = DroneState(
                        zone=dest,
                        last_zone=state.in_flight_from,
                    )
                    if dest != self._goal:
                        planned[dest] += 1
                    drones_moved += 1
                    movement_tokens.append(f"{token_prefix}{dest}")
                else:
                    new_states[drone_id].remaining_turns -= 1
                    conn = self._conn_by_pair[
                        frozenset({state.in_flight_from or "", dest})
                    ]
                    movement_tokens.append(f"{token_prefix}{conn.name}")
                continue

            u = state.zone
            moved = False
            for v in self._ordered_next_hops(u, state.last_zone):
                ek = frozenset({u, v})
                cap_el = self._link_cap[ek]
                if edge_use[ek] + 1 > cap_el:
                    continue
                if planned[u] < 1:
                    break

                edge_use[ek] += 1
                planned[u] -= 1

                step_cost = 2 if md.hubs[v].zone == "restricted" else 1
                if step_cost == 1:
                    max_v = self._hub_max_drones(md, v)
                    if (
                        v != self._goal
                        and planned[v] + occupied_targets[v] + 1 > max_v
                    ):
                        planned[u] += 1
                        edge_use[ek] -= 1
                        continue
                    if v != self._goal:
                        planned[v] += 1
                    new_states[drone_id] = DroneState(zone=v, last_zone=u)
                    movement_tokens.append(f"{token_prefix}{v}")
                else:
                    max_v = self._hub_max_drones(md, v)
                    if (
                        v != self._goal
                        and planned.get(v, 0) + occupied_targets[v] + 1 > max_v
                    ):
                        planned[u] += 1
                        edge_use[ek] -= 1
                        continue
                    occupied_targets[v] += 1
                    new_states[drone_id] = DroneState(
                        zone=u,
                        last_zone=state.last_zone,
                        in_flight_to=v,
                        in_flight_from=u,
                        remaining_turns=1,
                    )
                    conn = self._conn_by_pair[ek]
                    movement_tokens.append(f"{token_prefix}{conn.name}")
                drones_moved += 1
                moved = True
                break
            if not moved:
                continue

        moved_any = drones_moved > 0
        self.states = new_states
        self.positions = [
            s.in_flight_to if s.in_flight_to is not None else s.zone
            for s in new_states
        ]

        self.turn_index += 1

        if moved_any:
            self._stagnation = 0
        elif not self.all_at_goal():
            self._stagnation += 1

        return StepResult(
            drones_moved, self.turn_index, movements=movement_tokens
        )
