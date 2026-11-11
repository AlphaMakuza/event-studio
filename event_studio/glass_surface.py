"""Layered square glass, rendered inside the window without blurring data."""
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget, QStyle, QStyleOption


class GlassSurface(QWidget):
    def paintEvent(self, event):
        from .theme import appearance_controller
        painter = QPainter(self)
        if appearance_controller().mode == "classic":
            option = QStyleOption()
            option.initFrom(self)
            self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)
            return
        rect = QRectF(self.rect())
        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        native = bool(self.window().property("nativeGlassBackdrop"))
        for position, color in ((0, "#142d3a"), (0.48, "#15212e"), (1, "#111925")):
            tint = QColor(color)
            tint.setAlpha(210 if native else 245)
            base.setColorAt(position, tint)
        painter.fillRect(rect, base)
        for x, y, radius, color in (
            (0.1, 0.05, 0.75, QColor(69, 180, 192, 48)),
            (1.0, 0.35, 0.65, QColor(125, 127, 190, 32)),
            (0.65, 1.1, 0.6, QColor(37, 127, 154, 23)),
        ):
            light = QRadialGradient(QPointF(self.width() * x, self.height() * y), self.width() * radius)
            light.setColorAt(0, color)
            light.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(rect, light)
        reflection = QLinearGradient(0, 0, self.width() * 0.7, self.height())
        reflection.setColorAt(0, QColor(230, 250, 255, 17))
        reflection.setColorAt(0.26, QColor(230, 250, 255, 2))
        reflection.setColorAt(0.27, QColor(230, 250, 255, 9))
        reflection.setColorAt(0.52, QColor(230, 250, 255, 0))
        reflection.setColorAt(1, QColor(230, 250, 255, 0))
        painter.fillRect(rect, reflection)
        painter.setPen(QColor(216, 244, 255, 48))
        painter.drawLine(0, 0, self.width(), 0)
        painter.setPen(QColor(216, 244, 255, 23))
        painter.drawLine(0, 0, 0, self.height())
