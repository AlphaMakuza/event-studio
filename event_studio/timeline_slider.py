from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSlider


class TimelineSlider(QSlider):
    sliceSelected = Signal(int)
    sliceEdited = Signal(int, int, int)  # index, start_value, end_value

    def __init__(self, orientation=Qt.Horizontal, parent=None) -> None:
        super().__init__(orientation, parent)

        self._slice_regions: List[dict] = []
        self._selected_slice_index: Optional[int] = None

        self._drag_mode: Optional[str] = None  # None / "move" / "resize_left" / "resize_right"
        self._drag_slice_index: Optional[int] = None
        self._drag_offset_value: int = 0
        self._drag_start_value: int = 0
        self._drag_end_value: int = 0
        self._handle_px = 8

    def set_slice_regions(self, regions: List[dict], selected_index: Optional[int] = None) -> None:
        self._slice_regions = regions
        self._selected_slice_index = selected_index
        self.update()

    def clear_slice_regions(self) -> None:
        self._slice_regions = []
        self._selected_slice_index = None
        self.update()

    def _value_to_x(self, value: int) -> int:
        vmin = self.minimum()
        vmax = self.maximum()
        if vmax <= vmin:
            return 8

        usable_w = max(1, self.width() - 16)
        frac = (value - vmin) / (vmax - vmin)
        return 8 + int(frac * usable_w)

    def _x_to_value(self, x: int) -> int:
        vmin = self.minimum()
        vmax = self.maximum()
        usable_w = max(1, self.width() - 16)
        clamped_x = max(8, min(self.width() - 8, x))
        frac = (clamped_x - 8) / usable_w
        return int(round(vmin + frac * (vmax - vmin)))

    def _region_rect(self, region: dict) -> QRect:
        x0 = self._value_to_x(int(region["start_value"]))
        x1 = self._value_to_x(int(region["end_value"]))
        if x1 < x0:
            x0, x1 = x1, x0

        track_y = self.height() // 2 - 12
        track_h = 8
        width = max(6, x1 - x0)
        return QRect(x0, track_y, width, track_h)

    def _hit_test_slice(self, x: int, y: int):
        for region in reversed(self._slice_regions):
            rect = self._region_rect(region)
            if rect.adjusted(-2, -4, 2, 4).contains(x, y):
                left_handle = QRect(rect.left() - self._handle_px, rect.top() - 4, self._handle_px * 2, rect.height() + 8)
                right_handle = QRect(rect.right() - self._handle_px, rect.top() - 4, self._handle_px * 2, rect.height() + 8)

                if left_handle.contains(x, y):
                    return region["index"], "resize_left"
                if right_handle.contains(x, y):
                    return region["index"], "resize_right"
                return region["index"], "move"
        return None, None

    def mousePressEvent(self, event) -> None:
        if self.orientation() == Qt.Horizontal and event.button() == Qt.LeftButton and self._slice_regions:
            idx, mode = self._hit_test_slice(event.position().x(), event.position().y())
            if idx is not None:
                self._selected_slice_index = idx
                self.sliceSelected.emit(idx)

                region = next((r for r in self._slice_regions if r["index"] == idx), None)
                if region is not None:
                    self._drag_mode = mode
                    self._drag_slice_index = idx
                    self._drag_start_value = int(region["start_value"])
                    self._drag_end_value = int(region["end_value"])
                    mouse_value = self._x_to_value(int(event.position().x()))
                    self._drag_offset_value = mouse_value - self._drag_start_value
                    self.update()
                    event.accept()
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode is not None and self._drag_slice_index is not None:
            mouse_value = self._x_to_value(int(event.position().x()))
            min_v = self.minimum()
            max_v = self.maximum()

            start_v = self._drag_start_value
            end_v = self._drag_end_value
            min_len = 2

            if self._drag_mode == "move":
                length = end_v - start_v
                new_start = mouse_value - self._drag_offset_value
                new_end = new_start + length

                if new_start < min_v:
                    new_start = min_v
                    new_end = new_start + length
                if new_end > max_v:
                    new_end = max_v
                    new_start = new_end - length

                start_v = new_start
                end_v = new_end

            elif self._drag_mode == "resize_left":
                start_v = max(min_v, min(mouse_value, end_v - min_len))

            elif self._drag_mode == "resize_right":
                end_v = min(max_v, max(mouse_value, start_v + min_len))

            self.sliceEdited.emit(self._drag_slice_index, int(start_v), int(end_v))
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_mode is not None:
            self._drag_mode = None
            self._drag_slice_index = None
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        if self.orientation() != Qt.Horizontal:
            return
        if not self._slice_regions:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        for region in self._slice_regions:
            rect = self._region_rect(region)

            color = QColor(region.get("color", "#34c759"))
            fill = QColor(color)
            fill.setAlpha(145)

            painter.fillRect(rect, fill)

            pen = QPen(color, 2)
            if region.get("index") == self._selected_slice_index:
                pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(rect)

            if region.get("index") == self._selected_slice_index:
                handle_pen = QPen(QColor("#ffffff"), 2)
                painter.setPen(handle_pen)
                painter.drawLine(rect.left(), rect.top() - 3, rect.left(), rect.bottom() + 3)
                painter.drawLine(rect.right(), rect.top() - 3, rect.right(), rect.bottom() + 3)

        painter.end()