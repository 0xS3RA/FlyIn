from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

HubKind = Literal["start", "hub", "end"]
ZoneType = Literal["normal", "restricted", "priority", "blocked"]
_VALID_ZONE_TYPES: set[str] = {"normal", "restricted", "priority", "blocked"}
_HUB_LINE = re.compile(
    r"^\s*(start_hub|hub|end_hub):\s+([^\s\-]+)\s+(-?\d+)\s+(-?\d+)"
    r"(?:\s+\[([^\]]+)\])?\s*$"
)
_CONN_LINE = re.compile(
    r"^\s*connection:\s+([^\s\-]+)-([^\s\-]+)(?:\s+\[([^\]]+)\])?\s*$"
)
_NB_DRONES = re.compile(r"^\s*nb_drones:\s*(\d+)\s*$")


class MapParseError(ValueError):
    """Raised when map file syntax or constraints are invalid."""


@dataclass
class Hub:
    """Map node and metadata."""

    name: str
    kind: HubKind
    x: int
    y: int
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def zone(self) -> ZoneType:
        """Return zone type with default value."""
        raw = self.attrs.get("zone", "normal").lower()
        if raw == "restricted":
            return "restricted"
        if raw == "priority":
            return "priority"
        if raw == "blocked":
            return "blocked"
        return "normal"

    @property
    def max_drones(self) -> int:
        """Return zone capacity, defaulting to 1."""
        if self.kind in {"start", "end"}:
            return 10**18
        return int(self.attrs.get("max_drones", "1"))


@dataclass
class Connection:
    """Bidirectional edge with optional capacity."""

    a: str
    b: str
    max_link_capacity: int = 1

    @property
    def name(self) -> str:
        """Return canonical edge label for output."""
        return f"{self.a}-{self.b}"


@dataclass
class MapData:
    """Parsed map container."""

    path: Path
    nb_drones: int
    hubs: dict[str, Hub]
    connections: list[Connection]


def _parse_brackets(
    raw: str | None, *, path: Path, lineno: int
) -> dict[str, str]:
    """Parse metadata block `[k=v ...]` and validate syntax."""
    if raw is None:
        return {}
    out: dict[str, str] = {}
    for token in raw.split():
        if "=" not in token:
            raise MapParseError(
                f"{path}:{lineno}: invalid metadata token {token!r}"
            )
        key, _, value = token.partition("=")
        if not key or not value:
            raise MapParseError(
                f"{path}:{lineno}: invalid metadata token {token!r}"
            )
        out[key.strip()] = value.strip()
    return out


def _parse_positive_int(
    raw: str, *, path: Path, lineno: int, field_name: str
) -> int:
    """Parse strictly positive integer values."""
    if not raw.isdigit():
        raise MapParseError(
            f"{path}:{lineno}: {field_name} must be a positive integer"
        )
    value = int(raw)
    if value <= 0:
        raise MapParseError(f"{path}:{lineno}: {field_name} must be > 0")
    return value


def load_map(path: Path) -> MapData:
    """Read and validate a map file according to subject constraints."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MapParseError(f"{path}: unable to read map: {exc}") from exc

    nb_drones: int | None = None
    hubs: dict[str, Hub] = {}
    connections: list[Connection] = []
    seen_connections: set[frozenset[str]] = set()
    first_data_line_seen = False

    for lineno, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue

        if not first_data_line_seen:
            first_data_line_seen = True
            m = _NB_DRONES.match(line)
            if not m:
                raise MapParseError(
                    f"{path}:{lineno}: first line must be nb_drones: <int>"
                )
            nb_drones = _parse_positive_int(
                m.group(1), path=path, lineno=lineno, field_name="nb_drones"
            )
            continue

        m = _NB_DRONES.match(line)
        if m:
            raise MapParseError(
                f"{path}:{lineno}: nb_drones must appear only once"
            )

        m = _HUB_LINE.match(line)
        if m:
            kind_raw, name, sx, sy, bracket = m.groups()
            if name in hubs:
                raise MapParseError(
                    f"{path}:{lineno}: duplicate zone name {name!r}"
                )
            attrs = _parse_brackets(bracket, path=path, lineno=lineno)
            zone_value = attrs.get("zone", "normal").lower()
            if zone_value not in _VALID_ZONE_TYPES:
                raise MapParseError(
                    f"{path}:{lineno}: invalid zone type {zone_value!r}; "
                    "expected one of normal|restricted|priority|blocked"
                )
            if "max_drones" in attrs:
                _parse_positive_int(
                    attrs["max_drones"],
                    path=path,
                    lineno=lineno,
                    field_name="max_drones",
                )
            kind: HubKind = "hub"
            if kind_raw == "start_hub":
                kind = "start"
            elif kind_raw == "end_hub":
                kind = "end"
            hubs[name] = Hub(
                name=name, kind=kind, x=int(sx), y=int(sy), attrs=attrs
            )
            continue

        m = _CONN_LINE.match(line)
        if m:
            if nb_drones is None:
                raise MapParseError(
                    f"{path}:{lineno}: nb_drones must be declared first"
                )
            a, b, bracket = m.groups()
            if a not in hubs or b not in hubs:
                raise MapParseError(
                    f"{path}:{lineno}: connection must reference previously "
                    "defined zones"
                )
            key = frozenset({a, b})
            if key in seen_connections:
                raise MapParseError(
                    f"{path}:{lineno}: duplicate connection {a}-{b}"
                )
            seen_connections.add(key)
            attrs = _parse_brackets(bracket, path=path, lineno=lineno)
            cap = 1
            if "max_link_capacity" in attrs:
                cap = _parse_positive_int(
                    attrs["max_link_capacity"],
                    path=path,
                    lineno=lineno,
                    field_name="max_link_capacity",
                )
            unknown = set(attrs.keys()) - {"max_link_capacity"}
            if unknown:
                keys = ", ".join(sorted(unknown))
                raise MapParseError(
                    f"{path}:{lineno}: unknown connection metadata: {keys}"
                )
            connections.append(Connection(a=a, b=b, max_link_capacity=cap))
            continue

        raise MapParseError(f"{path}:{lineno}: unrecognized line: {line!r}")

    if nb_drones is None:
        raise MapParseError(f"{path}: missing nb_drones declaration")
    if not hubs:
        raise MapParseError(f"{path}: no zones declared")
    if not connections:
        raise MapParseError(f"{path}: no connections declared")

    starts = [h.name for h in hubs.values() if h.kind == "start"]
    ends = [h.name for h in hubs.values() if h.kind == "end"]
    if len(starts) != 1:
        raise MapParseError(
            f"{path}: expected exactly one start_hub, got {len(starts)}"
        )
    if len(ends) != 1:
        raise MapParseError(
            f"{path}: expected exactly one end_hub, got {len(ends)}"
        )

    return MapData(
        path=path, nb_drones=nb_drones, hubs=hubs, connections=connections
    )
