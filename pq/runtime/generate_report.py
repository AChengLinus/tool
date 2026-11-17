#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电能质量测试数据汇总报告生成工具 (v2.0)
==============================================
按照模板格式，将谐波、间谐波、电能质量测试数据生成 Word 报告。

模板参考：
  - 综合值表格：独立的 7 列表格（谐波次数 + A/B/C相最大值/95%值）
  - 各功率区间表格：大合并表格，第一列为"功率区间"（8列）
  - 电流和电压分开出表
"""

import os
import re
import argparse
from datetime import datetime

import pandas as pd
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml


# ============================================================
# 功率区间定义
# ============================================================
INTERVAL_NAMES = [
    "0%-10%Pn", "10%-20%Pn", "20%-30%Pn", "30%-40%Pn", "40%-50%Pn",
    "50%-60%Pn", "60%-70%Pn", "70%-80%Pn", "80%-90%Pn", "90%-100%Pn",
]

# 文件名中使用的区间关键词
INTERVAL_FILE_KEYWORDS = [
    "0～10%", "10～20%", "20～30%", "30～40%", "40～50%",
    "50～60%", "60～70%", "70～80%", "80～90%", "90～100%",
]


# ============================================================
# 工具函数
# ============================================================

def clean_value(val):
    """清理单元格值，转为数值"""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return val if not pd.isna(val) else None
    s = str(val).strip()
    if s in ('-', '/', '—', '', 'nan', 'NaN', 'None'):
        return None
    s = re.sub(r'[\(（].*?[\)）]', '', s)
    s = s.replace('%', '').replace('V', '').replace('A', '')
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        return str(val).strip()


def format_num(val, decimals=3):
    """格式化数值用于显示"""
    if val is None:
        return "—"
    if isinstance(val, float):
        if abs(val) >= 1000:
            return f"{val:.2f}"
        elif abs(val) >= 10:
            return f"{val:.3f}"
        elif abs(val) >= 1:
            return f"{val:.4f}"
        else:
            return f"{val:.{decimals}f}"
    return str(val)


def format_order(order_str):
    """格式化谐波/间谐波次数标签"""
    try:
        v = float(order_str)
        if v == int(v):
            return str(int(v))
        else:
            # 保留原始精度（如 1.5, 2.5）
            return str(v)
    except ValueError:
        return order_str


def find_file_by_interval(folder, interval_keyword, extra_filter=""):
    """在目录中根据区间关键词查找文件"""
    for f in os.listdir(folder):
        if interval_keyword in f and extra_filter in f:
            return os.path.join(folder, f)
    return None


# ============================================================
# 数据解析：谐波 / 间谐波（同时提取电流和电压）
# ============================================================

def parse_harmonic_file_both(filepath):
    """
    解析谐波/间谐波 Excel 文件，同时返回电流(A)和电压(%)数据。

    文件有两种列格式（自动检测）：
      21列格式（含综合值列）：
        电压: Uab max=2, 95%=3 | Ubc max=5, 95%=6 | Uca max=8, 95%=9
        电流: Ia max=12, 95%=13 | Ib max=15, 95%=16 | Ic max=18, 95%=19
      15列格式（不含综合值列）：
        电压: Uab max=2, 95%=3 | Ubc max=4, 95%=5 | Uca max=6, 95%=7
        电流: Ia max=9, 95%=10 | Ib max=11, 95%=12 | Ic max=13, 95%=14

    返回: {
        "current": [{谐波次数, A_max, A_95, B_max, B_95, C_max, C_95}, ...],
        "voltage": [{谐波次数, A_max, A_95, B_max, B_95, C_max, C_95}, ...],
    }
    """
    df = pd.read_excel(filepath, header=None)
    num_cols = df.shape[1]

    if num_cols >= 21:
        # 21列格式
        u_amax, u_a95 = 2, 3
        u_bmax, u_b95 = 5, 6
        u_cmax, u_c95 = 8, 9
        i_amax, i_a95 = 12, 13
        i_bmax, i_b95 = 15, 16
        i_cmax, i_c95 = 18, 19
    else:
        # 15列格式
        u_amax, u_a95 = 2, 3
        u_bmax, u_b95 = 4, 5
        u_cmax, u_c95 = 6, 7
        i_amax, i_a95 = 9, 10
        i_bmax, i_b95 = 11, 12
        i_cmax, i_c95 = 13, 14

    current_rows = []
    voltage_rows = []

    for i in range(3, len(df)):
        order_raw = df.iloc[i, 0]
        if order_raw is None or (isinstance(order_raw, float) and pd.isna(order_raw)):
            continue
        order_str = str(order_raw).strip()
        if order_str in ('', 'nan', 'NaN'):
            continue

        order_label = format_order(order_str)

        # 电流数据
        i_row = {
            "order": order_label,
            "A_max": clean_value(df.iloc[i, i_amax]),
            "A_95":  clean_value(df.iloc[i, i_a95]),
            "B_max": clean_value(df.iloc[i, i_bmax]),
            "B_95":  clean_value(df.iloc[i, i_b95]),
            "C_max": clean_value(df.iloc[i, i_cmax]),
            "C_95":  clean_value(df.iloc[i, i_c95]),
        }
        current_rows.append(i_row)

        # 电压数据
        u_row = {
            "order": order_label,
            "A_max": clean_value(df.iloc[i, u_amax]),
            "A_95":  clean_value(df.iloc[i, u_a95]),
            "B_max": clean_value(df.iloc[i, u_bmax]),
            "B_95":  clean_value(df.iloc[i, u_b95]),
            "C_max": clean_value(df.iloc[i, u_cmax]),
            "C_95":  clean_value(df.iloc[i, u_c95]),
        }
        voltage_rows.append(u_row)

    return {"current": current_rows, "voltage": voltage_rows}


# ============================================================
# 数据解析：电能质量
# ============================================================

def parse_power_quality_file(filepath):
    """
    解析电能质量 Excel 文件。
    左右双栏布局，提取所有参数。
    """
    df = pd.read_excel(filepath, header=None)
    rows = []

    for i in range(3, len(df)):
        # 左侧参数组 (cols 0-5)
        pname_l = str(df.iloc[i, 0]).strip() if pd.notna(df.iloc[i, 0]) else ""
        if pname_l and pname_l not in ('nan', ''):
            rows.append({
                "参数名称": pname_l,
                "代号": str(df.iloc[i, 1]).strip() if pd.notna(df.iloc[i, 1]) else "",
                "单位": str(df.iloc[i, 2]).strip() if pd.notna(df.iloc[i, 2]) and str(df.iloc[i, 2]).strip() not in ('nan', '') else "-",
                "最大值": clean_value(df.iloc[i, 3]),
                "最小值": clean_value(df.iloc[i, 4]),
                "95%值": None,
                "综合值": clean_value(df.iloc[i, 5]),
            })

        # 右侧参数组 (cols 6-12)
        pname_r = str(df.iloc[i, 6]).strip() if pd.notna(df.iloc[i, 6]) else ""
        if pname_r and pname_r not in ('nan', ''):
            rows.append({
                "参数名称": pname_r,
                "代号": str(df.iloc[i, 7]).strip() if pd.notna(df.iloc[i, 7]) else "",
                "单位": str(df.iloc[i, 8]).strip() if pd.notna(df.iloc[i, 8]) and str(df.iloc[i, 8]).strip() not in ('nan', '') else "-",
                "最大值": clean_value(df.iloc[i, 9]),
                "最小值": None,
                "95%值": clean_value(df.iloc[i, 11]),
                "综合值": clean_value(df.iloc[i, 12]),
            })

    return rows


# ============================================================
# Word 表格构建
# ============================================================

def set_cell_shading(cell, color):
    """设置单元格背景色"""
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color}" w:val="clear"/>')
    cell._tc.get_or_add_tcPr().append(shading)


def _is_number_text(text):
    """判断文本是否为数值（用于决定字体：数字用 Times New Roman，文字用宋体）"""
    if text is None or text == "—" or text == "":
        return False
    try:
        float(str(text))
        return True
    except ValueError:
        return False


def format_table_cell(cell, text, bold=False, font_size=None, alignment=WD_ALIGN_PARAGRAPH.CENTER,
                      is_header=False):
    """
    格式化表格单元格。
    - 表头：宋体 8pt 加粗 浅蓝背景
    - 数字数据：Times New Roman 11pt
    - 文字数据：宋体 10.5pt（五号）
    - 英文标签：宋体 10.5pt
    """
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.text = ""
    para = cell.paragraphs[0]
    para.alignment = alignment
    para.paragraph_format.space_before = Pt(1)
    para.paragraph_format.space_after = Pt(1)
    para.paragraph_format.line_spacing = 1.0

    display_text = str(text) if text is not None else "—"

    if is_header:
        run = para.add_run(display_text)
        run.font.size = Pt(font_size or 10.5)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        run.bold = True
        set_cell_shading(cell, "D9E2F3")
    elif _is_number_text(display_text):
        # 数字 → Times New Roman 11pt
        run = para.add_run(display_text)
        run.font.size = Pt(font_size or 11)
        run.font.name = "Times New Roman"
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    else:
        # 文字/中文 → 宋体 10.5pt（五号）
        run = para.add_run(display_text)
        run.font.size = Pt(font_size or 10.5)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 垂直居中
    tcPr = cell._tc.get_or_add_tcPr()
    vAlign = parse_xml(f'<w:vAlign {nsdecls("w")} w:val="center"/>')
    tcPr.append(vAlign)


def add_table_caption(doc, text):
    """添加表标题（Caption 样式）"""
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(6)
    para.paragraph_format.space_after = Pt(3)
    run = para.add_run(text)
    run.font.size = Pt(9)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.bold = True


def make_7col_header(order_name="谐波次数"):
    """标准 7 列表头"""
    return [order_name,
            "A相最大\n值 (A)", "95%概率\n大值(A)",
            "B相最大\n值 (A)", "95%概率\n大值(A)",
            "C相最大\n值 (A)", "95%概率\n大值(A)"]


def make_7col_header_pct(order_name="谐波次数"):
    """百分比版 7 列表头"""
    return [order_name,
            "A相最大\n值 (%)", "95%概率\n大值(%)",
            "B相最大\n值 (%)", "95%概率\n大值(%)",
            "C相最大\n值 (%)", "95%概率\n大值(%)"]


def make_8col_header(order_name="谐波次数"):
    """含功率区间列的 8 列表头"""
    return ["功率\n区间", order_name,
            "A相最大\n值 (A)", "95%概率\n大值(A)",
            "B相最大\n值 (A)", "95%概率\n大值(A)",
            "C相最大\n值 (A)", "95%概率\n大值(A)"]


def make_8col_header_pct(order_name="谐波次数"):
    """含功率区间列的百分比版 8 列表头"""
    return ["功率\n区间", order_name,
            "A相最大\n值 (%)", "95%概率\n大值(%)",
            "B相最大\n值 (%)", "95%概率\n大值(%)",
            "C相最大\n值 (%)", "95%概率\n大值(%)"]


def add_combined_table_7col(doc, rows, unit="A", row_filter=None, order_name="谐波次数"):
    """
    添加综合值表格（7列，无功率区间列）。
    row_filter: 过滤函数，默认使用 _filter_harmonic_rows(skip_fundamental=True)
    """
    if row_filter is None:
        row_filter = lambda r: _filter_harmonic_rows(r, skip_fundamental=True)

    if unit == "%":
        headers = make_7col_header_pct(order_name)
    else:
        headers = make_7col_header(order_name)

    data_rows = row_filter(rows)

    if not data_rows:
        no_data_para = doc.add_paragraph("（无数据）")
        return

    table = doc.add_table(rows=len(data_rows) + 1, cols=7, style="Table Grid")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    # 表头
    for j, h in enumerate(headers):
        format_table_cell(table.rows[0].cells[j], h, is_header=True, font_size=8)

    # 数据
    for i, row in enumerate(data_rows):
        vals = [row["order"],
                format_num(row["A_max"]), format_num(row["A_95"]),
                format_num(row["B_max"]), format_num(row["B_95"]),
                format_num(row["C_max"]), format_num(row["C_95"])]
        for j, v in enumerate(vals):
            format_table_cell(table.rows[i + 1].cells[j], v)

    _set_7col_widths(table)
    return table


def add_interval_table_8col(doc, all_interval_data, unit="A", order_name="谐波次数",
                            row_filter=None):
    """
    添加各功率区间合并表格（8列，第一列为功率区间）。

    all_interval_data: [(interval_name, [rows]), ...]
    row_filter: 过滤函数
    """
    if row_filter is None:
        row_filter = lambda r: _filter_harmonic_rows(r, skip_fundamental=True)

    if unit == "%":
        headers = make_8col_header_pct(order_name)
    else:
        headers = make_8col_header(order_name)

    # 构建所有行：每条数据前加上功率区间名
    all_rows = []
    for interval_name, rows in all_interval_data:
        data_rows = row_filter(rows)
        for r in data_rows:
            all_rows.append((interval_name, r))

    if not all_rows:
        no_data_para = doc.add_paragraph("（无数据）")
        return

    table = doc.add_table(rows=len(all_rows) + 1, cols=8, style="Table Grid")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    # 表头
    for j, h in enumerate(headers):
        format_table_cell(table.rows[0].cells[j], h, is_header=True, font_size=8)

    # 数据：功率区间列只在每组第一行写值，其余行留空（后面合并单元格用）
    last_interval = None
    merge_ranges = []
    group_start = 1  # 数据从第1行开始（第0行是表头）
    for i, (iname, row) in enumerate(all_rows):
        if iname != last_interval and last_interval is not None:
            # 新区间开始，记录上一个区间的合并范围
            if group_start < i:  # i 是 0-based, 对应表行 i+1
                merge_ranges.append((group_start, i))  # start, end 是 1-based 行号
            group_start = i + 1  # 新区间起始行号
        show_interval = iname if iname != last_interval else ""
        last_interval = iname
        vals = [show_interval, row["order"],
                format_num(row["A_max"]), format_num(row["A_95"]),
                format_num(row["B_max"]), format_num(row["B_95"]),
                format_num(row["C_max"]), format_num(row["C_95"])]
        for j, v in enumerate(vals):
            format_table_cell(table.rows[i + 1].cells[j], v)

    # 最后一个区间
    if group_start < len(all_rows):
        merge_ranges.append((group_start, len(all_rows)))

    _set_8col_widths(table)
    _merge_interval_column(table, merge_ranges=merge_ranges)
    return table


def add_pq_combined_table(doc, rows, title=""):
    """添加电能质量综合值表格"""
    headers = ["参数名称", "代号", "单位", "最大值", "最小值", "95%概率大值", "综合值"]

    if not rows:
        doc.add_paragraph("（无数据）")
        return

    table = doc.add_table(rows=len(rows) + 1, cols=7, style="Table Grid")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    for j, h in enumerate(headers):
        format_table_cell(table.rows[0].cells[j], h, is_header=True, font_size=8)

    for i, row in enumerate(rows):
        vals = [row.get("参数名称", "—"),
                row.get("代号", "—"),
                row.get("单位", "—"),
                format_num(row.get("最大值")),
                format_num(row.get("最小值")),
                format_num(row.get("95%值")),
                format_num(row.get("综合值"))]
        for j, v in enumerate(vals):
            format_table_cell(table.rows[i + 1].cells[j], v)

    _set_pq_widths(table)


def add_pq_interval_table(doc, all_interval_data):
    """
    电能质量各功率区间合并表格。
    all_interval_data: [(interval_name, [rows]), ...]
    """
    headers = ["功率区间", "参数名称", "代号", "单位", "最大值", "最小值", "95%概率大值", "综合值"]

    all_rows = []
    for interval_name, rows in all_interval_data:
        for r in rows:
            all_rows.append((interval_name, r))

    if not all_rows:
        doc.add_paragraph("（无数据）")
        return

    table = doc.add_table(rows=len(all_rows) + 1, cols=8, style="Table Grid")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    for j, h in enumerate(headers):
        format_table_cell(table.rows[0].cells[j], h, is_header=True, font_size=8)

    # 数据：功率区间列只在每组第一行写值
    last_interval = None
    merge_ranges = []
    group_start = 1
    for i, (iname, row) in enumerate(all_rows):
        if iname != last_interval and last_interval is not None:
            if group_start < i:
                merge_ranges.append((group_start, i))
            group_start = i + 1
        show_interval = iname if iname != last_interval else ""
        last_interval = iname
        vals = [show_interval,
                row.get("参数名称", "—"),
                row.get("代号", "—"),
                row.get("单位", "—"),
                format_num(row.get("最大值")),
                format_num(row.get("最小值")),
                format_num(row.get("95%值")),
                format_num(row.get("综合值"))]
        for j, v in enumerate(vals):
            format_table_cell(table.rows[i + 1].cells[j], v)

    if group_start < len(all_rows):
        merge_ranges.append((group_start, len(all_rows)))

    _set_pqi_widths(table)
    _merge_interval_column(table, merge_ranges=merge_ranges)


def _merge_interval_column(table, col_idx=0, merge_ranges=None):
    """
    合并表格中 col_idx 列的连续相同值单元格。
    merge_ranges: [(start_row, end_row), ...]  行号从 1 开始（0 是表头）
    """
    if len(table.rows) <= 1:
        return

    if merge_ranges:
        for start, end in merge_ranges:
            if start < end and start < len(table.rows) and end < len(table.rows):
                # 清除待合并单元格的文本（只保留第一个单元格的内容）
                first_text = table.rows[start].cells[col_idx].text
                for r in range(start + 1, end + 1):
                    _clear_cell_text(table.rows[r].cells[col_idx])
                # 重新设置第一个单元格文本（清除操作可能影响了它）
                if first_text and not table.rows[start].cells[col_idx].text.strip():
                    _set_cell_text(table.rows[start].cells[col_idx], first_text)
                table.rows[start].cells[col_idx].merge(table.rows[end].cells[col_idx])
        return

    # 自动检测：按单元格文本分组
    start = 1
    current_val = table.rows[start].cells[col_idx].text
    for i in range(2, len(table.rows)):
        cell_val = table.rows[i].cells[col_idx].text
        if cell_val != current_val:
            if i - start > 1:
                _merge_cells(table, col_idx, start, i - 1)
            start = i
            current_val = cell_val
    if len(table.rows) - start > 1:
        _merge_cells(table, col_idx, start, len(table.rows) - 1)


def _clear_cell_text(cell):
    """清除单元格中所有段落的文本"""
    for p in cell.paragraphs:
        for r in p.runs:
            r.text = ""


def _set_cell_text(cell, text):
    """设置单元格文本（清除后写入）"""
    _clear_cell_text(cell)
    if cell.paragraphs:
        cell.paragraphs[0].add_run(text)


def _merge_cells(table, col, row_start, row_end):
    """合并表格中同一列的连续行"""
    cell_start = table.rows[row_start].cells[col]
    cell_end = table.rows[row_end].cells[col]
    cell_start.merge(cell_end)


def _set_7col_widths(table):
    """设置7列表格列宽"""
    widths = [Cm(2.0), Cm(2.8), Cm(2.8), Cm(2.8), Cm(2.8), Cm(2.8), Cm(2.8)]
    _apply_widths(table, widths)


def _set_8col_widths(table):
    """设置8列表格列宽"""
    widths = [Cm(1.8), Cm(1.8), Cm(2.5), Cm(2.5), Cm(2.5), Cm(2.5), Cm(2.5), Cm(2.5)]
    _apply_widths(table, widths)


def _set_pq_widths(table):
    """设置电能质量7列表格列宽"""
    widths = [Cm(3.2), Cm(2.0), Cm(1.2), Cm(2.5), Cm(2.5), Cm(2.5), Cm(2.5)]
    _apply_widths(table, widths)


def _set_pqi_widths(table):
    """设置电能质量8列表格列宽"""
    widths = [Cm(1.8), Cm(3.0), Cm(1.8), Cm(1.2), Cm(2.2), Cm(2.2), Cm(2.2), Cm(2.2)]
    _apply_widths(table, widths)


def _apply_widths(table, widths):
    for row in table.rows:
        for idx, w in enumerate(widths):
            if idx < len(row.cells):
                row.cells[idx].width = w


def _is_numeric_order(order_str):
    """判断是否为数值型谐波次数（过滤 THD, DC 等非数值行）"""
    try:
        float(order_str)
        return True
    except ValueError:
        return False


def _filter_harmonic_rows(rows, skip_fundamental=True):
    """
    过滤谐波数据行。
    - 去除 THD, DC 等非数值行
    - skip_fundamental=True 时去除 H1（基波=100%，不需要展示）
    """
    result = []
    for r in rows:
        order = r["order"]
        if not _is_numeric_order(order):
            continue
        if skip_fundamental:
            try:
                if float(order) == 1.0:
                    continue
            except ValueError:
                pass
        result.append(r)
    return result


def _filter_interharmonic_rows(rows):
    """
    过滤间谐波数据行。
    - 去除 THD, DC 等非数值行
    - 去除基波 "1"（与谐波基波重复）
    - 去除 0.5（DC-like 次谐波，不在标准报告范围）
    """
    SKIP_ORDERS = {1.0, 0.5}
    result = []
    for r in rows:
        order = r["order"]
        if not _is_numeric_order(order):
            continue
        try:
            if float(order) in SKIP_ORDERS:
                continue
        except ValueError:
            pass
        result.append(r)
    return result


# ============================================================
# 主流程
# ============================================================

def generate_report(base_dir, output_path):
    """
    按照模板格式生成报告。

    文档结构（参照 HJP260166P-03 模板）：
      - A4 纵向
      - 标题页
      - 各功率区间数据以大合并表格呈现
      - 综合值独立成表
    """
    doc = Document()

    # ---- 页面设置（A4 纵向）----
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)

    # ---- 文档样式 ----
    style = doc.styles['Normal']
    style.font.name = '宋体'
    style.font.size = Pt(10)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # ---- 标题 ----
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run("电能质量测试数据汇总报告")
    run.font.size = Pt(16)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.bold = True

    para2 = doc.add_paragraph()
    para2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = para2.add_run(f"生成日期：{datetime.now().strftime('%Y年%m月%d日')}")
    run2.font.size = Pt(9)
    run2.font.name = "宋体"
    run2._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run2.font.color.rgb = RGBColor(128, 128, 128)

    doc.add_paragraph()

    # =============================================
    # 第一部分：谐波
    # =============================================
    heading = doc.add_heading("1  谐波", level=1)
    _set_heading_font(heading)

    print("\n=== 第一部分：谐波 ===")
    _process_harmonic_group(doc, base_dir, "谐波", "谐波", section_num=1, is_interharmonic=False)

    # =============================================
    # 第二部分：间谐波
    # =============================================
    doc.add_page_break()
    heading = doc.add_heading("2  间谐波", level=1)
    _set_heading_font(heading)

    print("\n=== 第二部分：间谐波 ===")
    _process_harmonic_group(doc, base_dir, "间谐波", "间谐波", section_num=2, is_interharmonic=True)

    # =============================================
    # 第三部分：电能质量
    # =============================================
    doc.add_page_break()
    heading = doc.add_heading("3  电能质量", level=1)
    _set_heading_font(heading)

    print("\n=== 第三部分：电能质量 ===")
    _process_power_quality_group(doc, base_dir, section_num=3)

    # ---- 保存 ----
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    doc.save(output_path)
    print(f"\n[DONE] 报告已生成: {output_path}")


def _process_harmonic_group(doc, base_dir, folder_name, order_label, section_num, is_interharmonic=False):
    """
    处理谐波/间谐波组：
      - 电流综合值（7列表）
      - 电流各功率区间（8列合并表）
      - 电压综合值（7列表）
      - 电压各功率区间（8列合并表）
    """
    folder = os.path.join(base_dir, folder_name)
    if not os.path.isdir(folder):
        print(f"  [警告] 目录不存在: {folder}")
        return

    # 收集所有区间数据
    interval_current = {}   # {interval_name: [rows]}
    interval_voltage = {}
    comprehensive_current = None
    comprehensive_voltage = None

    for kw, iname in zip(INTERVAL_FILE_KEYWORDS, INTERVAL_NAMES):
        filepath = find_file_by_interval(folder, kw)
        if filepath:
            data = parse_harmonic_file_both(filepath)
            interval_current[iname] = data["current"]
            interval_voltage[iname] = data["voltage"]
            print(f"  {iname}: {len(data['current'])} rows (current) + {len(data['voltage'])} rows (voltage)")
        else:
            print(f"  [警告] {iname} 文件未找到")
            interval_current[iname] = []
            interval_voltage[iname] = []

    # 综合值文件
    comp_file = find_file_by_interval(folder, "综合值")
    if comp_file:
        data = parse_harmonic_file_both(comp_file)
        comprehensive_current = data["current"]
        comprehensive_voltage = data["voltage"]
        print(f"  综合值: {len(data['current'])} rows")

    # 选择过滤函数：谐波跳过 H1（基波），间谐波跳过 1 和 0.5
    if is_interharmonic:
        row_filter = _filter_interharmonic_rows
        order_col_name = "间谐波次数"
    else:
        row_filter = lambda r: _filter_harmonic_rows(r, skip_fundamental=True)
        order_col_name = "谐波次数"

    table_num = 0

    # ---- 电流部分 ----
    doc.add_heading(f"电流{order_label}", level=2)

    if comprehensive_current:
        table_num += 1
        add_table_caption(doc, f"表 {section_num}-{table_num}  {order_label}电流最大值（综合值）")
        add_combined_table_7col(doc, comprehensive_current, unit="A", row_filter=row_filter,
                                order_name=order_col_name)

    # 各功率区间合并表
    table_num += 1
    add_table_caption(doc, f"表 {section_num}-{table_num}  各功率区间{order_label}电流实测值")
    interval_list = [(name, interval_current.get(name, [])) for name in INTERVAL_NAMES]
    add_interval_table_8col(doc, interval_list, unit="A", order_name=order_col_name,
                            row_filter=row_filter)

    # ---- 电压部分 ----
    doc.add_heading(f"电压{order_label}", level=2)

    if comprehensive_voltage:
        table_num += 1
        add_table_caption(doc, f"表 {section_num}-{table_num}  {order_label}电压含有率（综合值）")
        add_combined_table_7col(doc, comprehensive_voltage, unit="%", row_filter=row_filter,
                                order_name=order_col_name)

    table_num += 1
    add_table_caption(doc, f"表 {section_num}-{table_num}  各功率区间{order_label}电压含有率")
    interval_list_v = [(name, interval_voltage.get(name, [])) for name in INTERVAL_NAMES]
    add_interval_table_8col(doc, interval_list_v, unit="%", order_name=order_col_name,
                            row_filter=row_filter)


def _process_power_quality_group(doc, base_dir, section_num=3):
    """处理电能质量组"""
    folder = os.path.join(base_dir, "电能质量")
    if not os.path.isdir(folder):
        print(f"  [警告] 目录不存在: {folder}")
        return

    interval_data = {}
    comprehensive_data = None

    for kw, iname in zip(INTERVAL_FILE_KEYWORDS, INTERVAL_NAMES):
        filepath = find_file_by_interval(folder, kw)
        if filepath:
            rows = parse_power_quality_file(filepath)
            interval_data[iname] = rows
            print(f"  {iname}: {len(rows)} rows")
        else:
            print(f"  [警告] {iname} 文件未找到")
            interval_data[iname] = []

    # 综合值
    comp_file = find_file_by_interval(folder, "综合值")
    if comp_file:
        comprehensive_data = parse_power_quality_file(comp_file)
        print(f"  综合值: {len(comprehensive_data)} rows")

    table_num = 0

    # 综合值表
    if comprehensive_data:
        doc.add_heading("电能质量参数（综合值）", level=2)
        table_num += 1
        add_table_caption(doc, f"表 {section_num}-{table_num}  电能质量参数综合值")
        add_pq_combined_table(doc, comprehensive_data)

    # 各功率区间表
    doc.add_heading("各功率区间电能质量参数", level=2)
    table_num += 1
    add_table_caption(doc, f"表 {section_num}-{table_num}  各功率区间电能质量参数实测值")
    interval_list = [(name, interval_data.get(name, [])) for name in INTERVAL_NAMES]
    add_pq_interval_table(doc, interval_list)


def _set_heading_font(heading):
    """设置标题字体"""
    for run in heading.runs:
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="电能质量测试数据汇总报告生成工具 v2.0"
    )
    parser.add_argument("-i", "--base-dir", default=None,
                        help="数据源根目录，默认为脚本所在目录")
    parser.add_argument("-o", "--output", default=None,
                        help="输出 Word 文件路径")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = args.base_dir or script_dir
    output_path = args.output or os.path.join(script_dir, "output", "电能质量测试数据汇总报告.docx")

    if not os.path.isdir(base_dir):
        print(f"[ERROR] 数据目录不存在: {base_dir}")
        return 1

    print("=" * 60)
    print("  电能质量测试数据汇总报告生成工具 v2.0")
    print("=" * 60)
    print(f"  数据目录: {base_dir}")
    print(f"  输出文件: {output_path}")
    print("=" * 60)

    generate_report(base_dir, output_path)
    return 0


if __name__ == "__main__":
    main()
