# -*- coding: utf-8 -*-
"""
核心业务逻辑包（按功能块分子包）
- core.parsers: 表格解析
- core.diff: 对比引擎
- core.rules: 规则引擎
- core.export: 导出引擎
- core.ai: AI 服务（自然语言→规则、列名语义匹配）
- core.usage: 使用统计与员工管理
"""

__all__ = []

# 各子包独立导入，单个失败不影响其他模块加载
try:
    from .parsers import load_table_from_file, get_columns_from_file, ParserError
    __all__ += ["load_table_from_file", "get_columns_from_file", "ParserError"]
except ImportError:
    load_table_from_file = get_columns_from_file = ParserError = None

try:
    from .diff import DiffEngine, DiffResult, cross_compare
    __all__ += ["DiffEngine", "DiffResult", "cross_compare"]
except ImportError:
    DiffEngine = DiffResult = cross_compare = None

try:
    from .rules import RuleEngine, RuleNode, ValidationRule, RuleViolation
    __all__ += ["RuleEngine", "RuleNode", "ValidationRule", "RuleViolation"]
except ImportError:
    RuleEngine = RuleNode = ValidationRule = RuleViolation = None

try:
    from .export import (
        export_to_excel,
        export_to_csv,
        export_to_pdf,
        export_diff_result,
        ExportError,
    )
    __all__ += ["export_to_excel", "export_to_csv", "export_to_pdf", "export_diff_result", "ExportError"]
except ImportError:
    export_to_excel = export_to_csv = export_to_pdf = export_diff_result = ExportError = None

try:
    from .ai import (
        AIClient,
        AIClientError,
        get_client as get_ai_client,
        parse_natural_language_to_rule,
        match_column_names_semantically,
    )
    __all__ += ["AIClient", "AIClientError", "get_ai_client", "parse_natural_language_to_rule", "match_column_names_semantically"]
except ImportError:
    AIClient = AIClientError = get_ai_client = parse_natural_language_to_rule = match_column_names_semantically = None

try:
    from .usage import (
        EmployeeProfile,
        save_employee_profile,
        load_employee_profile,
        UsageTracker,
        get_tracker,
    )
    __all__ += ["EmployeeProfile", "save_employee_profile", "load_employee_profile", "UsageTracker", "get_tracker"]
except ImportError:
    EmployeeProfile = save_employee_profile = load_employee_profile = UsageTracker = get_tracker = None
