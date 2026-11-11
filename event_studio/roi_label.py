from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, List, Union

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap, QColor
from PySide6.QtWidgets import QWidget


@dataclass
class Roi:
    x: int
    y: int
    w: int
    h: int


class ROILabel(QWidget):
    """
    ROI-enabled image viewer (supports grayscale and RGB).

    Supported frame inputs:
      - uint8 HxW      -> grayscale
      - uint8 HxWx3    -> RGB

    Interactions:
      - Left-drag on empty area: create candidate ROI
      - Right-click: open ROI actions supplied by the parent window
    """

    roiChanged = Signal(object)   # emits Roi | None
    roiMoved = Signal(object)     # emits Roi when active ROI is moved/resized
    editStarted = Signal()
    editFinished = Signal()

    HANDLE_NONE = 0
    HANDLE_MOVE = 1
    HANDLE_TL = 2
    HANDLE_TR = 3
    HANDLE_BL = 4
    HANDLE_BR = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self._img_w: int = 0
        self._img_h: int = 0

        self._pix: Optional[QPixmap] = None
        self._help_text: str = "File → Open recording to begin"

        self._dragging = False
        self._drag_start = QPoint()
        self._drag_end = QPoint()

        self._candidate_roi: Optional[Roi] = None

        # saved ROI overlays: accepts either Roi or (Roi, color_hex)
        self._rois: List[Union[Roi, tuple[Roi, str]]] = []
        self._active_index: Optional[int] = None
        self._show_overlays: bool = True

        # edit active ROI
        self._editing_roi = False
        self._edit_mode = self.HANDLE_NONE
        self._edit_start_img: Optional[Tuple[int, int]] = None
        self._edit_orig_roi: Optional[Roi] = None

    # -------------------------
    # Public API
    # -------------------------
    def set_help_text(self, text: str) -> None:
        self._help_text = text
        self.update()

    def set_image_size(self, w: int, h: int) -> None:
        self._img_w, self._img_h = int(w), int(h)

    def set_show_overlays(self, show: bool) -> None:
        self._show_overlays = bool(show)
        self.update()

    def set_rois(self, rois, active_index: Optional[int] = None) -> None:
        self._rois = list(rois)
        self._active_index = active_index
        self.update()

    def set_active_index(self, idx: Optional[int]) -> None:
        self._active_index = idx
        self.update()

    def clear_roi(self) -> None:
        self._candidate_roi = None
        self.roiChanged.emit(None)
        self.update()

    def get_roi(self) -> Optional[Roi]:
        return self._candidate_roi

    def set_candidate_roi(self, roi: Optional[Roi]) -> None:
        self._candidate_roi = roi
        self.update()

    def set_frame(self, img: np.ndarray) -> None:
        """
        Supports:
          - uint8 HxW
          - uint8 HxWx3
        """
        if img is None or img.size == 0:
            self._pix = None
            self.update()
            return

        if img.dtype != np.uint8:
            img = np.clip(img, 0, 255).astype(np.uint8)

        if img.ndim == 2:
            h, w = img.shape
            self.set_image_size(w, h)
            qimg = QImage(
                img.data,
                w,
                h,
                img.strides[0],
                QImage.Format_Grayscale8,
            ).copy()
            self._pix = QPixmap.fromImage(qimg)
            self.update()
            return

        if img.ndim == 3 and img.shape[2] == 3:
            h, w, _ = img.shape
            self.set_image_size(w, h)

            if not img.flags["C_CONTIGUOUS"]:
                img = np.ascontiguousarray(img)

            qimg = QImage(
                img.data,
                w,
                h,
                img.strides[0],
                QImage.Format_RGB888,
            ).copy()
            self._pix = QPixmap.fromImage(qimg)
            self.update()
            return

        raise ValueError("ROILabel.set_frame expects uint8 HxW or uint8 HxWx3 image")

    # -------------------------
    # Helpers
    # -------------------------
    def _fit_rect(self) -> QRect:
        if not self._pix:
            return QRect(0, 0, self.width(), self.height())

        ww, wh = self.width(), self.height()
        pw, ph = self._pix.width(), self._pix.height()
        if pw <= 0 or ph <= 0:
            return QRect(0, 0, ww, wh)

        scale = min(ww / pw, wh / ph)
        dw = int(pw * scale)
        dh = int(ph * scale)
        x0 = (ww - dw) // 2
        y0 = (wh - dh) // 2
        return QRect(x0, y0, dw, dh)

    def _widget_to_image(self, pt: QPoint) -> Optional[Tuple[int, int]]:
        if not self._pix or self._img_w <= 0 or self._img_h <= 0:
            return None

        r = self._fit_rect()
        if not r.contains(pt):
            return None

        u = (pt.x() - r.x()) / max(1, r.width())
        v = (pt.y() - r.y()) / max(1, r.height())

        x = int(u * self._img_w)
        y = int(v * self._img_h)

        x = max(0, min(self._img_w - 1, x))
        y = max(0, min(self._img_h - 1, y))
        return x, y

    def _image_to_widget_rect(self, roi: Roi) -> QRect:
        r = self._fit_rect()
        if self._img_w <= 0 or self._img_h <= 0:
            return QRect()

        x0 = r.x() + int((roi.x / self._img_w) * r.width())
        y0 = r.y() + int((roi.y / self._img_h) * r.height())
        x1 = r.x() + int(((roi.x + roi.w) / self._img_w) * r.width())
        y1 = r.y() + int(((roi.y + roi.h) / self._img_h) * r.height())
        return QRect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

    def _normalize_roi(self, roi: Roi) -> Roi:
        x = max(0, min(self._img_w - 1, roi.x))
        y = max(0, min(self._img_h - 1, roi.y))
        w = max(1, roi.w)
        h = max(1, roi.h)

        if x + w > self._img_w:
            w = self._img_w - x
        if y + h > self._img_h:
            h = self._img_h - y

        w = max(1, w)
        h = max(1, h)
        return Roi(x=x, y=y, w=w, h=h)

    def _unpack_roi_entry(self, entry) -> tuple[Roi, str]:
        if isinstance(entry, tuple) and len(entry) == 2:
            roi, color = entry
            return roi, color
        return entry, "#8b0000"

    def _active_roi_entry(self) -> Optional[tuple[Roi, str]]:
        if self._active_index is None:
            return None
        if not (0 <= self._active_index < len(self._rois)):
            return None
        return self._unpack_roi_entry(self._rois[self._active_index])

    def _handle_rects(self, roi: Roi) -> dict[int, QRect]:
        wr = self._image_to_widget_rect(roi)
        s = 10
        return {
            self.HANDLE_TL: QRect(wr.left() - s // 2, wr.top() - s // 2, s, s),
            self.HANDLE_TR: QRect(wr.right() - s // 2, wr.top() - s // 2, s, s),
            self.HANDLE_BL: QRect(wr.left() - s // 2, wr.bottom() - s // 2, s, s),
            self.HANDLE_BR: QRect(wr.right() - s // 2, wr.bottom() - s // 2, s, s),
        }

    def _hit_test_active_roi(self, pt: QPoint) -> int:
        active = self._active_roi_entry()
        if active is None:
            return self.HANDLE_NONE

        roi, _ = active
        wr = self._image_to_widget_rect(roi)
        if wr.isNull():
            return self.HANDLE_NONE

        handles = self._handle_rects(roi)
        for mode, hr in handles.items():
            if hr.contains(pt):
                return mode

        if wr.contains(pt):
            return self.HANDLE_MOVE

        return self.HANDLE_NONE

    def _apply_roi_edit(
        self,
        orig: Roi,
        start_img: Tuple[int, int],
        cur_img: Tuple[int, int],
        mode: int,
    ) -> Roi:
        sx, sy = start_img
        cx, cy = cur_img
        dx = cx - sx
        dy = cy - sy

        x, y, w, h = orig.x, orig.y, orig.w, orig.h

        if mode == self.HANDLE_MOVE:
            return self._normalize_roi(Roi(x + dx, y + dy, w, h))

        if mode == self.HANDLE_TL:
            nx = x + dx
            ny = y + dy
            nw = w - dx
            nh = h - dy
            return self._normalize_roi(Roi(nx, ny, nw, nh))

        if mode == self.HANDLE_TR:
            ny = y + dy
            nw = w + dx
            nh = h - dy
            return self._normalize_roi(Roi(x, ny, nw, nh))

        if mode == self.HANDLE_BL:
            nx = x + dx
            nw = w - dx
            nh = h + dy
            return self._normalize_roi(Roi(nx, y, nw, nh))

        if mode == self.HANDLE_BR:
            nw = w + dx
            nh = h + dy
            return self._normalize_roi(Roi(x, y, nw, nh))

        return orig

    # -------------------------
    # Events
    # -------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            return  # Preserve the candidate for the context menu.

        if e.button() != Qt.LeftButton:
            return

        if not self._pix:
            return

        pt = e.position().toPoint()
        img_pt = self._widget_to_image(pt)
        if img_pt is None:
            return

        hit = self._hit_test_active_roi(pt)
        if hit != self.HANDLE_NONE:
            self.editStarted.emit()
            self._editing_roi = True
            self._edit_mode = hit
            self._edit_start_img = img_pt
            active = self._active_roi_entry()
            self._edit_orig_roi = Roi(active[0].x, active[0].y, active[0].w, active[0].h) if active else None
            return

        self._dragging = True
        self._drag_start = pt
        self._drag_end = pt
        self.update()

    def mouseMoveEvent(self, e):
        pt = e.position().toPoint()

        if self._editing_roi and self._edit_orig_roi and self._edit_start_img:
            cur_img = self._widget_to_image(pt)
            if cur_img is None:
                return

            new_roi = self._apply_roi_edit(
                self._edit_orig_roi,
                self._edit_start_img,
                cur_img,
                self._edit_mode,
            )
            self.roiMoved.emit(new_roi)
            return

        if self._dragging:
            self._drag_end = pt
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return

        if self._editing_roi:
            self._editing_roi = False
            self.editFinished.emit()
            self._edit_mode = self.HANDLE_NONE
            self._edit_start_img = None
            self._edit_orig_roi = None
            self.update()
            return

        if not self._dragging:
            return

        self._dragging = False

        a = self._widget_to_image(self._drag_start)
        b = self._widget_to_image(self._drag_end)
        if a is None or b is None:
            self.update()
            return

        x0, y0 = a
        x1, y1 = b
        x = min(x0, x1)
        y = min(y0, y1)
        w = abs(x1 - x0)
        h = abs(y1 - y0)

        if w < 2 or h < 2:
            self.update()
            return

        self._candidate_roi = Roi(x=x, y=y, w=w, h=h)
        self.roiChanged.emit(self._candidate_roi)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)

        if self._pix:
            r = self._fit_rect()
            p.drawPixmap(r, self._pix)

            if self._show_overlays:
                for i, entry in enumerate(self._rois):
                    roi, color_hex = self._unpack_roi_entry(entry)
                    wr = self._image_to_widget_rect(roi)

                    color = QColor(color_hex)
                    pen = QPen(color)
                    pen.setWidth(3 if (self._active_index is not None and i == self._active_index) else 2)
                    p.setPen(pen)
                    p.drawRect(wr)

                    if self._active_index is not None and i == self._active_index:
                        for hr in self._handle_rects(roi).values():
                            p.fillRect(hr, QColor("#9ecbff"))
                            p.setPen(QPen(Qt.white, 1))
                            p.drawRect(hr)

            if self._candidate_roi:
                wr = self._image_to_widget_rect(self._candidate_roi)
                pen = QPen(Qt.white)
                pen.setStyle(Qt.DashLine)
                pen.setWidth(2)
                p.setPen(pen)
                p.drawRect(wr)

        else:
            p.setPen(Qt.white)
            p.drawText(self.rect(), Qt.AlignCenter, self._help_text)

        if self._dragging:
            pen = QPen(Qt.white)
            pen.setStyle(Qt.DashLine)
            pen.setWidth(1)
            p.setPen(pen)
            drag_rect = QRect(self._drag_start, self._drag_end).normalized()
            p.drawRect(drag_rect)
