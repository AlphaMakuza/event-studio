"""Exact, bounded activity overview of the loaded original events."""

import numpy as np
from PySide6.QtCore import Qt, Signal, QRectF, QPoint
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget


def activity_color(level):
    """Blend a vibrant blue-to-green-to-pink activity palette."""
    stops = ((65, 112, 255), (38, 210, 237), (86, 235, 133), (183, 112, 250), (255, 72, 184))
    position = max(0.0, min(1.0, float(level))) * (len(stops) - 1)
    index = min(int(position), len(stops) - 2)
    fraction = position - index
    channels = [round(a + (b - a) * fraction)
                for a, b in zip(stops[index], stops[index + 1])]
    return QColor(*channels, 235)


def overview_bins(timestamps, maximum_bins=512):
    if not len(timestamps):
        return np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    start, end = int(timestamps[0]), int(timestamps[-1]) + 1
    width = max(1, (end - start + maximum_bins - 1) // maximum_bins)
    edges = np.arange(start, end, width, dtype=np.int64)
    edges = np.r_[edges, np.int64(end)]
    return edges, np.diff(np.searchsorted(timestamps, edges, side="left"))


class RecordingOverview(QWidget):
    seekRequested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Recording activity overview")
        self.setToolTip("Activity in the visible timeline range. Colors blend from blue (low activity) through cyan, green and violet to hot pink (high activity), relative to the recording on a logarithmic scale. The thin line marks playback time and aligns with the slider below. Click or drag to seek. Saved slices are shown and edited only on the time bar below.")
        self.edges = np.array([])
        self.counts = np.array([])
        self.interval = (0, 0)
        self.press = None
        self.timeline = None
        self.visible_range = None
        self.setEnabled(False)

    def set_recording(self, events):
        self.edges, self.counts = overview_bins(events.t) if events is not None else (np.array([]), np.array([]))
        self.setEnabled(bool(len(self.counts)))
        self.visible_range = None
        self.update()

    def set_interval(self, start, end):
        self.interval = start, end
        self.update()

    def set_visible_range(self, start, end):
        self.visible_range = int(start), max(int(start) + 1, int(end))
        self.update()

    def track_bounds(self):
        if self.timeline is not None:
            left, right = self.timeline.track_bounds()
            return (self.mapFromGlobal(self.timeline.mapToGlobal(QPoint(left, 0))).x(),
                    self.mapFromGlobal(self.timeline.mapToGlobal(QPoint(right, 0))).x())
        return 0, max(1, self.width() - 1)

    def time_range(self):
        return self.visible_range or (int(self.edges[0]), int(self.edges[-1]))

    def time_to_x(self, timestamp):
        origin, end = self.time_range()
        left, right = self.track_bounds()
        return left + (int(timestamp) - origin) * (right - left) / max(1, end - origin)

    def timestamp(self, x):
        origin, end = self.time_range()
        left, right = self.track_bounds()
        fraction = (max(min(left, right), min(max(left, right), x)) - left) / (right - left or 1)
        return min(end, origin + round(fraction * (end - origin)))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and len(self.counts):
            self.press = event.position().x()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self.press is None:
            return
        self.press = None
        self.seekRequested.emit(self.timestamp(event.position().x()))

    def mouseMoveEvent(self, event):
        if self.press is not None and len(self.counts):
            self.seekRequested.emit(self.timestamp(event.position().x()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 22, 33, 100))
        if not len(self.counts):
            painter.setPen(QColor("#b5acbf"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Recording activity appears here")
            return
        rates = self.counts * 1000.0 / np.diff(self.edges)
        levels = np.log1p(rates)
        peak = max(float(levels.max()), 1e-12)
        painter.setPen(Qt.NoPen)
        left, right = self.track_bounds()
        painter.setClipRect(QRectF(min(left, right), 0, abs(right - left) + 1, self.height()))
        for i, value in enumerate(levels):
            level = float(value) / peak
            painter.setBrush(activity_color(level))
            x0, x1 = self.time_to_x(self.edges[i]), self.time_to_x(self.edges[i + 1])
            height = level * (self.height() - 10)
            painter.drawRect(QRectF(min(x0, x1), self.height() - height, max(1, abs(x1 - x0)), height))
        # Use the shared timeline coordinates, without outlining the frame window.
        playhead_x = round(self.time_to_x(self.interval[0]))
        painter.setPen(QPen(QColor(30, 24, 42, 210), 3))
        painter.drawLine(playhead_x, 1, playhead_x, self.height() - 1)
        painter.setPen(QPen(QColor("#fff2fc"), 1))
        painter.drawLine(playhead_x, 1, playhead_x, self.height() - 1)
