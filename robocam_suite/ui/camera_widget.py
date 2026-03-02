import cv2
from PySide6.QtWidgets import QOpenGLWidget
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtCore import Qt, QTimer
import numpy as np

class CameraWidget(QOpenGLWidget):
    """A widget to display a camera feed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame: np.ndarray = None

    def set_frame(self, frame: np.ndarray):
        """Sets the frame to be displayed."""
        # Convert BGR (OpenCV default) to RGB
        if frame is not None:
            self._frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            self._frame = None
        self.update() # Trigger a repaint

    def paintGL(self):
        """Renders the camera frame to the widget."""
        painter = QPainter(self)

        if self._frame is None:
            painter.fillRect(self.rect(), QColor('black'))
            painter.setPen(QColor('white'))
            painter.drawText(self.rect(), Qt.AlignCenter, "No Camera Feed")
            return

        height, width, channel = self._frame.shape
        bytes_per_line = 3 * width
        q_image = QImage(self._frame.data, width, height, bytes_per_line, QImage.Format_RGB888)

        # Scale image to fit widget, preserving aspect ratio
        scaled_image = q_image.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Center the image
        x = (self.width() - scaled_image.width()) / 2
        y = (self.height() - scaled_image.height()) / 2

        painter.drawImage(x, y, scaled_image)
