"""Transparent logo startup, with the homepage gated on audio completion."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional
import wave
from PySide6.QtCore import Qt, QTimer, QRect, QUrl
from PySide6.QtGui import QPixmap, QBitmap, QRegion
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication, QLabel, QWidget


def _asset_path(name):
    return Path(__file__).resolve().parent / "assets" / name


def logo_pixmap():
    """Trim the asset's transparent margins without changing the original PNG."""
    pixmap = QPixmap(str(_asset_path("logo.png")))
    if not pixmap.isNull():
        bounds = QRegion(
            QBitmap.fromImage(pixmap.toImage().createAlphaMask())
        ).boundingRect()
        if not bounds.isEmpty():
            pixmap = pixmap.copy(bounds)
    return pixmap


class BootOverlay(QWidget):
    def __init__(self, message="Loading…"):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.logo = QLabel(self)
        self.logo.setAlignment(Qt.AlignCenter)
        pixmap = logo_pixmap()
        self.logo.setPixmap(
            pixmap.scaled(420, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.status = QLabel(self)
        self.status.setAlignment(Qt.AlignCenter)
        loading = QPixmap(str(_asset_path("loading.png")))
        if loading.isNull():
            self.status.setText("L O A D I N G . . .")
            self.status.setStyleSheet(
                "color: white; font: 12px Consolas; background: transparent;"
            )
        else:
            self.status.setPixmap(loading)
        self.set_message(message)
        # Short PCM sound avoids the native media pipeline's early-stop stall.
        self.player = QSoundEffect(self)
        self.player.setVolume(0.9)
        self.player.setLoopCount(1)
        self.wav_path = _asset_path("boot.wav")
        if self.wav_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(self.wav_path)))
        self.setFixedSize(480, 280)
        self.logo.setGeometry(QRect(0, 20, 480, 200))
        self.status.setGeometry(QRect(0, 235, 480, 20))
        self.finished = False
        self._audio_started = False
        self._fallback = QTimer(self)
        self._fallback.setSingleShot(True)

    def center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geometry = screen.availableGeometry()
            self.move(
                geometry.x() + (geometry.width() - self.width()) // 2,
                geometry.y() + (geometry.height() - self.height()) // 2,
            )

    def start(self):
        self.center_on_screen()
        self.show()
        self.raise_()
        if self.player.source().isValid():
            self.player.play()

    def set_message(self, text):
        self.status.setAccessibleName(text)
        self.status.setToolTip(text)


def show_boot(
    app: QApplication,
    *,
    ms: int = 0,
    message="Loading Event-Based Studio…",
    keep_music: bool = False,
    on_done: Optional[Callable[[], None]] = None,
):
    """Reveal the homepage after the song; fall back safely if audio cannot play.

    Legacy ms is a fallback minimum only. Music never outlives the splash.
    keep_music remains accepted for callers of the previous API.
    """
    overlay = BootOverlay(message)

    def finish():
        if overlay.finished:
            return
        overlay.finished = True
        overlay._fallback.stop()
        overlay.player.stop()
        # Show the destination first so the app never loses its last window.
        if on_done:
            on_done()
        overlay.hide()
        overlay.deleteLater()

    def playing_changed():
        if overlay.player.isPlaying():
            overlay._audio_started = True
        elif overlay._audio_started:
            finish()

    def status_changed():
        if overlay.player.status() == QSoundEffect.Error:
            overlay._fallback.start(max(1000, ms))

    overlay.player.playingChanged.connect(playing_changed)
    overlay.player.statusChanged.connect(status_changed)
    overlay._fallback.timeout.connect(finish)
    try:
        with wave.open(str(overlay.wav_path), "rb") as sound:
            duration_ms = int(1000 * sound.getnframes() / sound.getframerate())
        fallback = max(ms, duration_ms + 3000)
    except (OSError, wave.Error, EOFError):
        fallback = max(ms, 1000)
    overlay._fallback.start(fallback)
    overlay.start()
    # Some backends synchronously reject an unavailable audio device.
    if overlay.player.status() == QSoundEffect.Error:
        status_changed()
    return overlay
