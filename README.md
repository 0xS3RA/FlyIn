*This project has been created as part of the 42 curriculum by <vvan-ach>*

# Fly-in

## Description

Fly-in is a Python project that routes multiple drones from a unique start hub to a unique end hub on a graph of connected zones.  
The objective is to minimize the number of simulation turns while respecting all mandatory movement rules:

- zone capacities (`max_drones`)
- connection capacities (`max_link_capacity`)
- zone movement costs (`normal=1`, `priority=1`, `restricted=2`, `blocked=inaccessible`)
- simultaneous movement constraints and deadlock prevention

The repository includes:

- a strict parser for map files
- a simulation engine with turn-by-turn scheduling
- mandatory terminal output format (`D<ID>-<zone>` / `D<ID>-<connection>`)
- a graphical representation (PySide6 viewer)

## Instructions

### Installation

```bash
make install
```

### Run terminal simulation (mandatory format)

```bash
python3 -m flyin_viewer maps/easy/01_linear_path.txt
```

### Run graphical viewer

```bash
python3 -m flyin_viewer --gui --maps-root maps
```

### Debug

```bash
make debug
```

### Linting / Type-checking

```bash
make lint
# Optional stricter checks
make lint-strict
```

## Algorithm Choices

The routing strategy combines weighted shortest-path guidance with per-turn capacity-aware scheduling:

1. **Distance precomputation (Dijkstra)**  
   Distances are computed from the end hub using destination-entry costs:
   - `restricted`: +2
   - other reachable zones: +1
   - `blocked`: excluded (except if it is the unique end hub)

2. **Greedy next-hop selection per drone**  
   At each turn, each drone selects an adjacent hub that strictly improves its weighted distance to goal.  
   Ties are resolved by:
   - preferring `priority` zones
   - then lexical order of zone names

3. **Conflict-free scheduling**  
   The scheduler enforces:
   - zone occupancy (`max_drones`)
   - connection occupancy (`max_link_capacity`)
   - start/end special occupancy rules
   - simultaneous movement with turn snapshot semantics

4. **Restricted movement transit state**  
   Entering a `restricted` destination creates a two-turn move:
   - turn 1: drone is in-flight and output uses `D<ID>-<connection>`
   - turn 2: drone must arrive at destination, no waiting allowed in connection

### Complexity

- Precomputation: `O((V + E) log V)`
- Per turn scheduling: `O(D * deg)` where:
  - `D` = number of drones
  - `deg` = average hub degree
- Memory: `O(V + E + D)`

## Visual Representation

The GUI (`--gui`) displays:

- colored hubs (`color=` metadata)
- zone accents (`restricted`, `priority`, `blocked`)
- connection style and labels for `max_link_capacity`
- live drone positions and animated transitions

This representation helps validate map topology, congestion points, and movement behavior quickly.

## Resources

- [Python typing docs](https://docs.python.org/3/library/typing.html)
- [mypy documentation](https://mypy.readthedocs.io/)
- [flake8 documentation](https://flake8.pycqa.org/)
- [Dijkstra algorithm reference](https://en.wikipedia.org/wiki/Dijkstra%27s_algorithm)
- [PySide6 documentation](https://doc.qt.io/qtforpython/)

### AI Usage

AI assistance was used for:

- extracting and checking mandatory requirements from the subject PDF
- performing a point-by-point compliance audit against parser/simulation behaviorw
- drafting and refining project documentation structure
