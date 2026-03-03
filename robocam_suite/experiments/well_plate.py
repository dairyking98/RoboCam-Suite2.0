"""
Well-plate path generation.

Supported scan patterns
-----------------------
raster  — left-to-right on every row (default)
snake   — left-to-right on even rows, right-to-left on odd rows
          (minimises stage travel distance)
"""
from typing import List, Tuple


class WellPlate:
    """Generates and stores the path for a well plate experiment."""

    PATTERN_RASTER = "Raster"
    PATTERN_SNAKE  = "Snake"

    def __init__(
        self,
        width: int,
        depth: int,
        corners: List[Tuple[float, float, float]],
        pattern: str = PATTERN_RASTER,
    ):
        if len(corners) != 4:
            raise ValueError("Exactly four corner points are required.")
        self.width   = width
        self.depth   = depth
        self.corners = corners
        self.pattern = pattern
        self.path    = self._generate_path()

    # ------------------------------------------------------------------
    # Path generation
    # ------------------------------------------------------------------

    def _interpolate(self, row_i: int, col_j: int) -> Tuple[float, float, float]:
        """Bilinear interpolation for a single well position."""
        upper_left, lower_left, upper_right, lower_right = self.corners
        x1, y1, z1 = upper_left
        x2, y2, z2 = lower_left
        x3, y3, z3 = upper_right
        x4, y4, z4 = lower_right

        u = col_j / (self.width - 1) if self.width > 1 else 0.0
        v = row_i / (self.depth - 1) if self.depth > 1 else 0.0

        top_x = x1 + u * (x3 - x1)
        top_y = y1 + u * (y3 - y1)
        top_z = z1 + u * (z3 - z1)

        bot_x = x2 + u * (x4 - x2)
        bot_y = y2 + u * (y4 - y2)
        bot_z = z2 + u * (z4 - z2)

        return (
            top_x + v * (bot_x - top_x),
            top_y + v * (bot_y - top_y),
            top_z + v * (bot_z - top_z),
        )

    def _generate_path(self) -> List[Tuple[float, float, float]]:
        """
        Generate the ordered list of well positions.

        For raster: row 0 → cols 0..N-1, row 1 → cols 0..N-1, …
        For snake:  row 0 → cols 0..N-1, row 1 → cols N-1..0, …
        """
        path: List[Tuple[float, float, float]] = []

        for row_i in range(self.depth):
            cols = range(self.width)
            if self.pattern == self.PATTERN_SNAKE and row_i % 2 == 1:
                cols = range(self.width - 1, -1, -1)
            for col_j in cols:
                path.append(self._interpolate(row_i, col_j))

        return path

    def get_path(self) -> List[Tuple[float, float, float]]:
        return self.path

    def get_path_with_labels(self) -> List[Tuple[str, Tuple[float, float, float]]]:
        """
        Return the ordered path as ``(label, position)`` pairs where
        ``label`` uses standard well-plate notation: row letter (A, B, …)
        and 1-based column number (1, 2, …).  For example the first well
        in row 0, column 0 is ``'A1'``; row 1 column 2 is ``'B3'``.

        For plates with more than 26 rows the row label wraps to two
        letters (AA, AB, …) following the same convention as spreadsheet
        column headers.
        """
        def _row_label(i: int) -> str:
            label = ""
            i += 1  # 1-based
            while i > 0:
                i, rem = divmod(i - 1, 26)
                label = chr(ord('A') + rem) + label
            return label

        result: List[Tuple[str, Tuple[float, float, float]]] = []
        for row_i in range(self.depth):
            cols = range(self.width)
            if self.pattern == self.PATTERN_SNAKE and row_i % 2 == 1:
                cols = range(self.width - 1, -1, -1)
            for col_j in cols:
                label = f"{_row_label(row_i)}{col_j + 1}"
                result.append((label, self._interpolate(row_i, col_j)))
        return result
