# -*- coding: utf-8 -*-
"""
员工信息管理模块
Employee profile management.
管理当前登录员工的信息持久化，用于登录预填和使用统计。
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict

try:
    from config import EMPLOYEE_PROFILE_FILE, load_json_safe, save_json_safe
except ImportError:
    import os
    _UD = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "user_data")
    EMPLOYEE_PROFILE_FILE = os.path.join(_UD, "employee_profile.json")

    def load_json_safe(path, default=None):
        import json
        if default is None:
            default = {}
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        return default

    def save_json_safe(path, data):
        import json
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except (IOError, TypeError):
            return False


@dataclass
class EmployeeProfile:
    """员工身份信息。"""
    employee_id: str   # 工号
    name: str          # 姓名
    department: str    # 部门
    last_login: str = ""  # ISO 时间戳

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "EmployeeProfile":
        return cls(
            employee_id=str(d.get("employee_id", "")),
            name=str(d.get("name", "")),
            department=str(d.get("department", "")),
            last_login=str(d.get("last_login", "")),
        )


def save_employee_profile(profile: EmployeeProfile) -> bool:
    """保存员工信息到本地配置文件（用于下次启动预填）。"""
    profile.last_login = datetime.now().isoformat(timespec="seconds")
    return save_json_safe(EMPLOYEE_PROFILE_FILE, profile.to_dict())


def load_employee_profile() -> Optional[EmployeeProfile]:
    """加载上次保存的员工信息。文件缺失或损坏时返回 None。"""
    data = load_json_safe(EMPLOYEE_PROFILE_FILE, {})
    if data and data.get("employee_id") and data.get("name"):
        return EmployeeProfile.from_dict(data)
    return None
