from __future__ import annotations

from pathlib import Path

from flyin_viewer.parser import MapParseError, load_map
from flyin_viewer.simulation import DroneSimulation, SimulationError


def run_cli(map_path: Path) -> int:
    """Run simulation in terminal with mandatory output format."""
    try:
        data = load_map(map_path)
        sim = DroneSimulation(data)
    except (MapParseError, SimulationError) as exc:
        print(f"Error: {exc}")
        return 1

    while not sim.all_at_goal():
        result = sim.step()
        if result.movements:
            print(" ".join(result.movements))
        if result.drones_moved == 0 and not sim.all_at_goal():
            print("Error: simulation is blocked and cannot deliver all drones")
            return 1
    return 0
