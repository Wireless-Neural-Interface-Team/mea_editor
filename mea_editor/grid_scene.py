"""
Qt scene wrapper exposing dynamic axis coordinates.

Axes (X/Y) are provided by an external callback, typically derived
from electrode positions for grid and tick labels.
"""

from __future__ import annotations

try:
    from PySide6.QtWidgets import QGraphicsScene
except ImportError as exc:
    raise SystemExit("PySide6 is required. Install with: pip install PySide6") from exc


class GridScene(QGraphicsScene):
    """
    Qt scene wrapper exposing dynamic axis coordinates.

    Axes (X/Y) are provided by an external callback, typically derived
    from electrode positions for grid and tick labels.
    """

    def __init__(self, parent=None) -> None:
        """Initialize scene with default axes provider (empty lists)."""
        super().__init__(parent)
        # Default: no axes (empty lists).
        self._axes_provider = lambda: ([], [])

    def set_axes_provider(self, provider) -> None:
        """
        Set the callback that provides axis values.

        Args:
            provider: No-arg function returning (x_list, y_list).
        """
        self._axes_provider = provider

    def get_axes(self) -> tuple[list[float], list[float]]:
        """
        Return current X/Y coordinates for grid and axes.

        Returns:
            (xs, ys): sorted lists of unique abscissas and ordinates.
        """
        return self._axes_provider()
