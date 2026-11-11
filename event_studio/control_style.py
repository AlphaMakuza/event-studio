"""Shared window chrome and visible numeric step arrows in both appearances."""
from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QColor, QPolygonF
from PySide6.QtWidgets import QProxyStyle, QStyle, QWidget, QDialog


class StudioStyle(QProxyStyle):
    def __init__(self):
        super().__init__('Fusion')

    def polish(self, target):
        super().polish(target)
        if isinstance(target, QDialog):
            target.installEventFilter(self)
            from .window_chrome import install_window_header
            install_window_header(target)

    def eventFilter(self, target, event):
        if event.type() in (QEvent.PolishRequest, QEvent.LayoutRequest, QEvent.Show):
            from .window_chrome import install_window_header
            install_window_header(target)
        return False

    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (QStyle.PE_IndicatorSpinUp, QStyle.PE_IndicatorSpinDown):
            center = option.rect.center()
            direction = -1 if element == QStyle.PE_IndicatorSpinUp else 1
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#eee5f5') if option.state & QStyle.State_Enabled else QColor('#847d8b'))
            painter.drawPolygon(QPolygonF([QPointF(center.x() - 3, center.y() - direction * 2),
                                           QPointF(center.x() + 3, center.y() - direction * 2),
                                           QPointF(center.x(), center.y() + direction * 2)]))
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)
