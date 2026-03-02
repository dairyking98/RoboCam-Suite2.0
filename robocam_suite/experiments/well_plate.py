from typing import List, Tuple

class WellPlate:
    """Generates and stores the path for a well plate experiment."""

    def __init__(self, width: int, depth: int, corners: List[Tuple[float, float, float]]):
        if len(corners) != 4:
            raise ValueError("Exactly four corner points are required.")
        self.width = width
        self.depth = depth
        self.corners = corners
        self.path = self._generate_path()

    def _generate_path(self) -> List[Tuple[float, float, float]]:
        """Generate a path of well positions from four corner coordinates."""
        path: List[Tuple[float, float, float]] = []
        
        upper_left, lower_left, upper_right, lower_right = self.corners
        x1, y1, z1 = upper_left
        x2, y2, z2 = lower_left
        x3, y3, z3 = upper_right
        x4, y4, z4 = lower_right
        
        for i in range(self.depth):
            for j in range(self.width):
                u = j / (self.width - 1) if self.width > 1 else 0.0
                v = i / (self.depth - 1) if self.depth > 1 else 0.0
                
                top_x = x1 + u * (x3 - x1)
                top_y = y1 + u * (y3 - y1)
                top_z = z1 + u * (z3 - z1)
                
                bottom_x = x2 + u * (x4 - x2)
                bottom_y = y2 + u * (y4 - y2)
                bottom_z = z2 + u * (z4 - z2)
                
                x = top_x + v * (bottom_x - top_x)
                y = top_y + v * (bottom_y - top_y)
                z = top_z + v * (bottom_z - top_z)
                
                path.append((x, y, z))
        
        return path

    def get_path(self) -> List[Tuple[float, float, float]]:
        """Returns the generated path."""
        return self.path
