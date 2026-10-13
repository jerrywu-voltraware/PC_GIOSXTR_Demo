"""Bounded, searchable view of the selected device's recent events."""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import DeviceState


class LogPage(QWidget):
    DISPLAY_LINE_LIMIT = 500
    REFRESH_INTERVAL_MS = 150

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state: DeviceState | None = None
        self._snapshot: tuple[str, ...] = ()
        self._rendered_lines: tuple[str, ...] = ()
        self._clear_anchor: str | None = None
        self._rendering = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._capture_snapshot)

        root = QVBoxLayout(self)
        title = QLabel("目前裝置事件 · 最新在上方")
        title.setStyleSheet("font-weight: 700;")
        root.addWidget(title)

        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜尋訊息、錯誤或關鍵字…")
        self.search_input.setAccessibleName("搜尋裝置事件")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._render)
        filters.addWidget(self.search_input, 1)
        self.level_filter = QComboBox()
        self.level_filter.setAccessibleName("事件嚴重度篩選")
        self.level_filter.addItem("全部事件", "ALL")
        self.level_filter.addItem("警告與錯誤", "IMPORTANT")
        self.level_filter.addItem("僅錯誤", "ERROR")
        self.level_filter.setToolTip("依訊息中的 error、failed、warning、錯誤、警告等文字判定。")
        self.level_filter.currentIndexChanged.connect(self._render)
        filters.addWidget(self.level_filter)
        root.addLayout(filters)

        actions = QHBoxLayout()
        self.pause_button = QPushButton("暫停畫面")
        self.pause_button.setCheckable(True)
        self.pause_button.setToolTip("只暫停此頁顯示；裝置接收與檔案記錄會持續執行。")
        self.pause_button.toggled.connect(self._set_paused)
        actions.addWidget(self.pause_button)
        self.follow_checkbox = QCheckBox("追蹤最新")
        self.follow_checkbox.setChecked(True)
        self.follow_checkbox.setToolTip("自動保持在頂端；向下捲動檢視歷程時會停止追蹤。")
        self.follow_checkbox.toggled.connect(self._set_follow)
        actions.addWidget(self.follow_checkbox)
        actions.addStretch(1)
        self.clear_button = QPushButton("清除畫面")
        self.clear_button.setToolTip("只清除此裝置目前的顯示，不刪除事件來源、batch.txt 或 CSV。")
        self.clear_button.clicked.connect(self.clear)
        actions.addWidget(self.clear_button)
        root.addLayout(actions)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setMaximumBlockCount(self.DISPLAY_LINE_LIMIT)
        self.text.setAccessibleName("裝置事件內容")
        self.text.setPlaceholderText("裝置事件會顯示於此；完整歷程可從 Overview 開啟 batch.txt。")
        self.text.verticalScrollBar().valueChanged.connect(self._on_scroll)
        root.addWidget(self.text, 1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        hint = QLabel("畫面最多保留最近 500 筆。暫停、搜尋與清除畫面均不影響 CSV 或 batch.txt 寫入。")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self._update_status()

    def clear(self) -> None:
        """Hide existing device events without mutating their source or files."""
        self._refresh_timer.stop()
        messages = self._state.log_messages if self._state is not None else []
        # DeviceState prepends immutable strings and keeps at most 500 entries.
        # One object reference is enough to identify the clear boundary, even
        # when two events happen to have identical timestamps and text.
        self._clear_anchor = messages[0] if messages else None
        self._snapshot = ()
        self._render()

    def refresh(self, state: DeviceState) -> None:
        if state is not self._state:
            self._refresh_timer.stop()
            self._state = state
            self._clear_anchor = None
            # A new device must not inherit another device's frozen view.
            self.pause_button.blockSignals(True)
            self.pause_button.setChecked(False)
            self.pause_button.blockSignals(False)
            self.pause_button.setText("暫停畫面")
            self.follow_checkbox.setChecked(True)
            self._capture_snapshot()
        elif not self.pause_button.isChecked() and not self._refresh_timer.isActive():
            # Repeated packet callbacks share one pending refresh; do not
            # restart this timer or a busy stream could starve the display.
            self._refresh_timer.start()

    def _capture_snapshot(self) -> None:
        if self._state is None or self.pause_button.isChecked():
            return
        messages = self._state.log_messages[: self.DISPLAY_LINE_LIMIT]
        if self._clear_anchor is not None:
            for index, message in enumerate(messages):
                if message is self._clear_anchor:
                    messages = messages[:index]
                    break
            else:
                # The old boundary aged out; every retained event is new.
                self._clear_anchor = None
        # One event occupies one screen line, even if a diagnostic contains
        # embedded newlines. The unmodified source remains available on disk.
        snapshot = tuple(" ".join(message.splitlines()) for message in messages)
        if snapshot != self._snapshot:
            self._snapshot = snapshot
            self._render()
        else:
            self._update_status()

    @staticmethod
    def _severity(message: str) -> str:
        lowered = message.casefold()
        if any(marker in lowered for marker in ("error", "failed", "exception", "失敗", "錯誤", "異常")):
            return "ERROR"
        if any(marker in lowered for marker in ("warning", "unknown", "skipped", "警告", "略過")):
            return "WARNING"
        return "INFO"

    def _render(self, *_args) -> None:
        query = self.search_input.text().strip().casefold()
        level = self.level_filter.currentData()
        lines = tuple(
            line for line in self._snapshot
            if (not query or query in line.casefold())
            and (
                level == "ALL"
                or (level == "IMPORTANT" and self._severity(line) in {"WARNING", "ERROR"})
                or (level == "ERROR" and self._severity(line) == "ERROR")
            )
        )
        if lines != self._rendered_lines:
            scrollbar = self.text.verticalScrollBar()
            old_position = scrollbar.value()
            old_horizontal = self.text.horizontalScrollBar().value()
            old_anchor = self.text.firstVisibleBlock().text()
            self._rendering = True
            try:
                self.text.setPlainText("\n".join(lines))
                if self.follow_checkbox.isChecked():
                    scrollbar.setValue(scrollbar.minimum())
                else:
                    # Preserve the visible event when new entries are prepended.
                    new_position = lines.index(old_anchor) if old_anchor in lines else old_position
                    scrollbar.setValue(new_position)
                self.text.horizontalScrollBar().setValue(old_horizontal)
            finally:
                self._rendering = False
            self._rendered_lines = lines
        self._update_status()

    def _set_paused(self, paused: bool) -> None:
        self.pause_button.setText("恢復畫面" if paused else "暫停畫面")
        if paused:
            self._refresh_timer.stop()
        else:
            self._capture_snapshot()
        self._update_status()

    def _set_follow(self, follow: bool) -> None:
        if follow:
            self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().minimum())
        self._update_status()

    def _on_scroll(self, value: int) -> None:
        if not self._rendering and value > self.text.verticalScrollBar().minimum():
            self.follow_checkbox.setChecked(False)

    def _update_status(self) -> None:
        mode = "已暫停畫面" if self.pause_button.isChecked() else "即時更新"
        follow = "追蹤最新" if self.follow_checkbox.isChecked() else "檢視歷程"
        self.status_label.setText(
            f"{mode} · {follow} · 顯示 {len(self._rendered_lines)} / {len(self._snapshot)} 筆"
        )
