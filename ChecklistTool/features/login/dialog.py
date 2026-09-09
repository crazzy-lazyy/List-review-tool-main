# -*- coding: utf-8 -*-
"""
登录对话框：启动时收集员工身份信息。
收集工号、姓名、部门，支持记住上次登录信息。
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from typing import Optional

from core.usage.employee import (
    EmployeeProfile,
    load_employee_profile,
    save_employee_profile,
)

# 常见部门预置列表
_PRESET_DEPARTMENTS = [
    "主辅系统室",
    "布置室",
    "三废系统室",
    "力学室",
    "在退役室",
]

# 模块级当前员工引用（供全局访问）
_current_employee: Optional[EmployeeProfile] = None


def get_current_employee() -> Optional[EmployeeProfile]:
    """获取当前登录的员工信息。"""
    return _current_employee


def set_current_employee(employee: EmployeeProfile):
    """设置当前登录员工（供 main.py 调用）。"""
    global _current_employee
    _current_employee = employee


class LoginDialog(QDialog):
    """员工登录信息收集对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("员工登录 — 清单对比与校审工具")
        self.setMinimumWidth(420)
        self.setMaximumWidth(520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._employee: Optional[EmployeeProfile] = None
        self._setup_ui()
        self._load_last_profile()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("清单对比与校审工具 v2.0")
        title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 4px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("请输入您的员工信息，用于记录软件使用情况。\n信息仅保存在本地，不会上传到外部服务器。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; margin-bottom: 8px;")
        layout.addWidget(hint)

        # 表单
        g_form = QGroupBox("员工信息")
        form = QFormLayout(g_form)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("请输入工号，如 E001")
        self.id_edit.setMaxLength(32)
        form.addRow("工号：", self.id_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("请输入姓名")
        self.name_edit.setMaxLength(32)
        form.addRow("姓名：", self.name_edit)

        self.dept_combo = QComboBox()
        self.dept_combo.setEditable(True)
        self.dept_combo.addItem("")  # 空选项
        for dept in _PRESET_DEPARTMENTS:
            self.dept_combo.addItem(dept)
        self.dept_combo.setCurrentIndex(0)
        self.dept_combo.setMaxCount(20)  # 限制下拉项数
        form.addRow("部门：", self.dept_combo)

        layout.addWidget(g_form)

        # 记住信息
        self.remember_check = QCheckBox("记住登录信息（下次启动自动填充）")
        self.remember_check.setChecked(True)
        layout.addWidget(self.remember_check)

        layout.addSpacing(8)

        # 按钮
        btn_box = QDialogButtonBox()
        self.ok_btn = btn_box.addButton("确定", QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_btn = btn_box.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ------------------------------------------------------------------
    # 预填上次登录信息
    # ------------------------------------------------------------------
    def _load_last_profile(self):
        """加载上次保存的员工信息到表单。"""
        profile = load_employee_profile()
        if profile:
            self.id_edit.setText(profile.employee_id)
            self.name_edit.setText(profile.name)
            if profile.department:
                idx = self.dept_combo.findText(profile.department)
                if idx >= 0:
                    self.dept_combo.setCurrentIndex(idx)
                else:
                    self.dept_combo.setEditText(profile.department)
            # 光标移到工号末尾，方便直接修改
            self.id_edit.setFocus()
            self.id_edit.selectAll()

    # ------------------------------------------------------------------
    # 确定 / 取消
    # ------------------------------------------------------------------
    def _on_accept(self):
        """验证输入并接受登录。"""
        emp_id = self.id_edit.text().strip()
        emp_name = self.name_edit.text().strip()
        emp_dept = self.dept_combo.currentText().strip()

        if not emp_id:
            QMessageBox.warning(self, "提示", "请填写工号。")
            self.id_edit.setFocus()
            return

        if not emp_name:
            QMessageBox.warning(self, "提示", "请填写姓名。")
            self.name_edit.setFocus()
            return

        # 确保自定义部门出现在下拉列表中
        if emp_dept and self.dept_combo.findText(emp_dept) < 0:
            self.dept_combo.addItem(emp_dept)

        profile = EmployeeProfile(
            employee_id=emp_id,
            name=emp_name,
            department=emp_dept,
        )

        # 如果勾选了"记住"，保存到本地
        if self.remember_check.isChecked():
            save_employee_profile(profile)

        self._employee = profile
        set_current_employee(profile)
        self.accept()

    def get_employee(self) -> Optional[EmployeeProfile]:
        """获取已确认的员工信息（仅在 accept 后有效）。"""
        return self._employee
