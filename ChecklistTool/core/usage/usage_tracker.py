# -*- coding: utf-8 -*-
"""
使用频次追踪器
Usage frequency tracker.
单例模式，记录员工使用软件的功能和频次，支持本地存储和自动同步到共享网盘。
"""

import os
import shutil
import logging
from datetime import datetime
from typing import Dict, List, Optional

try:
    from config import USAGE_DIR, load_json_safe, save_json_safe, get_network_share_path
except ImportError:
    import os as _os
    _ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    USAGE_DIR = _os.path.join(_ROOT, "user_data", "usage")
    from config import load_json_safe, save_json_safe  # fallback, will be re-imported properly

    def get_network_share_path() -> str:
        return ""

try:
    from PyQt6.QtCore import QThread, pyqtSignal
    _HAS_PYQT = True
except ImportError:
    QThread = None
    pyqtSignal = None
    _HAS_PYQT = False

from .employee import EmployeeProfile

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 后台同步工作线程（需要 PyQt6）
# ------------------------------------------------------------------
if _HAS_PYQT:

    class _SyncWorker(QThread):
        """后台将本地使用统计文件复制到共享网盘。"""
        done = pyqtSignal(bool, str)  # ok, message

        def __init__(self, local_files: List[str], dest_dir: str):
            super().__init__()
            self.local_files = local_files
            self.dest_dir = dest_dir

        def run(self):
            try:
                os.makedirs(self.dest_dir, exist_ok=True)
                copied = 0
                for f in self.local_files:
                    if os.path.isfile(f):
                        dest = os.path.join(self.dest_dir, os.path.basename(f))
                        shutil.copy2(f, dest)
                        copied += 1
                self.done.emit(True, f"同步完成，已复制 {copied} 个文件")
            except OSError as e:
                self.done.emit(False, f"网络目录不可用：{e}")
else:
    _SyncWorker = None  # type: ignore


# ------------------------------------------------------------------
# 追踪器单例
# ------------------------------------------------------------------
class UsageTracker:
    """
    使用频次追踪器（模块级单例）。
    用法：
        tracker = get_tracker()
        tracker.start_session(employee)
        tracker.track_event("规则校验", duration_s=12.5, details={"file": "xxx.xlsx"})
    """

    def __init__(self):
        self._employee: Optional[EmployeeProfile] = None
        self._sync_worker: Optional[_SyncWorker] = None
        self._sync_pending: bool = False

    # ── 会话管理 ──────────────────────────────────────────────
    def start_session(self, employee: EmployeeProfile):
        """开始新的使用会话，记录员工信息并写入 app_launch 事件。"""
        self._employee = employee
        self.track_event("app_launch", duration_s=0, details="")

    @property
    def employee(self) -> Optional[EmployeeProfile]:
        return self._employee

    def has_employee(self) -> bool:
        return self._employee is not None

    # ── 事件记录 ──────────────────────────────────────────────
    def track_event(
        self,
        feature: str,
        duration_s: float = 0,
        details: str = "",
    ):
        """
        记录一次使用事件。
        feature: 功能名称（如 "规则校验"、"交叉对比"、"app_launch"、"export"）
        duration_s: 操作耗时（秒），0 表示不记录耗时
        details: 附加说明（如违规条数、文件数等）
        """
        if not self._employee:
            return  # 未登录时不记录

        event = {
            "employee_id": self._employee.employee_id,
            "employee_name": self._employee.name,
            "department": self._employee.department,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "feature": feature,
            "duration_s": round(duration_s, 1),
            "details": details,
        }

        # 本地保存
        try:
            self._save_local(event)
        except Exception:
            logger.exception("保存使用统计到本地失败")

        # 异步同步到网盘
        self._maybe_sync()

    # ── 本地存储 ──────────────────────────────────────────────
    def _save_local(self, event: dict):
        """追加事件到当月 JSON 文件。"""
        month_file = self._current_month_file()
        data = load_json_safe(month_file, default={"events": []})
        # 确保顶层包含员工标识（便于网盘文件自描述）
        if self._employee:
            data["employee_id"] = self._employee.employee_id
            data["employee_name"] = self._employee.name
            data["department"] = self._employee.department
        data.setdefault("events", []).append(event)
        save_json_safe(month_file, data)

    def _current_month_file(self) -> str:
        """当前月份的统计文件路径。"""
        month_str = datetime.now().strftime("%Y-%m")
        return os.path.join(USAGE_DIR, f"usage_{month_str}.json")

    def local_usage_files(self) -> List[str]:
        """获取所有本地统计文件路径（按文件名排序）。"""
        try:
            files = [
                os.path.join(USAGE_DIR, f)
                for f in os.listdir(USAGE_DIR)
                if f.startswith("usage_") and f.endswith(".json")
            ]
            files.sort()
            return files
        except OSError:
            return []

    # ── 网盘同步 ──────────────────────────────────────────────
    def _maybe_sync(self):
        """如果配置了网盘路径且无正在运行的同步任务，则启动后台同步。"""
        share_path = get_network_share_path()
        if not share_path:
            return

        if _SyncWorker is None:
            return  # PyQt6 不可用时跳过

        if self._sync_worker and self._sync_worker.isRunning():
            self._sync_pending = True
            return

        self._do_sync(share_path)

    def _do_sync(self, dest_dir: str):
        """启动后台同步线程。"""
        if _SyncWorker is None:
            return  # PyQt6 不可用时跳过后台同步
        local_files = self.local_usage_files()
        if not local_files:
            return

        self._sync_pending = False
        self._sync_worker = _SyncWorker(local_files, dest_dir)
        self._sync_worker.done.connect(self._on_sync_done)
        self._sync_worker.start()

    def _on_sync_done(self, ok: bool, message: str):
        """同步完成回调。"""
        if ok:
            logger.info("网盘同步: %s", message)
        else:
            logger.warning("网盘同步失败: %s", message)

        # 如果同步期间有新事件，再次触发同步
        if self._sync_pending:
            share_path = get_network_share_path()
            if share_path:
                self._do_sync(share_path)

    def sync_now(self) -> str:
        """
        手动触发全量同步（供系统配置页"立即同步"按钮使用）。
        返回结果描述字符串。
        """
        share_path = get_network_share_path()
        if not share_path:
            return "尚未配置共享网盘路径，请先在系统配置页中设置。"

        if self._sync_worker and _SyncWorker is not None and self._sync_worker.isRunning():
            return "同步正在进行中，请稍后再试。"

        local_files = self.local_usage_files()
        if not local_files:
            return "本地暂无统计数据可同步。"

        # 同步执行（不在后台），因为用户点击了按钮期望立即得到结果
        try:
            os.makedirs(share_path, exist_ok=True)
            copied = 0
            for f in local_files:
                if os.path.isfile(f):
                    dest = os.path.join(share_path, os.path.basename(f))
                    shutil.copy2(f, dest)
                    copied += 1
            return f"同步完成，已将 {copied} 个统计文件复制到：{share_path}"
        except OSError as e:
            return f"同步失败，网络目录不可用：{e}"


# ------------------------------------------------------------------
# 模块级单例
# ------------------------------------------------------------------
_tracker: Optional[UsageTracker] = None


def get_tracker() -> UsageTracker:
    """获取 UsageTracker 单例。"""
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
