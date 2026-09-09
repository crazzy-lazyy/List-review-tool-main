# -*- coding: utf-8 -*-
"""
通用控件：字段多选列表、进度提示等。
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QProgressBar,
    QGroupBox,
    QFileDialog,
    QLineEdit,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal


class ColumnSelector(QWidget):
    """双列表：可选列 <-> 已选列，用于配置对比字段、键字段。"""

    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        self.available = QListWidget()
        self.available.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.selected = QListWidget()
        self.selected.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(QLabel("可选列"))
        layout.addWidget(self.available, 1)
        btn_layout = QVBoxLayout()
        add_btn = QPushButton("添加 →")
        add_btn.clicked.connect(self._add)
        remove_btn = QPushButton("← 移除")
        remove_btn.clicked.connect(self._remove)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addWidget(QLabel("已选列"))
        layout.addWidget(self.selected, 1)

    def set_columns(self, columns: list):
        """设置可选列（清空已选并填充可选）。"""
        self.available.clear()
        self.selected.clear()
        for c in columns:
            self.available.addItem(str(c))

    def _add(self):
        for item in self.available.selectedItems():
            text = item.text()
            if not any(self.selected.item(i).text() == text for i in range(self.selected.count())):
                self.selected.addItem(text)
        self._emit()

    def _remove(self):
        for item in list(self.selected.selectedItems()):
            self.selected.takeItem(self.selected.row(item))
        self._emit()

    def _emit(self):
        self.selection_changed.emit(self.get_selected())

    def get_selected(self) -> list:
        return [self.selected.item(i).text() for i in range(self.selected.count())]


class FilePathRow(QWidget):
    """单行：标签 + 路径输入框 + 浏览按钮。"""

    path_changed = pyqtSignal(str)

    def __init__(self, label: str = "文件", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.addWidget(QLabel(label))
        self.line = QLineEdit()
        self.line.setReadOnly(True)
        layout.addWidget(self.line, 1)
        btn = QPushButton("浏览...")
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            "",
            "支持格式 (*.xlsx *.xls *.csv *.tsv *.docx *.pdf);;所有 (*.*)",
        )
        if path:
            self.line.setText(path)
            self.path_changed.emit(path)

    def path(self) -> str:
        return self.line.text().strip()

    def set_path(self, path: str):
        self.line.setText(path or "")


class ProgressWidget(QWidget):
    """进度条 + 状态文本。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.label = QLabel("就绪")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)

    def set_progress(self, value: int, text: str = ""):
        self.bar.setValue(min(100, max(0, value)))
        if text:
            self.label.setText(text)

    def set_busy(self, text: str = "处理中..."):
        self.bar.setRange(0, 0)  # 不确定进度
        self.label.setText(text)

    def set_idle(self, text: str = "就绪"):
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.label.setText(text)
