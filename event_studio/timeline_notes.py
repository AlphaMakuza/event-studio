"""Simple timestamped comments below the playback scrubber."""
from uuid import uuid4

from PySide6.QtCore import Qt, QPoint, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QToolTip


def note_time(note, origin):
    start = (int(note['t0']) - origin) / 1_000_000
    end = (int(note['t1']) - origin) / 1_000_000
    return f'{start:.3f} s' if start == end else f'{start:.3f}–{end:.3f} s'


class NoteMarkers(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setFixedHeight(32)
        self.setMouseTracking(True)
        self.setAccessibleName('Timeline notes')
        self.setToolTip('Click a comment to read it and go to its time. Notes follow the timeline zoom.')

    def positions(self):
        owner = self.panel.owner
        if owner.events is None:
            return []
        offset = self.mapFromGlobal(owner.timeline.mapToGlobal(QPoint(0, 0))).x()
        return [(i, offset + owner.timeline._value_to_x(owner._time_us_to_slider_value(n['t0'])))
                for i, n in enumerate(owner.annotations)
                if owner.zoom_start <= n['t0'] <= owner.zoom_end]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        positions = self.positions()
        if not positions:
            painter.setPen(QColor('#b5acbf'))
            painter.drawText(self.rect(), Qt.AlignCenter, 'No notes in this time range. Add a comment below.')
            return
        for i, x in positions:
            note = self.panel.owner.annotations[i]
            selected = note is self.panel.selected
            painter.setPen(QPen(QColor('#fff2fc') if selected else QColor('#b6b0ce'), 1))
            painter.drawLine(x, 0, x, 7)
            painter.setBrush(QColor('#ff63c3') if selected else QColor('#647de0'))
            painter.drawRoundedRect(QRectF(x - 8, 7, 16, 16), 5, 5)
            painter.setPen(QColor('#ffffff'))
            painter.drawText(QRectF(x - 8, 7, 16, 16), Qt.AlignCenter, '•')

    def hits(self, x):
        return [i for i, px in self.positions() if abs(px - x) <= 10]

    def mouseMoveEvent(self, event):
        hits = self.hits(event.position().x())
        if hits:
            owner = self.panel.owner
            QToolTip.showText(event.globalPosition().toPoint(), '\n\n'.join(
                f"{note_time(owner.annotations[i], owner.t_min)}: "
                f"{owner.annotations[i].get('text') or owner.annotations[i].get('name', 'Note')}"
                for i in hits), self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        hits = self.hits(event.position().x())
        if len(hits) == 1:
            self.panel.select_note(hits[0])
        elif hits:
            from .theme import StudioMenu
            menu = StudioMenu(self)
            for i in hits:
                note = self.panel.owner.annotations[i]
                action = menu.addAction(f"{note_time(note, self.panel.owner.t_min)}: {(note.get('text') or note.get('name', 'Note'))[:80]}")
                action.triggered.connect(lambda checked=False, index=i: self.panel.select_note(index))
            menu.exec(event.globalPosition().toPoint())
            menu.deleteLater()


class TimelineNotes(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.selected = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.markers = NoteMarkers(self)
        layout.addWidget(self.markers)
        row = QHBoxLayout()
        actions = QVBoxLayout()
        self.time_label = QLabel('Note at playhead')
        self.time_label.setStyleSheet('color: #d9d9df;')
        actions.addWidget(self.time_label)
        self.editor = QPlainTextEdit()
        self.editor.setMinimumHeight(180)
        self.editor.setMaximumHeight(260)
        self.editor.setMaximumWidth(800)
        self.editor.setMaximumBlockCount(0)
        self.editor.setTabChangesFocus(True)
        self.editor.setStyleSheet('color: #d9d9df; placeholder-text-color: #b6b6c2; selection-color: #ffffff;')
        self.editor.setPlaceholderText('Write your note here…\nEnter adds a new line. Ctrl+Enter saves your note.')
        self.editor.setAccessibleName('Timeline note text')
        row.addWidget(self.editor, 1)
        self.add_button = QPushButton('Add note')
        self.add_button.clicked.connect(self.add_note)
        self.save_shortcut = QShortcut(QKeySequence('Ctrl+Return'), self.editor)
        self.save_shortcut.setContext(Qt.WidgetShortcut)
        self.save_shortcut.activated.connect(self.submit)
        self.keypad_save_shortcut = QShortcut(QKeySequence('Ctrl+Enter'), self.editor)
        self.keypad_save_shortcut.setContext(Qt.WidgetShortcut)
        self.keypad_save_shortcut.activated.connect(self.submit)
        actions.addWidget(self.add_button)
        self.save_button = QPushButton('Save edit')
        self.save_button.clicked.connect(self.save_edit)
        actions.addWidget(self.save_button)
        self.delete_button = QPushButton('Delete note')
        self.delete_button.clicked.connect(self.delete_note)
        actions.addWidget(self.delete_button)
        self.done_button = QPushButton('Done')
        self.done_button.clicked.connect(self.clear_selection)
        actions.addWidget(self.done_button)
        actions.addStretch(1)
        row.addLayout(actions)
        row.addStretch(1)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        loaded = self.owner.events is not None
        self.setEnabled(loaded)
        if self.selected is not None and not any(n is self.selected for n in self.owner.annotations):
            self.clear_selection()
            return
        selected = self.selected is not None
        for button in (self.save_button, self.delete_button, self.done_button):
            button.setVisible(selected)
        self.time_label.setText(note_time(self.selected, self.owner.t_min) if selected
                               else f'Note at {(self.owner.position_us - self.owner.t_min) / 1_000_000:.3f} s')
        self.add_button.setVisible(not selected)
        self.markers.update()

    def clear_selection(self):
        self.selected = None
        self.editor.clear()
        self.refresh()

    def select_note(self, index):
        if not 0 <= index < len(self.owner.annotations):
            return
        self.selected = self.owner.annotations[index]
        self.editor.setPlainText(self.selected.get('text') or self.selected.get('name', ''))
        self.owner._seek_from_plot(self.selected['t0'])
        self.refresh()

    def submit(self):
        self.save_edit() if self.selected is not None else self.add_note()

    def add_note(self):
        text = self.editor.toPlainText().strip()
        if not text or self.owner.events is None:
            return
        timestamp = self.owner.position_us
        self.owner.annotations.append({'id': uuid4().hex, 'name': text[:60], 'text': text,
                                       't0': timestamp, 't1': timestamp, 'labels': [],
                                       'roi_id': None, 'roi_snapshot': None,
                                       'source_sha256': self.owner.events.metadata.get('sha256')})
        self.clear_selection()
        self.changed()

    def save_edit(self):
        text = self.editor.toPlainText().strip()
        if self.selected is not None and text:
            self.selected.update(text=text, name=text[:60])
            self.changed()

    def delete_note(self):
        if self.selected is not None:
            self.owner.annotations = [n for n in self.owner.annotations if n is not self.selected]
            self.clear_selection()
            self.changed()

    def changed(self):
        self.owner._update_timeline_slice_regions()
        if self.owner._workspace is not None:
            self.owner._workspace.refresh_annotations()
