"""Application log page."""

from __future__ import annotations

from PyQt6.QtWidgets import QPushButton, QTextEdit, QVBoxLayout, QWidget

from ..models import DeviceState


class LogPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        root.addWidget(self.text, 1)
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.clear)
        root.addWidget(clear_btn)
        self._state: DeviceState | None = None

    def clear(self) -> None:
        if self._state is not None:
            self._state.log_messages.clear()
        self.text.clear()

    def refresh(self, state: DeviceState) -> None:
        self._state = state
        self.text.setPlainText("\n".join(state.log_messages))
