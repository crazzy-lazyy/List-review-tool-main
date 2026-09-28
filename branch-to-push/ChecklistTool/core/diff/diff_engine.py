# -*- coding: utf-8 -*-
"""
清单差异对比引擎
参考 align + 规范化比较：仅在对齐后的对比列上做规范化再逐列比较，避免相同数值被误标为修改。
支持不匹配数据总数等统计。
"""

from typing import List, Optional, Set, Dict, Any, Tuple
import pandas as pd
import numpy as np

try:
    from config import DIFF_ADDED, DIFF_DELETED, DIFF_MODIFIED, DIFF_UNCHANGED
except ImportError:
    DIFF_ADDED = "added"
    DIFF_DELETED = "deleted"
    DIFF_MODIFIED = "modified"
    DIFF_UNCHANGED = "unchanged"

NUMERIC_TOLERANCE = 1e-9
NUMERIC_FORMAT = "%.10g"


def _canonical_scalar(v) -> str:
    """将单值规范为可比较字符串：能转浮点则按容差规范化后格式化为统一小数表示。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    try:
        f = float(v)
        if pd.isna(f):
            return ""
        # 统一成相同精度，避免科学计数法与小数混用导致误判
        return NUMERIC_FORMAT % f
    except (TypeError, ValueError):
        return s


def _canonical_series(s: pd.Series) -> pd.Series:
    """对一列做规范化。"""
    return s.map(_canonical_scalar)


def _canonical_df(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """仅对指定列做规范化，返回与 df 同索引的 DataFrame。"""
    out = pd.DataFrame(index=df.index)
    for c in cols:
        if c in df.columns:
            out[c] = _canonical_series(df[c])
        else:
            out[c] = ""
    return out


class DiffResult:
    """
    单次对比结果：行数据 + __diff_type__ + __changed_fields__；
    可选统计：count_added, count_deleted, count_modified, count_unchanged, total_mismatched。
    """

    def __init__(self):
        self.rows: List[Dict[str, Any]] = []
        self.columns: List[str] = []
        self.key_columns: List[str] = []
        self.compare_columns: List[str] = []
        # 表头差异说明（如待对比文件缺少/多出的列），由调用方计算后附上，结果页展示
        self.header_notes: List[str] = []
        self.count_added: int = 0
        self.count_deleted: int = 0
        self.count_modified: int = 0
        self.count_unchanged: int = 0

    @property
    def total_mismatched(self) -> int:
        """不匹配的数据总数（新增 + 删除 + 修改）。"""
        return self.count_added + self.count_deleted + self.count_modified

    def to_dataframe(self) -> pd.DataFrame:
        """返回完整结果表：数据列在前（与源表一致），最后为 __diff_type__、__changed_fields__、__changes_detail__。"""
        diff_cols = ["__diff_type__", "__changed_fields__", "__changes_detail__"]
        if not self.rows:
            return pd.DataFrame(columns=self.columns + diff_cols)
        df = pd.DataFrame(self.rows)
        if "__diff_type__" not in df.columns:
            df["__diff_type__"] = DIFF_UNCHANGED
        if "__changed_fields__" not in df.columns:
            df["__changed_fields__"] = [[]] * len(df)
        if "__changes_detail__" not in df.columns:
            df["__changes_detail__"] = ""
        # 数据列 = result.columns 中非差异列（保持顺序）+ 行里多出的非差异列，避免行号限制等导致只显示 3 列
        data_cols_ordered = [c for c in self.columns if c not in diff_cols]
        for c in data_cols_ordered:
            if c not in df.columns:
                df[c] = ""
        extra_data = [c for c in df.columns if c not in diff_cols and c not in data_cols_ordered]
        out_cols = data_cols_ordered + extra_data + [x for x in diff_cols if x in df.columns]
        # 源文件行号固定放第一列：此前当待对比文件有基准没有的列时，它会落在数据列中间，难以及时定位
        if "__source_row__" in out_cols:
            out_cols.remove("__source_row__")
            out_cols.insert(0, "__source_row__")
        df = df[out_cols]
        return df


class DiffEngine:
    """
    两表对比：键列匹配行，对比列做规范化后逐列比较（align 思路），
    仅当规范化结果不同才标为 modified，并记录 __changed_fields__。
    """

    def __init__(
        self,
        key_columns: Optional[List[str]] = None,
        compare_columns: Optional[List[str]] = None,
        ignore_case: bool = False,
        trim_strings: bool = True,
    ):
        self.key_columns = key_columns or []
        self.compare_columns = compare_columns or []
        self.ignore_case = ignore_case
        self.trim_strings = trim_strings

    def _row_key(self, row: pd.Series, keys: List[str]) -> tuple:
        return tuple(_canonical_scalar(row.get(k, "")) for k in keys)

    def compare_two_tables(
        self,
        df_a: pd.DataFrame,
        df_b: pd.DataFrame,
        keys: Optional[List[str]] = None,
        compare_cols: Optional[List[str]] = None,
    ) -> DiffResult:
        keys = keys or self.key_columns
        all_cols = list(df_a.columns)
        for c in df_b.columns:
            if c not in all_cols:
                all_cols.append(c)
        if not compare_cols:
            compare_cols = [
                c for c in all_cols
                if c not in ("__diff_type__", "__changed_fields__", "__row_index__", "__source_row__")
                and c in df_b.columns and c in df_a.columns
            ]

        result = DiffResult()
        result.columns = all_cols
        result.key_columns = keys
        result.compare_columns = compare_cols

        if df_a.empty and df_b.empty:
            return result

        if not keys:
            return self._compare_by_position(df_a, df_b, compare_cols, result)

        # 键列匹配（支持重复键）：key -> [row_indices]
        def _index_by_key(df: pd.DataFrame, ks: List[str]) -> Dict[tuple, List[int]]:
            m: Dict[tuple, List[int]] = {}
            for i in range(len(df)):
                k = self._row_key(df.iloc[i], ks)
                m.setdefault(k, []).append(i)
            return m

        key_to_a = _index_by_key(df_a, keys)
        key_to_b = _index_by_key(df_b, keys)

        # 统一输出基准：以基准清单(df_a)为主。
        # 主体按基准清单的键顺序输出（修改/未变/删除自然交错，行内容与行号均来自基准清单），
        # 仅存在于待对比文件(df_b)的行统一作为“新增”追加在末尾（按待对比行序，行号为待对比行号），
        # 避免不同对比选项下输出的排序基准不一致。
        idx_a: List[int] = []
        idx_b: List[int] = []
        added_rows: List[tuple] = []  # (待对比行索引, 差异说明)
        for k in key_to_a:
            la = key_to_a.get(k, [])
            lb = key_to_b.get(k, [])
            n_pair = min(len(la), len(lb))
            idx_a.extend(la[:n_pair])
            idx_b.extend(lb[:n_pair])
            # 待对比中该键多余的重复行 → 新增（末尾统一输出）
            added_rows.extend(
                (j, "该键在待对比文件中出现的次数多于基准（新增行）")
                for j in lb[n_pair:]
            )
        for k in key_to_b:
            if k not in key_to_a:
                added_rows.extend(
                    (j, "该键仅存在于待对比文件（基准清单没有此行）")
                    for j in key_to_b.get(k, [])
                )

        if idx_b:
            old_common = _canonical_df(df_a.iloc[idx_a].reset_index(drop=True), compare_cols)
            new_common = _canonical_df(df_b.iloc[idx_b].reset_index(drop=True), compare_cols)
            old_raw = df_a.iloc[idx_a].reset_index(drop=True)
            new_raw = df_b.iloc[idx_b].reset_index(drop=True)
            # 确保列顺序一致
            old_common = old_common[compare_cols]
            new_common = new_common[compare_cols]
            diff_bool = old_common.ne(new_common)
            modified_mask = diff_bool.any(axis=1)
        else:
            diff_bool = None
            modified_mask = None

        # 主体输出：按基准清单键顺序，逐键输出配对行 + 该键在基准清单中多出的行
        pos = 0
        for k in key_to_a:
            la = key_to_a.get(k, [])
            lb = key_to_b.get(k, [])
            n_pair = min(len(la), len(lb))
            for _ in range(n_pair):
                i = idx_a[pos]
                row_dict = df_a.iloc[i].to_dict()
                if modified_mask is not None and modified_mask.iloc[pos]:
                    changed = list(diff_bool.iloc[pos].index[diff_bool.iloc[pos]].tolist())
                    row_dict["__diff_type__"] = DIFF_MODIFIED
                    row_dict["__changed_fields__"] = changed
                    # 具体差异：列名 → 基准值→待对比值
                    parts = []
                    for col in changed:
                        if col in old_raw.columns and col in new_raw.columns:
                            ov = old_raw.iloc[pos][col]
                            nv = new_raw.iloc[pos][col]
                            so = str(ov) if ov is not None and not (isinstance(ov, float) and pd.isna(ov)) else ""
                            sn = str(nv) if nv is not None and not (isinstance(nv, float) and pd.isna(nv)) else ""
                            parts.append(f"{col}: {so}→{sn}")
                    row_dict["__changes_detail__"] = "; ".join(parts)
                    result.count_modified += 1
                else:
                    row_dict["__diff_type__"] = DIFF_UNCHANGED
                    row_dict["__changed_fields__"] = []
                    row_dict["__changes_detail__"] = ""
                    result.count_unchanged += 1
                result.rows.append(row_dict)
                pos += 1
            # 该键在基准清单中多出的行 → 删除（紧随配对行，保持基准清单顺序）
            for i_extra in la[n_pair:]:
                row_dict = df_a.iloc[i_extra].to_dict()
                row_dict["__diff_type__"] = DIFF_DELETED
                row_dict["__changed_fields__"] = []
                if lb:
                    row_dict["__changes_detail__"] = "该键在基准清单中出现的次数多于待对比（待对比缺失此行）"
                else:
                    row_dict["__changes_detail__"] = "该键仅存在于基准清单（待对比文件没有此行）"
                result.rows.append(row_dict)
                result.count_deleted += 1

        # 尾部输出：仅存在于待对比文件的行 → 新增（按待对比行序，便于回待对比文件定位）
        for j, detail in sorted(added_rows, key=lambda t: t[0]):
            row_dict = df_b.iloc[j].to_dict()
            row_dict["__diff_type__"] = DIFF_ADDED
            row_dict["__changed_fields__"] = []
            row_dict["__changes_detail__"] = detail
            result.rows.append(row_dict)
            result.count_added += 1

        return result

    def _compare_by_position(
        self,
        df_a: pd.DataFrame,
        df_b: pd.DataFrame,
        compare_cols: List[str],
        result: DiffResult,
    ) -> DiffResult:
        """无键列时按行号对齐比较。"""
        n_a, n_b = len(df_a), len(df_b)
        for i in range(max(n_a, n_b)):
            if i >= n_a:
                row_dict = df_b.iloc[i].to_dict()
                row_dict["__diff_type__"] = DIFF_ADDED
                row_dict["__changed_fields__"] = []
                row_dict["__changes_detail__"] = "待对比文件比基准多出的行（按行号对齐）"
                result.rows.append(row_dict)
                result.count_added += 1
            elif i >= n_b:
                row_dict = df_a.iloc[i].to_dict()
                row_dict["__diff_type__"] = DIFF_DELETED
                row_dict["__changed_fields__"] = []
                row_dict["__changes_detail__"] = "基准清单有而待对比文件缺少的行（按行号对齐）"
                result.rows.append(row_dict)
                result.count_deleted += 1
            else:
                old_common = _canonical_df(df_a.iloc[i : i + 1], compare_cols)
                new_common = _canonical_df(df_b.iloc[i : i + 1], compare_cols)
                diff_bool = old_common.ne(new_common)
                changed = list(diff_bool.columns[diff_bool.any()].tolist())
                # 展示内容以基准清单(df_a)为主，与键列匹配模式一致
                row_dict = df_a.iloc[i].to_dict()
                if changed:
                    row_dict["__diff_type__"] = DIFF_MODIFIED
                    row_dict["__changed_fields__"] = changed
                    parts = []
                    for col in changed:
                        if col in df_a.columns and col in df_b.columns:
                            ov = df_a.iloc[i][col]
                            nv = df_b.iloc[i][col]
                            so = str(ov) if ov is not None and not (isinstance(ov, float) and pd.isna(ov)) else ""
                            sn = str(nv) if nv is not None and not (isinstance(nv, float) and pd.isna(nv)) else ""
                            parts.append(f"{col}: {so}→{sn}")
                    row_dict["__changes_detail__"] = "; ".join(parts)
                    result.count_modified += 1
                else:
                    row_dict["__diff_type__"] = DIFF_UNCHANGED
                    row_dict["__changed_fields__"] = []
                    row_dict["__changes_detail__"] = ""
                    result.count_unchanged += 1
                result.rows.append(row_dict)
        return result

    def compare_versions(
        self,
        df_old: pd.DataFrame,
        df_new: pd.DataFrame,
        key_columns: Optional[List[str]] = None,
        compare_columns: Optional[List[str]] = None,
    ) -> DiffResult:
        return self.compare_two_tables(
            df_old, df_new, keys=key_columns, compare_cols=compare_columns
        )


def cross_compare(
    base_df: pd.DataFrame,
    other_dfs: List[pd.DataFrame],
    key_columns: List[str],
    compare_columns: List[str],
    base_name: str = "基准",
    other_names: Optional[List[str]] = None,
) -> List[DiffResult]:
    engine = DiffEngine(key_columns=key_columns, compare_columns=compare_columns)
    return [
        engine.compare_two_tables(base_df, odf, keys=key_columns, compare_cols=compare_columns)
        for odf in other_dfs
    ]
