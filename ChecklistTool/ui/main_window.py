# -*- coding: utf-8 -*-
"""
主窗口：集成规则校验、交叉对比、规则库、结果报告等选项卡。
（已移除“版本对比”界面：两文件对比可通过“交叉对比”添加 1 个待对比文件实现。）
"""

import sys
import os
import time

# 将项目根目录加入路径，便于各模块导入 config、core
if getattr(sys, "frozen", False):
    _root = os.path.dirname(sys.executable)
else:
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QLabel,
    QStatusBar,
    QMessageBox,
)
from PyQt6.QtCore import Qt

from features.rule_validate import TabRuleValidate
from features.cross_compare import TabCrossCompare
from features.rules_lib import TabRulesLib
from features.results import TabResults
from features.ai_config import TabAIConfig
from features.sys_config import TabSysConfig

# 功能名称映射（与 Tab 索引对应，用于使用统计）
_FEATURE_NAMES = {
    0: "规则校验",
    1: "交叉对比",
    2: "规则库",
    3: "结果报告",
    4: "AI 配置",
    5: "系统配置",
}

try:
    from core.usage import get_tracker
except ImportError:
    get_tracker = None


class MainWindow(QMainWindow):
    """清单对比与校审工具主窗口。"""

    def __init__(self):
        super().__init__()
        try:
            from config import APP_VERSION
            self.setWindowTitle(f"清单对比与校审工具 v{APP_VERSION}")
        except Exception:
            self.setWindowTitle("清单对比与校审工具")
        self.setMinimumSize(900, 650)
        self.resize(1000, 700)
        self._tab_results = None
        self._tab_rules = None
        self._employee = None
        self._active_tab_index = -1
        self._tab_start_time = time.time()
        self._app_start_time = time.time()
        self._setup_ui()

    def set_employee(self, employee):
        """设置当前登录员工（由 main.py 在登录后调用）。"""
        self._employee = employee
        if employee is not None:
            self.statusBar().showMessage(
                f"当前用户：{employee.name}（{employee.employee_id}） | 就绪"
            )

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        try:
            from config import APP_VERSION
            layout.addWidget(QLabel(f"清单对比与校审工具 v{APP_VERSION}"))
        except Exception:
            layout.addWidget(QLabel("清单对比与校审工具"))

        tabs = QTabWidget()
        tab_validate = TabRuleValidate()
        tab_validate.result_ready.connect(self._on_validate_result)
        tabs.addTab(tab_validate, "规则校验")

        tab_cross = TabCrossCompare()
        tab_cross.result_ready.connect(self._on_cross_result)
        tabs.addTab(tab_cross, "交叉对比")

        self._tab_rules = TabRulesLib()
        self._tab_rules.rules_updated.connect(tab_validate.refresh_rules_list)
        tabs.addTab(self._tab_rules, "规则库")

        self._tab_results = TabResults()
        tabs.addTab(self._tab_results, "结果报告")

        tab_ai_config = TabAIConfig()
        tabs.addTab(tab_ai_config, "AI 配置")

        tab_sys_config = TabSysConfig()
        tabs.addTab(tab_sys_config, "系统配置")

        # Tab 切换埋点
        tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(tabs)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

    def _on_validate_result(self, df, payload):
        if isinstance(payload, dict):
            violations = payload.get("violations", []) or []
            unvalidated_rows = payload.get("unvalidated_rows", []) or []
        else:
            violations = payload or []
            unvalidated_rows = []
        self._tab_results.set_validation_result(df, violations, unvalidated_rows=unvalidated_rows)
        self.statusBar().showMessage(
            f"校验完成，违规 {len(violations)} 条，未进入验证 {len(unvalidated_rows)} 行"
        )
        # 使用统计埋点
        self._track_feature("规则校验", f"违规 {len(violations)} 条")

    def _on_cross_result(self, results):
        if not results:
            return
        self._tab_results.set_diff_result(results[0])
        if len(results) > 1:
            self.statusBar().showMessage(f"交叉对比完成，共 {len(results)} 组结果，已展示第一组")
        else:
            self.statusBar().showMessage("交叉对比完成，请查看结果报告页")
        # 使用统计埋点
        self._track_feature("交叉对比", f"{len(results)} 组结果")

    # ── Tab 切换追踪 ──────────────────────────────────────────
    def _on_tab_changed(self, index: int):
        """记录上一个 Tab 的使用时长，开始计时新 Tab。"""
        # 记录上一个 Tab 的耗时
        if self._active_tab_index >= 0:
            elapsed = time.time() - self._tab_start_time
            feature = _FEATURE_NAMES.get(self._active_tab_index, f"Tab{self._active_tab_index}")
            self._track_feature(feature, f"停留 {elapsed:.0f} 秒", duration_s=elapsed)

        self._active_tab_index = index
        self._tab_start_time = time.time()

    def closeEvent(self, event):
        """窗口关闭时记录最后活跃 Tab 的耗时和应用退出事件。"""
        # 记录当前 Tab
        if self._active_tab_index >= 0:
            elapsed = time.time() - self._tab_start_time
            feature = _FEATURE_NAMES.get(self._active_tab_index, f"Tab{self._active_tab_index}")
            self._track_feature(feature, f"停留 {elapsed:.0f} 秒", duration_s=elapsed)

        # 记录应用退出
        session_elapsed = time.time() - self._app_start_time
        self._track_feature("app_exit", f"会话 {session_elapsed:.0f} 秒", duration_s=session_elapsed)

        event.accept()

    def _track_feature(self, feature: str, details: str = "", duration_s: float = 0):
        """统一的使用统计埋点入口。"""
        if get_tracker is None:
            return
        try:
            tracker = get_tracker()
            if tracker.has_employee():
                tracker.track_event(feature, duration_s=duration_s, details=details)
        except Exception:
            pass  # 埋点失败不影响正常使用
