from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, QRect, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication, QLabel, QWidget


def _asset_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "assets" / name


class BootOverlay(QWidget):
    def __init__(self, message: str = "Loading…") -> None:
        super().__init__()

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.logo = QLabel(self)
        self.logo.setAlignment(Qt.AlignCenter)

        logo_path = _asset_path("logo.png")
        pm = QPixmap(str(logo_path))
        if pm.isNull():
            self.logo.setText("logo.png not found")
            self.logo.setStyleSheet("color: white;")
        else:
            target = 520
            pm2 = pm.scaled(target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.logo.setPixmap(pm2)

        self.status = QLabel(message, self)
        self.status.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.status.setStyleSheet(
            "color: white;"
            "font-family: Consolas;"
            "font-size: 12px;"
        )

        # IMPORTANT: keep the player alive even if the overlay hides
        # (we hide, not close, so this is safe)
        # The asset is PCM WAV: use Qt's short-sound path rather than an FFmpeg
        # media pipeline, whose early shutdown stalled in native release tests.
        self.player = QSoundEffect(self)
        self.player.setVolume(0.9)

        wav_path = _asset_path("boot.wav")
        if wav_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(wav_path)))

        self._layout()

    def _layout(self) -> None:
        w, h = 700, 650
        self.setFixedSize(w, h)
        self.logo.setGeometry(QRect(0, 40, w, 520))
        self.status.setGeometry(QRect(0, 570, w, 30))

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)

    def start(self) -> None:
        self.center_on_screen()
        self.show()
        self.raise_()
        self.activateWindow()  # helps keep it on top on some setups
        if self.player.source().isValid():
            self.player.play()

    def set_message(self, text: str) -> None:
        self.status.setText(text)


def show_boot(
    app: QApplication,
    *,
    ms: int = 7000,
    message: str = "Loading Event-Based Studio…",
    keep_music: bool = True,
    on_done: Optional[Callable[[], None]] = None,
) -> BootOverlay:
    """
    Shows the boot overlay, plays audio, and after `ms` calls on_done.
    If keep_music=True, audio continues after overlay hides.
    """
    overlay = BootOverlay(message=message)
    overlay.start()

    def _finish():
        # Hide (DON'T close) so the player/audio doesn't get destroyed.
        overlay.hide()

        if not keep_music:
            try:
                overlay.player.stop()
            except Exception:
                pass
            overlay.deleteLater()
        else:
            # Optional cleanup: delete overlay after audio ends.
            # If duration isn't known/available, just delete later after a buffer.
            # (boot.wav is ~10s in your case)
            def cleanup_when_finished():
                if not overlay.player.isPlaying():
                    overlay.deleteLater()
            overlay.player.playingChanged.connect(cleanup_when_finished)
            cleanup_when_finished()

        if on_done:
            on_done()

    QTimer.singleShot(ms, _finish)
    return overlay
