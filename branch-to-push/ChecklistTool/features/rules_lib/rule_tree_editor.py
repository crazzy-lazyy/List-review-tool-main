# -*- coding: utf-8 -*-
"""
规则条件树可视化编辑器（拖拽构建）。
将 RuleNode 树与 QTreeWidget 绑定，支持添加/删除/编辑节点，逻辑与/或。
同时在条件树旁渲染自上而下决策流程图，双向高亮联动。
"""

import math
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QComboBox,
    QLineEdit,
    QLabel,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QMessageBox,
    QSplitter,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsPolygonItem,
    QGraphicsPathItem,
    QGraphicsTextItem,
    QGraphicsEllipseItem,
    QToolTip,
    QStyleOptionGraphicsItem,
    QToolButton,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QSizeF
from PyQt6.QtGui import (
    QColor,
    QPen,
    QBrush,
    QPainter,
    QPainterPath,
    QFont,
    QFontMetrics,
    QPolygonF,
    QTransform,
)

from core.rules import (
    RuleNode,
    RuleEngine,
    format_escaped_list,
    parse_escaped_list,
)


MAX_NODE_LABEL_CHARS = 120

# 字段下拉框中表示「该节点不配置具体条件（纯根/组节点）」的特殊项
_ROOT_FIELD_LABEL = "（无/根节点）"


def _op_label(op: str) -> str:
    m = {
        "eq": "等于 (=)",
        "ne": "不等于 (≠)",
        "gt": "大于 (>)",
        "ge": "大于等于 (≥)",
        "lt": "小于 (<)",
        "le": "小于等于 (≤)",
        "in": "属于/在列表中",
        "not_in": "不属于/不在列表中",
        "not_empty": "非空",
        "empty": "为空",
        "is_num": "是数字",
        "regex": "正则匹配",
        "contains": "包含",
    }
    return m.get(op, op)


def _logic_label(logic: str) -> str:
    return "且(and)" if logic == "and" else ("或(or)" if logic == "or" else str(logic))


def _format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        # 列表值（如 in/not_in）更易读的展示
        return "[" + ", ".join(str(x) for x in value) + "]"
    return str(value)


def _elide_text(text: str, max_chars: int = MAX_NODE_LABEL_CHARS) -> str:
    """超长文本截断，避免树节点内容把界面撑宽。"""
    s = str(text or "")
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "..."


def _format_leaf_brief(node: RuleNode) -> str:
    if not node or not getattr(node, "field", ""):
        return "根"
    v = _format_value(getattr(node, "value", None))
    v_part = f" {v}" if v else ""
    rn = (getattr(node, "rule_name", "") or "").strip()
    rn_part = f" | 规则名:{rn}" if rn else ""
    return f"{node.field} {_op_label(node.operator)}{v_part}{rn_part}"


def _collect_leaf_briefs(node: RuleNode, limit: int = 3) -> list:
    """收集若干叶子条件的简短预览，用于条件组节点的摘要显示。"""
    briefs = []
    stack = [node]
    while stack and len(briefs) < limit:
        n = stack.pop(0)
        children = list(getattr(n, "children", []) or [])
        if children:
            stack.extend(children)
        else:
            # 叶子：有 field 才算“具体条件”；否则跳过（根节点）
            if getattr(n, "field", ""):
                briefs.append(_format_leaf_brief(n))
    return briefs


def _count_conditions(node: RuleNode) -> int:
    """统计该节点下“叶子条件”的数量。"""
    if not node:
        return 0
    children = list(getattr(node, "children", []) or [])
    if children:
        return sum(_count_conditions(c) for c in children)
    return 1 if getattr(node, "field", "") else 0


class RuleNodeEditDialog(QDialog):
    """编辑单个条件节点：字段、运算符、值、逻辑。"""

    def __init__(self, node: RuleNode, columns: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑条件节点")
        # 限制弹窗宽度，防止超长字段名/值把窗口撑满屏。
        self.setMinimumWidth(520)
        self.setMaximumWidth(900)
        self.resize(680, 280)
        self.node = node
        self.columns = columns or []
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout(self)
        self.field_combo = QComboBox()
        self.field_combo.setEditable(True)  # 可手动输入列名（如 系统|专业），无需先加载文件
        self.field_combo.setMinimumContentsLength(24)
        self.field_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.field_combo.addItem(_ROOT_FIELD_LABEL, "")
        for c in self.columns:
            self.field_combo.addItem(c, c)
        try:
            self.field_combo.view().setTextElideMode(Qt.TextElideMode.ElideRight)
        except Exception:
            pass
        layout.addRow("字段（可下拉选择或直接输入列名）:", self.field_combo)
        self.op_combo = QComboBox()
        for op in RuleEngine.OPERATORS:
            self.op_combo.addItem(_op_label(op), op)
        self.op_combo.currentIndexChanged.connect(self._sync_value_input_state)
        layout.addRow("运算符:", self.op_combo)
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText(
            r"值（列表用逗号分隔；值内逗号写作 \,；is_num/为空/非空无需填写）"
        )
        layout.addRow("值:", self.value_edit)
        self.logic_combo = QComboBox()
        self.logic_combo.addItem("且 (and)", "and")
        self.logic_combo.addItem("或 (or)", "or")
        self.logic_combo.setToolTip(
            "and且：须同时满足所有子条件；\nor或：存在满足的子条件。")
        layout.addRow("子节点逻辑:", self.logic_combo)
        logic_hint = QLabel("and且：须同时满足所有子条件；or或：存在满足的子条件。")
        logic_hint.setWordWrap(True)
        logic_hint.setStyleSheet("color: #6b7280;")
        layout.addRow(logic_hint)
        self.rule_name_edit = QLineEdit()
        self.rule_name_edit.setPlaceholderText("规则名称（用于报告）")
        layout.addRow("规则名称:", self.rule_name_edit)

        # 回填：有预选项则选中，否则设为可编辑的当前值
        idx = self.field_combo.findData(self.node.field)
        if idx >= 0:
            self.field_combo.setCurrentIndex(idx)
        elif self.node.field:
            self.field_combo.setCurrentText(self.node.field)
        idx = self.op_combo.findData(self.node.operator)
        if idx >= 0:
            self.op_combo.setCurrentIndex(idx)
        if self.node.value is not None:
            if isinstance(self.node.value, list):
                self.value_edit.setText(format_escaped_list(self.node.value))
            else:
                self.value_edit.setText(str(self.node.value))
        self.logic_combo.setCurrentIndex(0 if self.node.logic == "and" else 1)
        self.rule_name_edit.setText(self.node.rule_name or "")
        self._sync_value_input_state()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _resolve_field_value(self) -> str:
        """解析字段值：以当前文本为准；空文本或「（无/根节点）」表示空字段。

        修复：下拉框可手动输入自定义列名，此时 currentIndex 可能仍停留在
        旧选项（如「（无/根节点）」，data 为空串）上；若按 itemData 取值，
        用户刚输入的字段名会被丢弃，保存后 field 为空、卡片重新显示「根」。
        """
        text = self.field_combo.currentText().strip()
        if not text or text == _ROOT_FIELD_LABEL:
            return ""
        return text

    @staticmethod
    def _operator_requires_value(op: str) -> bool:
        return op in {"eq", "in", "not_in"}

    def _sync_value_input_state(self, _index=None):
        """无参数运算符禁用值输入框，避免误以为 is_num 需要比较值。"""
        op = self.op_combo.currentData() or "eq"
        self.value_edit.setEnabled(op not in {"is_num", "empty", "not_empty"})

    def _on_accept(self):
        # 仅当该节点配置了字段条件时，才校验“值是否必填”。
        field_val = self._resolve_field_value()
        op = self.op_combo.currentData() or "eq"
        raw_val = self.value_edit.text().strip()
        if (field_val or "").strip() and self._operator_requires_value(op) and raw_val == "":
            QMessageBox.warning(self, "提示", "当前运算符需要填写“值”，否则条件无效。")
            return
        self.accept()

    def get_node(self) -> RuleNode:
        val = self.value_edit.text().strip()
        op = self.op_combo.currentData() or "eq"
        if op in {"in", "not_in"}:
            value = parse_escaped_list(val) if val else None
        else:
            value = val if val else None
        # 优先用下拉选中项 data；手动输入时回退文本
        field_val = self._resolve_field_value()
        self.node.field = field_val or ""
        self.node.operator = op
        self.node.value = value
        self.node.logic = self.logic_combo.currentData() or "and"
        self.node.rule_name = self.rule_name_edit.text().strip()
        return self.node


def _node_to_item(node: RuleNode) -> QTreeWidgetItem:
    """将 RuleNode 转为 QTreeWidgetItem（仅当前节点，不递归）。"""
    if node.children:
        rn = (node.rule_name or "").strip()
        count = _count_conditions(node)
        briefs = _collect_leaf_briefs(node, limit=3)
        briefs_part = (" | 示例: " + "；".join(briefs) + (" …" if count > len(briefs) else "")) if briefs else ""
        rn_part = f" | 规则名:{rn}" if rn else ""
        full_label = f"条件组({_logic_label(node.logic)}) | 条件数:{count}{rn_part}{briefs_part}"
    else:
        full_label = _format_leaf_brief(node)
    item = QTreeWidgetItem([_elide_text(full_label)])
    item.setToolTip(0, full_label)
    item.setData(0, Qt.ItemDataRole.UserRole, node)
    return item


def _build_children(item: QTreeWidgetItem, node: RuleNode):
    for c in node.children:
        child_item = _node_to_item(c)
        item.addChild(child_item)
        _build_children(child_item, c)


def _item_to_node(item: QTreeWidgetItem) -> RuleNode:
    """从 QTreeWidgetItem 恢复 RuleNode（递归）。"""
    node = item.data(0, Qt.ItemDataRole.UserRole)
    if not isinstance(node, RuleNode):
        node = RuleNode()
    node.children = []
    for i in range(item.childCount()):
        node.children.append(_item_to_node(item.child(i)))
    return node


# ---------------------------------------------------------------------------
# 条件流程图：从 RuleNode JSON 渲染自上而下决策树
# ---------------------------------------------------------------------------

# 色板
_C_BG_ROOT = QColor("#e0e7ff")       # 根矩形
_C_BORDER_ROOT = QColor("#6366f1")
_C_BG_LOGIC = QColor("#fef3c7")       # 逻辑菱形
_C_BORDER_LOGIC = QColor("#f59e0b")
_C_BG_LEAF = QColor("#f8fafc")        # 叶子条件圆角矩形
_C_BORDER_LEAF = QColor("#cbd5e1")
_C_BG_PASS = QColor("#d1fae5")        # 通过
_C_BORDER_PASS = QColor("#10b981")
_C_BG_FAIL = QColor("#fee2e2")        # 不通过
_C_BORDER_FAIL = QColor("#ef4444")
_C_TEXT = QColor("#1f2937")
_C_TEXT_MUTED = QColor("#6b7280")
_C_HIGHLIGHT = QColor("#6366f1")      # 高亮边框
_C_CONNECTOR = QColor("#94a3b8")      # 连线

# 尺寸常量
_NODE_W = 200                         # 矩形节点最小宽度
_NODE_H = 60                          # 矩形节点最小高度
_DIAMOND_W = 210                      # 菱形节点最小宽度
_DIAMOND_H = 90                       # 菱形节点最小高度
_VGAP = 110                           # 上下两层间距（父节点底部 → 子节点顶部）
_HGAP = 90                            # 同层兄弟节点（平行条件）之间的间距
_MAX_NODE_W = 420                     # 矩形节点最大宽度（超出自动换行）
_DIAMOND_WRAP_W = 340                 # 菱形节点文本自动换行宽度
_TERMINAL_W = 96                      # 终端节点（通过/报错）宽度
_TERMINAL_H = 40                      # 终端节点高度

_FONT_NODE = QFont("Microsoft YaHei", 9)
_FONT_LABEL = QFont("Microsoft YaHei", 8)


def _wrap_text(text: str, font: QFont, max_w: int) -> list:
    """按像素宽度自动换行，返回多行；不截断内容。"""
    fm = QFontMetrics(font)
    if not text:
        return [""]
    if fm.horizontalAdvance(text) <= max_w:
        return [text]
    lines = []
    current = ""
    for ch in text:
        if ch in "\n":
            if current:
                lines.append(current)
            current = ""
            continue
        if fm.horizontalAdvance(current + ch) > max_w and current:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return lines or [text]


def _calc_text_block(text: str, wrap_w: int) -> tuple:
    """按宽度换行并测量文本块，返回 (lines, text_w, text_h)。"""
    fm = QFontMetrics(_FONT_NODE)
    lines = _wrap_text(text, _FONT_NODE, wrap_w)
    text_w = max((fm.horizontalAdvance(l) for l in lines), default=0)
    text_h = len(lines) * fm.lineSpacing()
    return lines, text_w, text_h


def _calc_rect_size(text: str, min_w: int = _NODE_W, min_h: int = _NODE_H,
                    max_w: int = _MAX_NODE_W) -> tuple:
    """矩形节点（根/条件组/终端）尺寸。测量与绘制共用，保证布局与渲染一致。"""
    _, text_w, text_h = _calc_text_block(str(text), max_w - 24)
    w = max(min_w, min(max_w, text_w + 28))
    h = max(min_h, text_h + 18)
    return w, h


def _calc_diamond_size(lines: list) -> tuple:
    """菱形节点尺寸。测量与绘制共用，保证布局与渲染一致。"""
    fm = QFontMetrics(_FONT_NODE)
    text_w = max((fm.horizontalAdvance(l) for l in lines), default=0)
    text_h = len(lines) * fm.lineSpacing()
    w = max(_DIAMOND_W, min(_MAX_NODE_W + 120, text_w + 100))
    h = max(_DIAMOND_H, text_h + 56)
    return w, h


def _node_id(node: RuleNode) -> int:
    """用 id 作为节点唯一标识。"""
    return id(node)


class _FlowchartNodeBase(QGraphicsRectItem):
    """流程图节点基类，管理高亮和 hover 联动。"""

    def __init__(self, node_id: int, node: RuleNode, parent=None):
        super().__init__(0, 0, 1, 1, parent)
        self._node_id = node_id
        self._rule_node = node
        self._highlighted = False
        self._default_border = QPen(QColor("#ccc"), 1)
        self._default_bg = QColor("#fff")
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    @property
    def node_id(self):
        return self._node_id

    @property
    def rule_node(self):
        return self._rule_node

    def set_highlight(self, on: bool):
        self._highlighted = on
        if on:
            pen = QPen(_C_HIGHLIGHT, 2.5)
            self.setPen(pen)
        else:
            self.setPen(self._default_border)
        self.update()

    def hoverEnterEvent(self, event):
        try:
            self.set_highlight(True)
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and hasattr(view, "_on_node_hover"):
                view._on_node_hover(self._node_id, True)
            if self._rule_node:
                tip = _format_leaf_brief(self._rule_node) if self._rule_node.field else _logic_label(self._rule_node.logic)
                QToolTip.showText(event.screenPos(), tip)
        except RuntimeError:
            pass
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        try:
            self.set_highlight(False)
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and hasattr(view, "_on_node_hover"):
                view._on_node_hover(self._node_id, False)
        except RuntimeError:
            pass
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        try:
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and hasattr(view, "_on_node_click"):
                view._on_node_click(self._node_id)
        except RuntimeError:
            pass
        super().mousePressEvent(event)


class _FlowchartRectNode(_FlowchartNodeBase):
    """矩形节点：根节点 / 条件组 / 终端结果（多行文本与自适应宽高）。"""

    def __init__(self, node_id, node, text, color_bg, color_border, is_root=False,
                 rule_node=None, parent=None,
                 min_w=_NODE_W, min_h=_NODE_H, max_w=_MAX_NODE_W):
        super().__init__(node_id, rule_node or node, parent)
        self._text = str(text)
        self._default_bg = color_bg
        self._default_border = QPen(color_border, 1.5)
        self.setPen(self._default_border)
        self.setBrush(QBrush(color_bg))
        # 尺寸与布局测量共用同一公式，保证不重叠
        w, h = _calc_rect_size(self._text, min_w=min_w, min_h=min_h, max_w=max_w)
        self.setRect(0, 0, w, h)
        # 文本预先按宽度换行后写入（QGraphicsTextItem 默认不自动换行）
        display = "\n".join(_wrap_text(self._text, _FONT_NODE, max_w - 24))
        self._label = QGraphicsTextItem(display, self)
        self._label.setFont(_FONT_NODE)
        self._label.setDefaultTextColor(_C_TEXT)
        label_w = self._label.boundingRect().width()
        label_h = self._label.boundingRect().height()
        self._label.setPos((w - label_w) / 2, (h - label_h) / 2)

    def boundingRect(self) -> QRectF:
        return self.rect()

    def paint(self, painter, option, widget=None):
        rect = self.rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRoundedRect(rect, 6, 6)


class _FlowchartDiamondNode(_FlowchartNodeBase):
    """菱形节点：逻辑组 (AND/OR) + 条件（多行文本与自适应宽高）。"""

    def __init__(self, node_id, node, lines, rule_node=None, parent=None):
        super().__init__(node_id, rule_node or node, parent)
        self._lines = lines or [""]
        self._default_bg = _C_BG_LOGIC
        self._default_border = QPen(_C_BORDER_LOGIC, 1.5)
        self.setPen(self._default_border)
        self.setBrush(QBrush(_C_BG_LOGIC))

        # 尺寸与布局测量共用同一公式；宽高留足内边距，文字不压菱形边框
        w, h = _calc_diamond_size(self._lines)
        self._w = w
        self._h = h
        self.setRect(0, 0, w, h)

        # 文字（垂直居中，逐行排布）
        line_h = QFontMetrics(_FONT_NODE).lineSpacing()
        total_text_h = len(self._lines) * line_h
        y = (h - total_text_h) / 2
        for i, line in enumerate(self._lines):
            item = QGraphicsTextItem(line, self)
            item.setFont(_FONT_NODE)
            item.setDefaultTextColor(_C_TEXT)
            item.setPos((w - item.boundingRect().width()) / 2, y + i * line_h)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def shape(self):
        path = QPainterPath()
        path.moveTo(self._w / 2, 0)
        path.lineTo(self._w, self._h / 2)
        path.lineTo(self._w / 2, self._h)
        path.lineTo(0, self._h / 2)
        path.closeSubpath()
        return path

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        w, h = self._w, self._h
        poly = QPolygonF([QPointF(w/2, 0), QPointF(w, h/2), QPointF(w/2, h), QPointF(0, h/2)])
        painter.drawPolygon(poly)


class _FlowchartLeafNode(_FlowchartNodeBase):
    """圆角矩形节点：叶子条件（支持多行自动换行与自适应宽高）。"""

    def __init__(self, node_id, node, text, rule_node=None, parent=None):
        super().__init__(node_id, rule_node or node, parent)
        self._text = text
        self._default_bg = _C_BG_LEAF
        self._default_border = QPen(_C_BORDER_LEAF, 1.5)
        self.setPen(self._default_border)
        self.setBrush(QBrush(_C_BG_LEAF))
        # 按最大宽度自动换行（不截断）
        lines = _wrap_text(text, _FONT_NODE, _MAX_NODE_W - 24)
        line_h = QFontMetrics(_FONT_NODE).lineSpacing()
        max_w = max((_text_width(l, _FONT_NODE) for l in lines), default=60)
        w = max(_NODE_W, min(_MAX_NODE_W, max_w + 24))
        h = max(_NODE_H, len(lines) * line_h + 12)
        self.setRect(0, 0, w, h)
        for i, line in enumerate(lines):
            item = QGraphicsTextItem(line, self)
            item.setFont(_FONT_NODE)
            item.setDefaultTextColor(_C_TEXT)
            item.setPos((w - item.boundingRect().width()) / 2, 6 + i * line_h)

    def boundingRect(self) -> QRectF:
        return self.rect()

    def paint(self, painter, option, widget=None):
        rect = self.rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRoundedRect(rect, 8, 8)


def _text_width(text: str, font: QFont) -> int:
    fm = QFontMetrics(font)
    return fm.horizontalAdvance(str(text))


def _build_node_text(node: RuleNode) -> str:
    """构建叶子节点显示文本。"""
    if not node.field:
        return _logic_label(node.logic)
    v = _format_value(node.value)
    v_part = f" {v}" if v else ""
    return f"{node.field} {_op_label(node.operator)}{v_part}"


def _build_diamond_lines(node: RuleNode, wrap_w: int = 0) -> list:
    """构建菱形节点显示文本行，可选按 wrap_w 自动换行以完整展示内容。"""
    raw_lines = []
    if node.field:
        v = _format_value(node.value)
        v_part = f" {v}" if v else ""
        raw_lines.append(f"{node.field} {_op_label(node.operator)}{v_part}")
    raw_lines.append(_logic_label(node.logic))
    if wrap_w <= 0:
        return raw_lines
    wrapped = []
    for line in raw_lines:
        wrapped.extend(_wrap_text(line, _FONT_NODE, wrap_w))
    return wrapped


def _build_root_diamond_lines(node: RuleNode, rule_name: str,
                              wrap_w: int = _DIAMOND_WRAP_W) -> list:
    """根节点自身配置了字段条件时的菱形文本行：规则名 + 字段/运算符/值 + 子逻辑。

    根节点带 field 时不能只渲染规则名矩形，否则该条件的字段、运算符和值
    （单条件规则的全部内容）在流程图中完全不可见。
    """
    raw_lines = []
    rn = (rule_name or "").strip()
    if rn:
        raw_lines.append(rn)
    v = _format_value(node.value)
    v_part = f" {v}" if v else ""
    raw_lines.append(f"{node.field} {_op_label(node.operator)}{v_part}")
    raw_lines.append(_logic_label(node.logic))
    if wrap_w <= 0:
        return raw_lines
    wrapped = []
    for line in raw_lines:
        wrapped.extend(_wrap_text(line, _FONT_NODE, wrap_w))
    return wrapped


class ConditionFlowchart(QGraphicsView):
    """条件流程图视图：从 RuleNode 渲染自上而下决策树，支持缩放和双向高亮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 允许鼠标拖拽平移（点击节点仍可触发，拖拽空白处平移）
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._zoom = 1.0
        self._user_zoomed = False    # 用户是否已手动缩放（避免 resize 重置）
        self._node_items = {}       # node_id -> QGraphicsItem
        self._tree_items = {}       # node_id -> QTreeWidgetItem
        self._rule_name = ""
        self._on_tree_highlight = None  # callback(node_id, on)
        self._on_tree_click = None      # callback(node_id)
        self.setMinimumHeight(180)

    def set_highlight_callback(self, cb):
        self._on_tree_highlight = cb

    def set_click_callback(self, cb):
        self._on_tree_click = cb

    def _on_node_hover(self, node_id, on):
        """流程图节点 hover → 高亮条件树对应节点。"""
        if self._on_tree_highlight:
            self._on_tree_highlight(node_id, on)

    def _on_node_click(self, node_id):
        """流程图节点点击 → 高亮/展开条件树对应节点。"""
        if self._on_tree_click:
            self._on_tree_click(node_id)

    def highlight_node(self, node_id: int, on: bool):
        """外部调用：高亮指定节点。"""
        item = self._node_items.get(node_id)
        if not item:
            return
        try:
            item.set_highlight(on)
        except RuntimeError:
            # C++ 对象已删除（场景重建期间）
            self._node_items.pop(node_id, None)

    def build_from_node(self, root: RuleNode, rule_name: str = ""):
        """从 RuleNode 构建流程图。"""
        # 先清空引用再清场景，避免访问已删除的 C++ 对象
        self._node_items.clear()
        self._scene.clear()
        self._rule_name = rule_name or "未命名规则"
        # 重置缩放标记，让新规则加载后自动 fit
        self._user_zoomed = False
        self._zoom = 1.0
        self.setTransform(QTransform().scale(1.0, 1.0))

        if not root:
            text = self._scene.addText("条件为空")
            text.setDefaultTextColor(_C_TEXT_MUTED)
            text.setFont(_FONT_NODE)
            return

        try:
            self._layout_and_render(root)
            # 扩大场景矩形范围，允许用户在流程图周围大范围拖拽平移
            # 修复问题：默认场景矩形仅覆盖图形项，拖拽超出范围后无法继续平移
            rect = self._scene.itemsBoundingRect()
            if not rect.isEmpty():
                margin = max(rect.width(), rect.height(), 2000) * 2
                self._scene.setSceneRect(
                    rect.x() - margin,
                    rect.y() - margin,
                    rect.width() + 2 * margin,
                    rect.height() + 2 * margin,
                )
            # 加载后自动适配视图（仅首次，用户缩放后不再重置）
            self.fit_in_view()
        except Exception as e:
            self._scene.clear()
            text = self._scene.addText(f"条件树解析失败: {e}")
            text.setDefaultTextColor(QColor("#f44"))
            text.setFont(_FONT_NODE)

    def _measure_node_size(self, node: RuleNode, is_root=False) -> tuple:
        """估算节点尺寸（不创建 QGraphicsItem），返回 (w, h)。与绘制共用公式。"""
        if getattr(node, "field", ""):
            # 根节点带字段条件时同样按菱形测量（文本含规则名行），与渲染一致
            lines = (_build_root_diamond_lines(node, self._rule_name) if is_root
                     else _build_diamond_lines(node, _DIAMOND_WRAP_W))
            return _calc_diamond_size(lines)
        if is_root:
            return _calc_rect_size(self._rule_name or "未命名规则")
        return _calc_rect_size(f"条件组({_logic_label(node.logic)})")

    def _measure_subtree(self, node: RuleNode, is_root=False) -> dict:
        """递归测量子树尺寸，返回布局信息 dict。"""
        has_field = bool(getattr(node, "field", ""))
        children = list(getattr(node, "children", []) or [])
        node_w, node_h = self._measure_node_size(node, is_root=is_root)

        if not children:
            # 叶子：节点 + 下方「是→通过 / 否→报错」一排两个终端
            row_w = _TERMINAL_W * 2 + _HGAP
            w = max(node_w, row_w)
            h = node_h + _VGAP + _TERMINAL_H
            return {"w": w, "h": h, "node_w": node_w, "node_h": node_h, "children": []}

        child_measures = [self._measure_subtree(c) for c in children]
        children_w = sum(m["w"] for m in child_measures) + _HGAP * (len(child_measures) - 1)
        children_h = max(m["h"] for m in child_measures)

        if has_field:
            # 条件+子节点：子节点块整体左移，右侧整列预留给「否→报错」终端，
            # 保证终端不会挤进右侧兄弟子树
            combo_w = children_w + _HGAP + _TERMINAL_W
            w = max(node_w, combo_w)
            h = node_h + _VGAP + max(children_h, _TERMINAL_H)
        else:
            # 条件组：子节点在下方居中，全部通过后还需接「通过」终端
            w = max(node_w, children_w)
            h = node_h + _VGAP + children_h + _VGAP + _TERMINAL_H

        return {"w": w, "h": h, "node_w": node_w, "node_h": node_h, "children": child_measures}

    def _layout_and_render(self, root: RuleNode):
        """树形布局：自上而下，同层级横向对齐，是/否分支左右分开。"""
        measure = self._measure_subtree(root, is_root=True)
        total_w = measure['w']
        cx = total_w / 2
        self._render_subtree(root, cx, 0, measure, is_root=True)

    def _render_subtree(self, node: RuleNode, center_x: float, top_y: float,
                        measure: dict, is_root=False):
        """递归渲染子树。center_x 为节点中心 x，top_y 为节点顶部 y。

        父子关系：父节点底部 → 竖直支线 → 水平母线 → 每个子节点顶部各一条
        带箭头的竖直支线，保证每个子模块都有明确连线。
        平行关系：同层子树按 _HGAP 等距横向排列、顶部对齐。
        """
        has_field = bool(getattr(node, "field", ""))
        children = list(getattr(node, "children", []) or [])
        node_w = measure["node_w"]
        node_h = measure["node_h"]
        node_right = center_x + node_w / 2
        node_bottom = top_y + node_h

        # --- 渲染当前节点 ---
        if is_root and not has_field:
            text = self._rule_name or "未命名规则"
            item = _FlowchartRectNode(id(node), node, text,
                                      _C_BG_ROOT, _C_BORDER_ROOT, is_root=True, rule_node=node)
        elif has_field:
            lines = (_build_root_diamond_lines(node, self._rule_name) if is_root
                     else _build_diamond_lines(node, _DIAMOND_WRAP_W))
            item = _FlowchartDiamondNode(id(node), node, lines, rule_node=node)
        else:
            text = f"条件组({_logic_label(node.logic)})"
            item = _FlowchartRectNode(id(node), node, text,
                                      QColor("#e0e7ff"), QColor("#6366f1"), rule_node=node)
        item.setPos(center_x - item.boundingRect().width() / 2, top_y)
        self._scene.addItem(item)
        self._node_items[id(node)] = item

        # --- 叶子条件：是→通过(左下) / 否→报错(右下) ---
        if not children:
            child_y = node_bottom + _VGAP
            pass_cx = center_x - _TERMINAL_W / 2 - _HGAP / 2
            error_cx = center_x + _TERMINAL_W / 2 + _HGAP / 2
            self._add_drop_connector(center_x - node_w * 0.25, node_bottom,
                                     pass_cx, child_y, "是")
            self._add_drop_connector(center_x + node_w * 0.25, node_bottom,
                                     error_cx, child_y, "否")
            self._add_terminal(pass_cx, child_y, True)
            self._add_terminal(error_cx, child_y, False)
            return child_y + _TERMINAL_H

        # --- 有子节点：先水平排布子树，再连母线 ---
        child_measures = measure["children"]
        child_y = node_bottom + _VGAP
        children_w = sum(m["w"] for m in child_measures) + _HGAP * (len(child_measures) - 1)
        child_cxs = self._layout_children(children, child_measures, child_y,
                                          center_x, node_w, has_field)
        return self._connect_children(node, center_x, top_y, node_w, node_h,
                                      child_y, children_w, child_cxs,
                                      child_measures, has_field)

    def _layout_children(self, children, child_measures, child_y,
                         center_x, node_w, has_field) -> list:
        """横向排布子节点，返回各子节点中心 x。有自身条件的节点，其子节点块
        整体左移、右侧留出「否→报错」终端的位置（与测量公式一致）。"""
        children_w = sum(m["w"] for m in child_measures) + _HGAP * (len(child_measures) - 1)
        if has_field:
            combo_w = children_w + _HGAP + _TERMINAL_W
            block_left = center_x - combo_w / 2
        else:
            block_left = center_x - children_w / 2
        cx_cursor = block_left
        child_cxs = []
        for child, m in zip(children, child_measures):
            child_cx = cx_cursor + m["w"] / 2
            self._render_subtree(child, child_cx, child_y, m)
            child_cxs.append(child_cx)
            cx_cursor += m["w"] + _HGAP
        return child_cxs

    def _connect_children(self, node, center_x, top_y, node_w, node_h,
                          child_y, children_w, child_cxs, child_measures, has_field):
        """从当前节点向子节点区连线，并放置「否→报错」/「通过」终端。"""
        node_right = center_x + node_w / 2
        node_bottom = top_y + node_h

        if has_field:
            # 是：子节点块整体左移后的母线分支
            combo_w = children_w + _HGAP + _TERMINAL_W
            block_left = center_x - combo_w / 2
            self._add_branch_bus(center_x, node_bottom, child_y, child_cxs, label="是")
            # 否：右侧报错终端
            error_cx = block_left + combo_w - _TERMINAL_W / 2
            if error_cx > node_right + 4:
                self._add_polyline(
                    [(node_right, top_y + node_h / 2),
                     (error_cx, top_y + node_h / 2),
                     (error_cx, child_y)],
                    label="否", label_seg=0)
            else:
                # 节点本身很宽、终端在其投影内：改从底部绕行，避免连线穿入节点
                self._add_drop_connector(center_x + node_w * 0.3, node_bottom,
                                         error_cx, child_y, "否")
            self._add_terminal(error_cx, child_y, False)
            return child_y + max(m["h"] for m in child_measures)

        # 条件组：母线分支连接所有子节点，全部通过后接「通过」终端
        self._add_branch_bus(center_x, node_bottom, child_y, child_cxs)
        children_max_h = max(m["h"] for m in child_measures)
        pass_y = child_y + children_max_h + _VGAP
        self._add_polyline([(center_x, child_y + children_max_h), (center_x, pass_y)])
        self._add_terminal(center_x, pass_y, True)
        return pass_y + _TERMINAL_H

    def _add_polyline(self, pts, label="", label_seg=0):
        """折线连接线（末段方向箭头），可选在指定段旁标注是/否等文字。"""
        if len(pts) < 2:
            return
        path = QPainterPath(QPointF(pts[0][0], pts[0][1]))
        for x, y in pts[1:]:
            path.lineTo(x, y)
        item = QGraphicsPathItem(path)
        item.setPen(QPen(_C_CONNECTOR, 1.5))
        item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._scene.addItem(item)

        # 箭头（指向终点，随末段方向）
        (x1, y1), (x2, y2) = pts[-2], pts[-1]
        if y2 > y1:
            arrow = QPolygonF([QPointF(x2, y2), QPointF(x2 - 5, y2 - 9), QPointF(x2 + 5, y2 - 9)])
        elif y2 < y1:
            arrow = QPolygonF([QPointF(x2, y2), QPointF(x2 - 5, y2 + 9), QPointF(x2 + 5, y2 + 9)])
        elif x2 > x1:
            arrow = QPolygonF([QPointF(x2, y2), QPointF(x2 - 9, y2 - 5), QPointF(x2 - 9, y2 + 5)])
        else:
            arrow = QPolygonF([QPointF(x2, y2), QPointF(x2 + 9, y2 - 5), QPointF(x2 + 9, y2 + 5)])
        arrow_item = QGraphicsPolygonItem(arrow)
        arrow_item.setBrush(QBrush(_C_CONNECTOR))
        arrow_item.setPen(QPen(_C_CONNECTOR, 1))
        self._scene.addItem(arrow_item)

        # 标注：水平段放上方居中，竖直段放右侧居中
        if label and 0 <= label_seg < len(pts) - 1:
            ax, ay = pts[label_seg]
            bx, by = pts[label_seg + 1]
            if abs(ay - by) < 0.5:
                lx, ly = (ax + bx) / 2, min(ay, by) - 12
            else:
                lx, ly = max(ax, bx) + 10, (ay + by) / 2
            text_item = QGraphicsTextItem(label, None)
            text_item.setFont(_FONT_LABEL)
            text_item.setDefaultTextColor(_C_TEXT_MUTED)
            text_item.setPos(lx - text_item.boundingRect().width() / 2,
                             ly - text_item.boundingRect().height() / 2)
            self._scene.addItem(text_item)

    def _add_drop_connector(self, x1, y1, x2, y2, label="", label_seg=0):
        """竖→横→竖折线，箭头竖直进入终点顶部；同轴时退化为直线。"""
        if abs(x1 - x2) < 0.5:
            self._add_polyline([(x1, y1), (x1, y2)], label=label, label_seg=label_seg)
            return
        mid_y = y1 + (y2 - y1) * 0.55
        self._add_polyline([(x1, y1), (x1, mid_y), (x2, mid_y), (x2, y2)],
                           label=label, label_seg=label_seg)

    def _add_branch_bus(self, parent_cx, parent_bottom, child_top_y, child_cxs, label=""):
        """父节点底部 → 竖直支线（标注是/否）→ 水平母线 → 逐条竖直落入每个子节点顶部。"""
        bus_y = parent_bottom + (child_top_y - parent_bottom) / 2
        self._add_polyline([(parent_cx, parent_bottom), (parent_cx, bus_y)],
                           label=label, label_seg=0)
        xs = list(child_cxs)
        if not xs:
            return
        if len(xs) > 1 or any(abs(x - parent_cx) > 0.5 for x in xs):
            # 水平母线（无箭头）
            bus_left = min(xs + [parent_cx])
            bus_right = max(xs + [parent_cx])
            path = QPainterPath(QPointF(bus_left, bus_y))
            path.lineTo(bus_right, bus_y)
            item = QGraphicsPathItem(path)
            item.setPen(QPen(_C_CONNECTOR, 1.5))
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self._scene.addItem(item)
        for cx in xs:
            self._add_polyline([(cx, bus_y), (cx, child_top_y)])

    def _add_terminal(self, cx, y, is_pass: bool):
        """添加终端节点（通过/不通过）。"""
        text = "通过" if is_pass else "报错"
        bg = _C_BG_PASS if is_pass else _C_BG_FAIL
        border = _C_BORDER_PASS if is_pass else _C_BORDER_FAIL
        item = _FlowchartRectNode(-1, None, text, bg, border, rule_node=None,
                                  min_w=_TERMINAL_W, min_h=_TERMINAL_H, max_w=_TERMINAL_W)
        w = item.boundingRect().width()
        item.setPos(cx - w / 2, y)
        self._scene.addItem(item)

    def wheelEvent(self, event):
        """滚轮缩放流程图（Ctrl+滚轮），以鼠标位置为中心，无限制。"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y() / 1200.0
            factor = 1.0 + delta
            # 放宽缩放范围，允许用户持续放大/缩小
            new_zoom = max(0.05, min(50.0, self._zoom * factor))
            if new_zoom == self._zoom:
                return
            # 标记用户已手动缩放，避免 resize 时重置
            self._user_zoomed = True
            # 鼠标在场景中的坐标
            mouse_scene = self.mapToScene(event.position().toPoint())
            self._zoom = new_zoom
            self.setTransform(QTransform().scale(self._zoom, self._zoom))
            # 缩放后补偿偏移，使鼠标位置保持不变
            after_scene = self.mapToScene(event.position().toPoint())
            delta_pt = mouse_scene - after_scene
            self.translate(delta_pt.x(), delta_pt.y())
        else:
            super().wheelEvent(event)

    def fit_in_view(self):
        """自动缩放适配视图。"""
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        # 同步记录当前缩放比例，避免后续 resize 重置
        try:
            self._zoom = self.transform().m11()
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 仅在首次（场景为空或未缩放时）自适应；保留用户缩放
        if not self._user_zoomed:
            self.fit_in_view()


class FlowchartDialog(QDialog):
    """流程图弹出窗口：独立查看流程图，支持缩放、可调整大小、可最大化。"""

    def __init__(self, root_node, rule_name="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"流程图 - {rule_name or '未命名规则'}")
        # 允许调整大小 + 最大化/最小化按钮
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(900, 700)
        self.setMinimumSize(400, 300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.flowchart = ConditionFlowchart()
        self.flowchart.build_from_node(root_node, rule_name)
        layout.addWidget(self.flowchart)
        # 提示
        hint = QLabel("Ctrl+滚轮缩放 | 拖拽平移 | 窗口可调整大小/最大化")
        hint.setStyleSheet("color: #6b7280; font-size: 11px; padding: 2px;")
        layout.addWidget(hint)


class RuleTreeEditor(QWidget):
    """规则条件树编辑器：树形展示 + 流程图，支持添加子节点、编辑、删除、双向高亮。"""

    def __init__(self, columns: list = None, parent=None):
        super().__init__(parent)
        self.columns = columns or []
        self._editable = True
        self._node_to_item = {}    # id(RuleNode) -> QTreeWidgetItem
        self._rule_name = ""       # 当前规则名（来自 ValidationRule.name）
        self._flowchart_dlg = None  # 流程图弹窗引用（非模态，避免被 GC）
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 上方：条件树（恢复原始大小）
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["条件"])
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        layout.addWidget(self.tree, stretch=1)

        # 下方：操作按钮
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("添加根/子条件")
        self.add_btn.clicked.connect(self._add_node)
        self.edit_btn = QPushButton("编辑")
        self.edit_btn.clicked.connect(self._edit_node)
        self.del_btn = QPushButton("删除")
        self.del_btn.clicked.connect(self._del_node)
        self.refresh_chart_btn = QPushButton("刷新流程图")
        self.refresh_chart_btn.clicked.connect(self._refresh_flowchart)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.del_btn)
        btn_layout.addWidget(self.refresh_chart_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 最下方：条件流程图（宽度与条件树一致，高度自适应）
        chart_header = QHBoxLayout()
        chart_label = QLabel("条件流程图（Ctrl+滚轮缩放）")
        chart_header.addWidget(chart_label)
        chart_header.addStretch()
        # 放大图标按钮
        self.expand_chart_btn = QToolButton()
        self.expand_chart_btn.setText("⤢")
        self.expand_chart_btn.setToolTip("弹出窗口查看流程图")
        self.expand_chart_btn.setFixedSize(28, 24)
        self.expand_chart_btn.clicked.connect(self._open_flowchart_dialog)
        chart_header.addWidget(self.expand_chart_btn)
        layout.addLayout(chart_header)

        self.flowchart = ConditionFlowchart()
        self.flowchart.set_highlight_callback(self._on_flowchart_highlight)
        self.flowchart.set_click_callback(self._on_flowchart_click)
        layout.addWidget(self.flowchart, stretch=1)

        self.set_editable(self._editable)

    def _open_flowchart_dialog(self):
        """弹出非模态窗口查看流程图，允许同时操作主窗口。"""
        if self.tree.topLevelItemCount() == 0:
            return
        item = self.tree.topLevelItem(0)
        root_node = _item_to_node(item)
        # 使用保存的规则名（优先 root.rule_name 作为回退）
        rule_name = self._rule_name
        if not rule_name and isinstance(root_node, RuleNode):
            rule_name = root_node.rule_name or ""
        # 若已有打开的弹窗，先关闭重建（确保内容最新）
        if self._flowchart_dlg is not None:
            try:
                self._flowchart_dlg.close()
            except RuntimeError:
                pass
            self._flowchart_dlg = None
        # parent=None 使弹窗成为独立顶层窗口，不会悬浮于主窗口之上
        self._flowchart_dlg = FlowchartDialog(root_node, rule_name, None)
        # 非模态显示：不阻塞主窗口，用户可继续操作应用程序
        self._flowchart_dlg.show()
        # 窗口关闭后释放引用
        self._flowchart_dlg.finished.connect(lambda _: setattr(self, "_flowchart_dlg", None))

    def set_editable(self, editable: bool):
        """控制是否允许修改条件树（查看/展开不受影响）。"""
        self._editable = bool(editable)
        if hasattr(self, "add_btn"):
            self.add_btn.setEnabled(self._editable)
        if hasattr(self, "edit_btn"):
            self.edit_btn.setEnabled(self._editable)
        if hasattr(self, "del_btn"):
            self.del_btn.setEnabled(self._editable)
        # 刷新流程图按钮始终可用（即使只读也能刷新查看）

    def set_columns(self, columns: list):
        self.columns = list(columns)

    def load_node(self, root: RuleNode, rule_name: str = ""):
        """从 RuleNode 加载树 + 渲染流程图。

        Args:
            root: 规则根节点
            rule_name: 规则名称（来自 ValidationRule.name，用于流程图根节点显示）
        """
        self._rule_name = rule_name or ""
        self.tree.clear()
        self._node_to_item.clear()
        if not root:
            self.flowchart.build_from_node(None)
            return
        item = _node_to_item(root)
        _build_children(item, root)
        self.tree.addTopLevelItem(item)
        item.setExpanded(True)
        self.tree.expandAll()
        # 建立 id(RuleNode) -> QTreeWidgetItem 映射
        self._build_node_map(item, root)
        # 渲染流程图
        self._refresh_flowchart()

    def _refresh_flowchart(self):
        """从当前条件树导出 RuleNode 并重新渲染流程图。"""
        if self.tree.topLevelItemCount() == 0:
            self.flowchart.build_from_node(None)
            return
        item = self.tree.topLevelItem(0)
        root_node = _item_to_node(item)
        # 重建映射
        self._node_to_item.clear()
        self._build_node_map(item, root_node)
        # 使用保存的规则名（优先 root.rule_name 作为回退）
        rule_name = self._rule_name
        if not rule_name and isinstance(root_node, RuleNode):
            rule_name = root_node.rule_name or ""
        self.flowchart.build_from_node(root_node, rule_name)

    def _build_node_map(self, item: QTreeWidgetItem, node: RuleNode):
        """递归建立 node_id -> QTreeWidgetItem 映射。"""
        self._node_to_item[id(node)] = item
        for i in range(item.childCount()):
            child_item = item.child(i)
            if i < len(node.children):
                self._build_node_map(child_item, node.children[i])

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, col: int):
        """条件树节点点击 → 高亮流程图对应节点。"""
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(node, RuleNode):
            return
        try:
            self.flowchart.highlight_node(id(node), True)
        except RuntimeError:
            pass

    def _on_flowchart_highlight(self, node_id: int, on: bool):
        """流程图 hover → 高亮条件树对应节点。"""
        item = self._node_to_item.get(node_id)
        if not item:
            return
        if on:
            # 展开父级
            parent = item.parent()
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()
            # 高亮（选中）
            self.tree.setCurrentItem(item)
        else:
            self.tree.clearSelection()

    def _on_flowchart_click(self, node_id: int):
        """流程图点击 → 高亮并展开条件树对应节点。"""
        item = self._node_to_item.get(node_id)
        if not item:
            return
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    def get_root_node(self) -> RuleNode:
        """导出当前树为 RuleNode。"""
        if self.tree.topLevelItemCount() == 0:
            return RuleNode()
        item = self.tree.topLevelItem(0)
        return _item_to_node(item)

    def _current_item(self) -> QTreeWidgetItem:
        return self.tree.currentItem()

    def _refresh_item_display(self, item: QTreeWidgetItem):
        """同步 tree 子项到 node.children 并重算显示标签。

        修复问题：编辑子条件后，父节点 node.children 可能仍为旧值（空），
        导致 _node_to_item 误判为叶子并显示「根」。此处以 tree 实际子项为准。
        """
        if not item:
            return
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(node, RuleNode):
            return
        # 用 tree 实际子项重建 node.children（递归同步）
        synced = _item_to_node(item)
        display_item = _node_to_item(synced)
        item.setText(0, display_item.text(0))
        item.setToolTip(0, display_item.toolTip(0))
        item.setData(0, Qt.ItemDataRole.UserRole, synced)

    def _refresh_chain(self, item: QTreeWidgetItem):
        """从 item 起沿祖先链逐级重算显示标签。

        只刷新直接父级时，祖父级「条件组」卡片上的条件数/示例仍可能是
        旧值（曾显示「根」时期的内容），故整条链都要重算。
        """
        p = item
        while p is not None:
            self._refresh_item_display(p)
            p = p.parent()

    def _open_node_editor(self, item: QTreeWidgetItem) -> bool:
        """弹出编辑对话框并应用结果。返回是否确认（OK）；取消返回 False。"""
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(node, RuleNode):
            node = RuleNode()
            item.setData(0, Qt.ItemDataRole.UserRole, node)
        dlg = RuleNodeEditDialog(node, self.columns, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        dlg.get_node()
        # 关键修复：以 tree 实际子项为准重建 node.children，
        # 否则 node.children 仍为旧值（可能为空），_node_to_item 会误显示「根」
        self._refresh_chain(item)
        # 编辑完成后刷新流程图
        self._refresh_flowchart()
        return True

    def _add_node(self):
        """添加子节点：若已选中某节点则在其下添加子条件，否则添加为顶层节点。"""
        if not self._editable:
            return
        parent_item = self._current_item()
        node = RuleNode(field="", operator="eq", value=None, logic="and")
        new_item = _node_to_item(node)
        if parent_item:
            parent_item.addChild(new_item)
            parent_item.setExpanded(True)
        else:
            self.tree.addTopLevelItem(new_item)
        self.tree.setCurrentItem(new_item)
        if not self._open_node_editor(new_item):
            # 取消编辑：移除刚添加的空节点，避免留下无意义的「根」卡片
            parent = new_item.parent()
            if parent:
                parent.removeChild(new_item)
            else:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(new_item))
            if parent is not None:
                self._refresh_chain(parent)
            self._refresh_flowchart()

    def _edit_node(self):
        if not self._editable:
            return
        item = self._current_item()
        if not item:
            return
        self._open_node_editor(item)

    def _del_node(self):
        if not self._editable:
            return
        item = self._current_item()
        if not item:
            return
        parent = item.parent()
        if parent:
            parent.removeChild(item)
        else:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        # 删除后刷新祖先链（父节点可能由条件组变为叶子，祖父级示例/条件数也会变化）
        if parent is not None:
            self._refresh_chain(parent)
        # 删除后刷新流程图
        self._refresh_flowchart()
