# -*- coding: utf-8 -*-
"""
系统配置页：共享网盘路径设置、手动同步。
配置持久化到 user_data/sys_config.json，编辑功能需管理员秘钥解锁。
"""

import os

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QPushButton,
    QLabel,
    QLineEdit,
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QInputDialog,
)
from PyQt6.QtCore import QThread, pyqtSignal

try:
    from config import SYS_CONFIG_FILE, load_json_safe, save_json_safe, get_network_share_path, get_rules_edit_key
except ImportError:
    import os as _os
    _ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    SYS_CONFIG_FILE = _os.path.join(_ROOT, "user_data", "sys_config.json")

    def load_json_safe(path, default=None):
        import json
        if default is None:
            default = {}
        try:
            if _os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        return default

    def save_json_safe(path, data):
        import json
        try:
            _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except (IOError, TypeError):
            return False

    def get_network_share_path() -> str:
        cfg = load_json_safe(SYS_CONFIG_FILE, {})
        return cfg.get("network_share_path", "").strip()

    def get_rules_edit_key() -> str:
        return "admin"

from core.usage import get_tracker


# ------------------------------------------------------------------
# 后台测试网络连通性
# ------------------------------------------------------------------
class _TestNetworkWorker(QThread):
    """在后台测试网络路径是否可写。"""
    done = pyqtSignal(bool, str)  # ok, message

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            os.makedirs(self.path, exist_ok=True)
            probe = os.path.join(self.path, ".connectivity_test")
            with open(probe, "w") as f:
                f.write("test")
            os.remove(probe)
            self.done.emit(True, f"连接成功！目录可写：{self.path}")
        except OSError as e:
            self.done.emit(False, f"目录不可用：{e}")


# ------------------------------------------------------------------
# 系统配置 Tab
# ------------------------------------------------------------------
class TabSysConfig(QWidget):
    """系统配置选项卡 — 共享网盘设置。编辑需管理员秘钥。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._edit_unlocked = False
        self._editable_widgets = []
        self._setup_ui()
        self._load_saved_config()
        self._apply_edit_lock()

    # ------------------------------------------------------------------
    # 编辑锁
    # ------------------------------------------------------------------
    def _apply_edit_lock(self):
        """根据解锁状态切换表单控件和按钮的可用性。"""
        for w in self._editable_widgets:
            w.setEnabled(self._edit_unlocked)
        self.save_btn.setEnabled(self._edit_unlocked)
        self.lock_btn.setText("🔒 已锁定（点击解锁）" if not self._edit_unlocked else "🔓 已解锁（点击锁定）")

    def _toggle_unlock(self):
        """切换编辑锁定状态：锁定时要求输入秘钥。"""
        if self._edit_unlocked:
            self._edit_unlocked = False
            self._apply_edit_lock()
            return

        key, ok = QInputDialog.getText(
            self, "管理员验证", "请输入管理员秘钥：",
            echo=QLineEdit.EchoMode.Password,
        )
        if not ok or not key:
            return

        expected = get_rules_edit_key()
        if key.strip() == expected:
            self._edit_unlocked = True
            self._apply_edit_lock()
        else:
            QMessageBox.warning(self, "提示", "秘钥错误，无法解锁编辑。")

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── 编辑锁按钮 ──
        lock_row = QHBoxLayout()
        self.lock_btn = QPushButton("🔒 已锁定（点击解锁）")
        self.lock_btn.clicked.connect(self._toggle_unlock)
        lock_row.addWidget(self.lock_btn)
        lock_row.addStretch()
        layout.addLayout(lock_row)

        # ── 共享网盘设置 ──
        g_share = QGroupBox("共享网盘设置")
        form = QFormLayout(g_share)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.auto_export_check = QCheckBox("启用自动导出到共享网盘")
        self.auto_export_check.setToolTip(
            "勾选后，每次使用软件都会自动将统计数据同步到指定的网盘文件夹。"
        )
        form.addRow(self.auto_export_check)
        self._editable_widgets.append(self.auto_export_check)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("例如：\\\\server\\share\\usage  或  Z:\\统计数据")
        path_row.addWidget(self.path_edit, 1)
        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.clicked.connect(self._browse_folder)
        path_row.addWidget(self.browse_btn)
        form.addRow("网盘路径：", path_row)
        self._editable_widgets.append(self.path_edit)
        self._editable_widgets.append(self.browse_btn)

        path_hint = QLabel(
            "请输入共享网盘中的目标文件夹路径。支持 UNC 路径（\\\\server\\share）或映射盘符（Z:\\）。\n"
            "统计数据将自动以 JSON 格式写入该目录，每月一个文件（usage_YYYY-MM.json）。"
        )
        path_hint.setWordWrap(True)
        path_hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(path_hint)

        layout.addWidget(g_share)

        # ── 操作按钮 ──
        btn_row = QHBoxLayout()

        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(self.test_btn)

        self.sync_btn = QPushButton("立即同步")
        self.sync_btn.setToolTip("将本地所有统计数据立即同步到网盘")
        self.sync_btn.clicked.connect(self._sync_now)
        btn_row.addWidget(self.sync_btn)

        self.save_btn = QPushButton("保存配置")
        self.save_btn.clicked.connect(self._save_config)
        btn_row.addWidget(self.save_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── 状态条 ──
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # ── 使用说明 ──
        g_help = QGroupBox("使用说明")
        help_text = QLabel(
            "• 本地统计数据始终保存在 user_data/usage/ 目录下，不会丢失。\n"
            "• 启用自动导出后，每次软件操作都会在后台自动将统计文件同步到网盘。\n"
            "• 如网络不可用，同步会自动跳过，不影响软件正常使用。\n"
            "• 「测试连接」会尝试在目标路径下创建临时文件以验证写入权限。\n"
            "• 「立即同步」会将本地所有月份的统计文件一次性复制到网盘。\n"
            "• 配置修改需管理员秘钥解锁，防止非授权修改。"
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #444; background: #f5f5f5; padding: 6px; border-radius: 4px;")
        help_layout = QVBoxLayout(g_help)
        help_layout.addWidget(help_text)
        layout.addWidget(g_help)

        layout.addStretch()

    # ------------------------------------------------------------------
    # 配置读写
    # ------------------------------------------------------------------
    def _load_saved_config(self):
        """加载已保存的系统配置到表单。"""
        cfg = load_json_safe(SYS_CONFIG_FILE, {})
        self.auto_export_check.setChecked(bool(cfg.get("auto_export_enabled", False)))
        self.path_edit.setText(str(cfg.get("network_share_path", "")))
        share = get_network_share_path()
        if share:
            self.status_label.setText(f"当前网盘路径：{share}")
        else:
            self.status_label.setText("尚未配置共享网盘路径。配置修改需管理员解锁。")

    def _save_config(self):
        """保存当前配置。"""
        if not self._edit_unlocked:
            QMessageBox.warning(self, "提示", "配置已锁定，请先点击「🔒 已锁定」按钮并输入管理员秘钥解锁。")
            return
        cfg = {
            "auto_export_enabled": self.auto_export_check.isChecked(),
            "network_share_path": self.path_edit.text().strip(),
        }
        if save_json_safe(SYS_CONFIG_FILE, cfg):
            self.status_label.setText(f"配置已保存（{SYS_CONFIG_FILE}）")
            QMessageBox.information(self, "提示", "系统配置已保存。")
        else:
            QMessageBox.warning(self, "提示", f"保存失败，请检查目录是否可写：{SYS_CONFIG_FILE}")

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def _browse_folder(self):
        """选择共享网盘目标文件夹。"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择网盘目标文件夹",
            self.path_edit.text() or os.path.expanduser("~"),
        )
        if folder:
            self.path_edit.setText(folder)

    def _test_connection(self):
        """测试网盘路径是否可写。"""
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请先填写网盘路径。")
            return

        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中...")
        self.status_label.setText("正在测试连接...")

        self._worker = _TestNetworkWorker(path)
        self._worker.done.connect(self._on_test_done)
        self._worker.start()

    def _on_test_done(self, ok: bool, message: str):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("测试连接")
        self.status_label.setText(message)
        if ok:
            self.status_label.setStyleSheet("color: #2a7; font-weight: bold;")
            QMessageBox.information(self, "连接成功", message)
        else:
            self.status_label.setStyleSheet("color: #c33; font-weight: bold;")
            QMessageBox.warning(self, "连接失败", message)

    def _sync_now(self):
        """手动触发同步。"""
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请先填写网盘路径。")
            return

        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("同步中...")
        self.status_label.setText("正在同步...")

        tracker = get_tracker()
        result = tracker.sync_now()

        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("立即同步")
        self.status_label.setText(result)

        if "失败" in result:
            self.status_label.setStyleSheet("color: #c33; font-weight: bold;")
            QMessageBox.warning(self, "同步失败", result)
        else:
            self.status_label.setStyleSheet("color: #2a7; font-weight: bold;")
            QMessageBox.information(self, "同步完成", result)
