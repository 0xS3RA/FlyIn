from PySide6.QtGui import QColor

_FALLBACK_HEX: dict[str, str] = {
    "brown": "#8b4513",
    "darkred": "#8b0000",
    "maroon": "#800000",
    "lime": "#32cd32",
    "orange": "#ff8c00",
    "cyan": "#00bcd4",
    "gold": "#ffd700",
    "rainbow": "#e040fb",
}


def resolve_color(name: str | None, default_hex: str = "#5c6bc0") -> QColor:
    if not name or not name.strip():
        return QColor(default_hex)
    key = name.strip().lower()
    if key == "rainbow":
        return QColor(_FALLBACK_HEX["rainbow"])
    qc = QColor(key)
    if qc.isValid():
        return qc
    hx = _FALLBACK_HEX.get(key)
    if hx:
        return QColor(hx)
    return QColor(default_hex)


def zone_accent(zone: str) -> tuple[QColor, int]:
    """Return (outline color, width) used to highlight zone type."""
    z = zone.lower()
    if z == "restricted":
        return QColor("#ff9800"), 3
    if z == "priority":
        return QColor("#00e5ff"), 3
    if z == "blocked":
        return QColor("#37474f"), 4
    return QColor(0, 0, 0, 0), 0
