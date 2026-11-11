"""Transparent logo startup, with the homepage gated on audio completion."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional
import wave
from PySide6.QtCore import Qt, QTimer, QRect, QUrl
from PySide6.QtGui import QPixmap, QBitmap, QRegion, QFontDatabase
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
        self.step_label = QLabel(self)
        self.step_label.setAlignment(Qt.AlignCenter)
        console_font = Path("C:/Windows/Fonts/consola.ttf")
        if console_font.exists():
            QFontDatabase.addApplicationFont(str(console_font))
        for label in (self.step_label,):
            label.setStyleSheet(
                "color: white; font: 8px Consolas, monospace; background: transparent;"
            )
            label.setTextFormat(Qt.PlainText)
        self.completed_steps = []
        self._tasks_done = False
        self._audio_done = False
        self.set_message(message)
        # Short PCM sound avoids the native media pipeline's early-stop stall.
        self.player = QSoundEffect(self)
        self.player.setVolume(0.9)
        self.player.setLoopCount(1)
        self.wav_path = _asset_path("boot.wav")
        if self.wav_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(self.wav_path)))
        self.setFixedSize(540, 390)
        self.logo.setGeometry(QRect(0, 20, 540, 200))
        self.step_label.setGeometry(QRect(0, 303, 540, 12))
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
        self.step_label.setAccessibleName(text)
        self.step_label.setText(text)


def show_boot(
    app: QApplication,
    *,
    ms: int = 0,
    message="Loading Event-Based Studio…",
    keep_music: bool = False,
    on_done: Optional[Callable[[], None]] = None,
    steps=(),
    on_error=None,
):
    """Reveal the homepage after the song; fall back safely if audio cannot play.

    Legacy ms is a fallback minimum only. Music never outlives the splash.
    keep_music remains accepted for callers of the previous API.
    """
    overlay = BootOverlay(message)
    pending = list(steps)
    overlay._tasks_done = not pending

    def finish():
        if overlay.finished or not (overlay._tasks_done and overlay._audio_done):
            return
        overlay.finished = True
        overlay._fallback.stop()
        overlay.player.stop()
        # Show the destination first so the app never loses its last window.
        if on_done:
            on_done()
        overlay.hide()
        overlay.deleteLater()

    def audio_done():
        overlay._audio_done = True
        finish()

    def next_step():
        if not pending:
            overlay._tasks_done = True
            overlay.set_message(
                "Finishing up…"
                if not overlay._audio_done
                else "Ready"
            )
            finish()
            return
        label, action = pending.pop(0)
        overlay.set_message(label + "…")

        def execute():
            try:
                action()
            except Exception as exc:
                overlay._fallback.stop()
                overlay.player.stop()
                overlay.set_message("Startup failed: " + str(exc))
                if on_error:
                    on_error(exc)
                return
            overlay.completed_steps.append(label)
            # Keep each real status readable before replacing it with the next.
            QTimer.singleShot(400, next_step)

        QTimer.singleShot(0, execute)

    def playing_changed():
        if overlay.player.isPlaying():
            overlay._audio_started = True
        elif overlay._audio_started:
            audio_done()

    def status_changed():
        if overlay.player.status() == QSoundEffect.Error:
            overlay._fallback.start(max(1000, ms))

    overlay.player.playingChanged.connect(playing_changed)
    overlay.player.statusChanged.connect(status_changed)
    overlay._fallback.timeout.connect(audio_done)
    try:
        with wave.open(str(overlay.wav_path), "rb") as sound:
            duration_ms = int(1000 * sound.getnframes() / sound.getframerate())
        fallback = max(ms, duration_ms + 3000)
    except (OSError, wave.Error, EOFError):
        fallback = max(ms, 1000)
    overlay._fallback.start(fallback)
    overlay.start()
    if pending:
        QTimer.singleShot(0, next_step)
    # Some backends synchronously reject an unavailable audio device.
    if overlay.player.status() == QSoundEffect.Error:
        status_changed()
    return overlay
