import cv2
import numpy as np
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QImage, QPainter, QColor, QPixmap
from PySide6.QtCore import Qt


class CameraWidget(QWidget):
    """
    A widget that displays a live camera feed.

    Uses a plain QWidget with a custom paintEvent rather than
    QOpenGLWidget, which keeps imports simple and portable across
    all platforms and PySide6 versions.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap = None
        # Allow the widget to grow and shrink freely
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Dark background while no frame is available
        self.setStyleSheet("background-color: black;")

    def clear_frame(self):
        """Reset to the 'No camera connected' state."""
        self._pixmap = None
        self.update()

    def set_frame(self, frame: np.ndarray):
        """
        Accepts an OpenCV BGR frame, converts it to a QPixmap, and
        schedules a repaint.  Safe to call from the main thread only.
        """
        if frame is None:
            self._pixmap = None
            self.update()
            return

        # OpenCV uses BGR; Qt expects RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        q_image = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        # Keep a copy so the underlying numpy buffer is not freed
        self._pixmap = QPixmap.fromImage(q_image.copy())
        self.update()

    def paintEvent(self, event):
        """Renders the latest frame, centred and aspect-ratio-correct."""
        painter = QPainter(self)

        if self._pixmap is None:
            painter.fillRect(self.rect(), QColor(30, 30, 30))
            # Draw a centred "No camera connected" message
            from PySide6.QtGui import QFont
            font = QFont()
            font.setPointSize(12)
            painter.setFont(font)
            painter.setPen(QColor(160, 160, 160))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "No camera connected\n\nSelect a camera in Setup and click\nApply & Reconnect Camera",
            )
            return

        scaled = self._pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
