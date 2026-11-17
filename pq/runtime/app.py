#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电能质量测试数据汇总报告 — Web 前端
启动: python app.py  → 浏览器访问 http://localhost:5000
"""

import os
import re
import json
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify, send_file, session

# 导入已有的数据处理逻辑
import generate_report as gr

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'power-quality-report-tool-2026')
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_UPLOAD_MB', '50')) * 1024 * 1024
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if os.environ.get('SESSION_COOKIE_SECURE', '0') == '1':
    app.config['SESSION_COOKIE_SECURE'] = True

# 上传文件存储根目录
# 容器/云主机默认写系统临时目录（避免只读文件系统），本地可用 UPLOAD_ROOT 覆盖
UPLOAD_ROOT = os.environ.get(
    'UPLOAD_ROOT',
    os.path.join(tempfile.gettempdir(), 'pq-report-uploads'),
)
SESSION_TTL_HOURS = float(os.environ.get('SESSION_TTL_HOURS', '12'))
_last_cleanup = 0.0

# 三个子项目配置
SECTIONS = {
    'harmonic': {
        'name': '谐波',
        'type': 'harmonic',
        'is_interharmonic': False,
    },
    'interharmonic': {
        'name': '间谐波',
        'type': 'harmonic',
        'is_interharmonic': True,
    },
    'power_quality': {
        'name': '电能质量',
        'type': 'power_quality',
        'is_interharmonic': False,
    },
}

INTERVAL_NAMES = gr.INTERVAL_NAMES
INTERVAL_KEYWORDS = gr.INTERVAL_FILE_KEYWORDS


# ============================================================
# 工具函数
# ============================================================

def get_session_dir():
    """获取当前 session 的上传目录"""
    _maybe_cleanup()
    if 'uid' not in session:
        session['uid'] = uuid.uuid4().hex[:12]
    d = os.path.join(UPLOAD_ROOT, session['uid'])
    os.makedirs(d, exist_ok=True)
    return d


def cleanup_stale_sessions():
    """删除超过 SESSION_TTL_HOURS 未更新的上传目录，避免磁盘被占满。"""
    try:
        if not os.path.isdir(UPLOAD_ROOT):
            return
        cutoff = time.time() - SESSION_TTL_HOURS * 3600
        for entry in os.scandir(UPLOAD_ROOT):
            try:
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        pass


def _maybe_cleanup():
    """每小时最多执行一次过期目录清理。"""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup >= 3600:
        _last_cleanup = now
        cleanup_stale_sessions()


def detect_interval_from_filename(filename):
    """根据文件名自动识别功率区间"""
    for kw, name in zip(INTERVAL_KEYWORDS, INTERVAL_NAMES):
        if kw in filename:
            return name
    if '综合值' in filename or '综合' in filename:
        return '运行区间综合值'
    return None


# ============================================================
# 路由
# ============================================================

@app.route('/')
def index():
    """主页面"""
    return render_template_string(HTML_TEMPLATE)


@app.route('/healthz')
def healthz():
    """容器平台健康检查"""
    return jsonify({'ok': True, 'service': 'power-quality-report'})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """上传单个文件到指定区间"""
    section = request.form.get('section', '')
    interval = request.form.get('interval', '')
    file = request.files.get('file')

    if not file or not section or not interval:
        return jsonify({'ok': False, 'error': '缺少参数'}), 400

    if section not in SECTIONS:
        return jsonify({'ok': False, 'error': '无效的子项目'}), 400

    # 保存文件
    sdir = os.path.join(get_session_dir(), section, interval)
    os.makedirs(sdir, exist_ok=True)

    # 清除该区间的旧文件
    for old in os.listdir(sdir):
        os.remove(os.path.join(sdir, old))

    safe_name = file.filename
    filepath = os.path.join(sdir, safe_name)
    file.save(filepath)

    # 尝试解析验证
    try:
        if SECTIONS[section]['type'] == 'harmonic':
            data = gr.parse_harmonic_file_both(filepath)
            rows_cur = len(data['current'])
            rows_vol = len(data['voltage'])
            msg = f'电流 {rows_cur} 行 + 电压 {rows_vol} 行'
        else:
            rows = gr.parse_power_quality_file(filepath)
            msg = f'{len(rows)} 个参数'
        return jsonify({'ok': True, 'filename': safe_name, 'rows': msg})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'文件解析失败: {str(e)}'}), 400


@app.route('/api/import-folder', methods=['POST'])
def import_folder():
    """批量导入目录"""
    data = request.get_json()
    section = data.get('section', '')
    folder_path = data.get('path', '').strip()

    if not section or not folder_path:
        return jsonify({'ok': False, 'error': '缺少参数'}), 400

    if not os.path.isdir(folder_path):
        return jsonify({'ok': False, 'error': f'目录不存在: {folder_path}'}), 400

    sdir = os.path.join(get_session_dir(), section)
    os.makedirs(sdir, exist_ok=True)

    results = {}
    files_in_dir = os.listdir(folder_path)

    # 匹配功率区间文件
    for fname in files_in_dir:
        full = os.path.join(folder_path, fname)
        if not os.path.isfile(full):
            continue
        if not fname.lower().endswith(('.xls', '.xlsx')):
            continue

        interval = detect_interval_from_filename(fname)
        if interval:
            # 复制文件
            dest_dir = os.path.join(sdir, interval)
            os.makedirs(dest_dir, exist_ok=True)
            for old in os.listdir(dest_dir):
                os.remove(os.path.join(dest_dir, old))
            shutil.copy2(full, os.path.join(dest_dir, fname))

            # 快速验证
            try:
                if SECTIONS[section]['type'] == 'harmonic':
                    d = gr.parse_harmonic_file_both(full)
                    results[interval] = f'{fname} (电流{len(d["current"])}行+电压{len(d["voltage"])}行)'
                else:
                    r = gr.parse_power_quality_file(full)
                    results[interval] = f'{fname} ({len(r)}参数)'
            except Exception as e:
                results[interval] = f'{fname} (解析失败: {e})'
        else:
            # 尝试匹配综合值
            if '综合值' in fname:
                interval = '运行区间综合值'
                dest_dir = os.path.join(sdir, interval)
                os.makedirs(dest_dir, exist_ok=True)
                for old in os.listdir(dest_dir):
                    os.remove(os.path.join(dest_dir, old))
                shutil.copy2(full, os.path.join(dest_dir, fname))
                results[interval] = fname

    return jsonify({'ok': True, 'matched': results})


@app.route('/api/status', methods=['POST'])
def get_status():
    """获取当前各区间文件状态"""
    data = request.get_json()
    section = data.get('section', '')
    if section not in SECTIONS:
        return jsonify({'ok': False}), 400

    sdir = os.path.join(get_session_dir(), section)
    status = {}
    all_intervals = INTERVAL_NAMES + ['运行区间综合值']

    for interval in all_intervals:
        idir = os.path.join(sdir, interval)
        if os.path.isdir(idir):
            files = [f for f in os.listdir(idir) if f.endswith(('.xls', '.xlsx'))]
            status[interval] = files[0] if files else None
        else:
            status[interval] = None

    ready = sum(1 for v in status.values() if v is not None)
    total = len(all_intervals)
    return jsonify({'ok': True, 'status': status, 'ready': ready, 'total': total})


@app.route('/api/generate', methods=['POST'])
def generate_report():
    """生成 Word 报告并返回下载"""
    data = request.get_json(silent=True) or {}
    sections_to_include = data.get('sections', ['harmonic', 'interharmonic', 'power_quality'])

    sdir = get_session_dir()
    # 每次生成用独立文件名，避免并发请求互相覆盖
    output_path = os.path.join(sdir, f'report_{uuid.uuid4().hex[:8]}.docx')

    try:
        doc = _build_report(sdir, sections_to_include)
        doc.save(output_path)
        resp = send_file(
            output_path,
            as_attachment=True,
            download_name=f'电能质量测试数据汇总报告_{datetime.now().strftime("%Y%m%d_%H%M%S")}.docx',
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

        # 文件发完后删除临时文件，避免重复生成占满磁盘
        @resp.call_on_close
        def _remove_report():
            try:
                os.remove(output_path)
            except OSError:
                pass

        return resp
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/clear', methods=['POST'])
def clear_files():
    """清空所有上传文件"""
    sdir = get_session_dir()
    if os.path.isdir(sdir):
        shutil.rmtree(sdir)
        os.makedirs(sdir, exist_ok=True)
    return jsonify({'ok': True})


# ============================================================
# 报告构建（复用 generate_report 的函数）
# ============================================================

def _build_report(session_dir, sections_to_include):
    """基于上传文件构建 Word 文档"""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # 页面设置
    section_obj = doc.sections[0]
    section_obj.page_width = Cm(21.0)
    section_obj.page_height = Cm(29.7)
    section_obj.left_margin = Cm(2.0)
    section_obj.right_margin = Cm(2.0)
    section_obj.top_margin = Cm(2.0)
    section_obj.bottom_margin = Cm(2.0)

    style = doc.styles['Normal']
    style.font.name = '宋体'
    style.font.size = Pt(10)
    style._element.rPr.rFonts.set(gr.qn('w:eastAsia'), '宋体')

    # 标题
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run("电能质量测试数据汇总报告")
    run.font.size = Pt(16)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(gr.qn('w:eastAsia'), '宋体')
    run.bold = True

    para2 = doc.add_paragraph()
    para2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = para2.add_run(f"生成日期：{datetime.now().strftime('%Y年%m月%d日')}")
    run2.font.size = Pt(9)
    run2.font.name = "宋体"
    run2._element.rPr.rFonts.set(gr.qn('w:eastAsia'), '宋体')
    run2.font.color.rgb = RGBColor(128, 128, 128)

    doc.add_paragraph()

    section_map = {
        'harmonic': (1, '谐波', False),
        'interharmonic': (2, '间谐波', True),
        'power_quality': (3, '电能质量', False),
    }

    for key in sections_to_include:
        if key not in section_map:
            continue
        sec_num, name, is_inter = section_map[key]
        heading = doc.add_heading(f"{sec_num}  {name}", level=1)
        _set_heading_font(heading)

        if key == 'power_quality':
            _build_pq_section(doc, session_dir, sec_num)
        else:
            _build_harmonic_section(doc, session_dir, key, name, sec_num, is_inter)

        if key != sections_to_include[-1]:
            doc.add_page_break()

    return doc


def _build_harmonic_section(doc, session_dir, section_key, order_label, section_num, is_interharmonic):
    """构建谐波/间谐波部分"""
    sdir = os.path.join(session_dir, section_key)

    interval_current = {}
    interval_voltage = {}
    comprehensive_current = None
    comprehensive_voltage = None

    for iname in gr.INTERVAL_NAMES:
        idir = os.path.join(sdir, iname)
        if os.path.isdir(idir):
            files = [f for f in os.listdir(idir) if f.endswith(('.xls', '.xlsx'))]
            if files:
                fp = os.path.join(idir, files[0])
                data = gr.parse_harmonic_file_both(fp)
                interval_current[iname] = data['current']
                interval_voltage[iname] = data['voltage']
                continue
        interval_current[iname] = []
        interval_voltage[iname] = []

    # 综合值
    comp_dir = os.path.join(sdir, '运行区间综合值')
    if os.path.isdir(comp_dir):
        files = [f for f in os.listdir(comp_dir) if f.endswith(('.xls', '.xlsx'))]
        if files:
            data = gr.parse_harmonic_file_both(os.path.join(comp_dir, files[0]))
            comprehensive_current = data['current']
            comprehensive_voltage = data['voltage']

    if is_interharmonic:
        row_filter = gr._filter_interharmonic_rows
        order_col_name = "间谐波次数"
    else:
        row_filter = lambda r: gr._filter_harmonic_rows(r, skip_fundamental=True)
        order_col_name = "谐波次数"

    table_num = 0

    # 电流部分
    doc.add_heading(f"电流{order_label}", level=2)

    if comprehensive_current:
        table_num += 1
        gr.add_table_caption(doc, f"表 {section_num}-{table_num}  {order_label}电流最大值（综合值）")
        gr.add_combined_table_7col(doc, comprehensive_current, unit="A", row_filter=row_filter,
                                   order_name=order_col_name)

    table_num += 1
    gr.add_table_caption(doc, f"表 {section_num}-{table_num}  各功率区间{order_label}电流实测值")
    ilist = [(n, interval_current.get(n, [])) for n in gr.INTERVAL_NAMES]
    gr.add_interval_table_8col(doc, ilist, unit="A", order_name=order_col_name, row_filter=row_filter)

    # 电压部分
    doc.add_heading(f"电压{order_label}", level=2)

    if comprehensive_voltage:
        table_num += 1
        gr.add_table_caption(doc, f"表 {section_num}-{table_num}  {order_label}电压含有率（综合值）")
        gr.add_combined_table_7col(doc, comprehensive_voltage, unit="%", row_filter=row_filter,
                                   order_name=order_col_name)

    table_num += 1
    gr.add_table_caption(doc, f"表 {section_num}-{table_num}  各功率区间{order_label}电压含有率")
    ilist_v = [(n, interval_voltage.get(n, [])) for n in gr.INTERVAL_NAMES]
    gr.add_interval_table_8col(doc, ilist_v, unit="%", order_name=order_col_name, row_filter=row_filter)


def _build_pq_section(doc, session_dir, section_num):
    """构建电能质量部分"""
    sdir = os.path.join(session_dir, 'power_quality')

    interval_data = {}
    for iname in gr.INTERVAL_NAMES:
        idir = os.path.join(sdir, iname)
        if os.path.isdir(idir):
            files = [f for f in os.listdir(idir) if f.endswith(('.xls', '.xlsx'))]
            if files:
                interval_data[iname] = gr.parse_power_quality_file(os.path.join(idir, files[0]))
                continue
        interval_data[iname] = []

    comprehensive_data = None
    comp_dir = os.path.join(sdir, '运行区间综合值')
    if os.path.isdir(comp_dir):
        files = [f for f in os.listdir(comp_dir) if f.endswith(('.xls', '.xlsx'))]
        if files:
            comprehensive_data = gr.parse_power_quality_file(os.path.join(comp_dir, files[0]))

    table_num = 0

    if comprehensive_data:
        doc.add_heading("电能质量参数（综合值）", level=2)
        table_num += 1
        gr.add_table_caption(doc, f"表 {section_num}-{table_num}  电能质量参数综合值")
        gr.add_pq_combined_table(doc, comprehensive_data)

    doc.add_heading("各功率区间电能质量参数", level=2)
    table_num += 1
    gr.add_table_caption(doc, f"表 {section_num}-{table_num}  各功率区间电能质量参数实测值")
    ilist = [(n, interval_data.get(n, [])) for n in gr.INTERVAL_NAMES]
    gr.add_pq_interval_table(doc, ilist)


def _set_heading_font(heading):
    for run in heading.runs:
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(gr.qn('w:eastAsia'), '宋体')


# ============================================================
# HTML 模板
# ============================================================

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>电能质量测试数据汇总报告生成工具</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:"Microsoft YaHei","微软雅黑",SimSun,"宋体",sans-serif; background:#f0f2f5; color:#333; min-height:100vh; }
.header { background:linear-gradient(135deg,#1a3a5c,#2d6aa0); color:#fff; padding:20px 40px; text-align:center; }
.header h1 { font-size:22px; font-weight:500; letter-spacing:2px; }
.header .sub { font-size:12px; opacity:0.7; margin-top:4px; }
.container { max-width:1100px; margin:0 auto; padding:20px; }
.section-selector { display:flex; align-items:center; gap:16px; padding:14px 20px; background:#fff; border-radius:8px; margin-bottom:12px; box-shadow:0 1px 4px rgba(0,0,0,.04); }
.section-label { font-weight:600; font-size:13px; color:#555; }
.check-label { font-size:13px; cursor:pointer; display:flex; align-items:center; gap:4px; color:#333; }
.check-label input[type=checkbox] { width:16px; height:16px; cursor:pointer; accent-color:#2d6aa0; }
.tabs { display:flex; gap:0; margin-bottom:0; }
.tab { flex:1; padding:14px 20px; text-align:center; cursor:pointer; background:#e8ecf1; border:none; font-size:15px; font-weight:500; color:#666; transition:all .2s; border-radius:8px 8px 0 0; }
.tab.active { background:#fff; color:#1a3a5c; font-weight:700; box-shadow:0 -2px 8px rgba(0,0,0,.06); }
.tab:hover:not(.active) { background:#dde3ea; }
.panel { background:#fff; border-radius:0 0 8px 8px; padding:24px; box-shadow:0 2px 12px rgba(0,0,0,.06); display:none; }
.panel.active { display:block; }
.toolbar { display:flex; gap:12px; align-items:center; margin-bottom:20px; flex-wrap:wrap; }
.toolbar input[type=text] { flex:1; min-width:300px; padding:10px 14px; border:1px solid #d0d5dd; border-radius:6px; font-size:13px; }
.btn { padding:10px 22px; border:none; border-radius:6px; cursor:pointer; font-size:13px; font-weight:500; transition:all .2s; }
.btn-blue { background:#2d6aa0; color:#fff; }
.btn-blue:hover { background:#1a3a5c; }
.btn-outline { background:#fff; color:#2d6aa0; border:1px solid #2d6aa0; }
.btn-outline:hover { background:#eef4fa; }
.btn-green { background:#27ae60; color:#fff; font-size:15px; padding:14px 40px; }
.btn-green:hover { background:#219a52; }
.btn-red { background:#e74c3c; color:#fff; }
.btn-red:hover { background:#c0392b; }
table.upload-table { width:100%; border-collapse:collapse; }
table.upload-table td, table.upload-table th { padding:8px 10px; border-bottom:1px solid #eee; }
table.upload-table th { text-align:left; font-weight:600; color:#555; font-size:13px; width:140px; }
.drop-zone { border:2px dashed #c0c8d2; border-radius:6px; padding:12px 16px; text-align:center; cursor:pointer; transition:all .2s; font-size:12px; color:#999; min-height:44px; display:flex; align-items:center; justify-content:center; gap:6px; }
.drop-zone:hover, .drop-zone.dragover { border-color:#2d6aa0; color:#2d6aa0; background:#f5f9fd; }
.drop-zone.has-file { border-style:solid; border-color:#27ae60; background:#f0faf4; color:#27ae60; }
.drop-zone .icon { font-size:18px; }
.status-row { margin-top:12px; padding:8px 14px; border-radius:6px; font-size:13px; }
.status-ok { background:#eafaf1; color:#27ae60; }
.status-warn { background:#fef9e7; color:#f39c12; }
.status-error { background:#fdedec; color:#e74c3c; }
.footer { display:flex; gap:16px; justify-content:center; margin-top:28px; padding:20px; }
.result-area { margin-top:16px; padding:12px 16px; background:#f8f9fb; border-radius:6px; font-size:12px; color:#666; max-height:150px; overflow-y:auto; display:none; }
input[type=file] { display:none; }
.progress-wrap { margin-top:12px; display:none; }
.progress-bar { height:6px; background:#e0e0e0; border-radius:3px; overflow:hidden; }
.progress-fill { height:100%; background:#2d6aa0; width:0%; transition:width .3s; border-radius:3px; }
</style>
</head>
<body>

<div class="header">
  <h1>电能质量测试数据汇总报告生成工具</h1>
  <div class="sub">Upload Excel data files for each power interval, then generate the report</div>
</div>

<div class="container">

  <!-- 导出项目选择 -->
  <div class="section-selector">
    <span class="section-label">选择导出项目：</span>
    <label class="check-label"><input type="checkbox" id="chk-harmonic" checked onchange="onSectionCheck()"> 谐波</label>
    <label class="check-label"><input type="checkbox" id="chk-interharmonic" checked onchange="onSectionCheck()"> 间谐波</label>
    <label class="check-label"><input type="checkbox" id="chk-power_quality" checked onchange="onSectionCheck()"> 电能质量</label>
    <span style="margin-left:12px;font-size:12px;color:#888;" id="check-hint">已选 3 项</span>
  </div>

  <!-- 标签页 -->
  <div class="tabs">
    <button class="tab active" onclick="switchTab('harmonic')">&#9889; 谐波</button>
    <button class="tab" onclick="switchTab('interharmonic')">&#9889; 间谐波</button>
    <button class="tab" onclick="switchTab('power_quality')">&#9889; 电能质量</button>
  </div>

  <!-- 谐波面板 -->
  <div class="panel active" id="panel-harmonic">
    <div class="toolbar">
      <input type="text" id="folder-harmonic" placeholder="粘贴目录路径，如: C:\Users\...\谐波\">
      <button class="btn btn-blue" onclick="importFolder('harmonic')">&#128194; 导入路径</button>
      <button class="btn btn-outline" onclick="document.getElementById('folder-picker-harmonic').click()">&#128193; 选择文件夹</button>
      <input type="file" id="folder-picker-harmonic" webkitdirectory directory style="display:none" onchange="handleFolderPick(this,'harmonic')">
      <button class="btn btn-outline" onclick="clearSection('harmonic')">&#128465; 清空</button>
    </div>
    <div class="result-area" id="result-harmonic"></div>
    <table class="upload-table" id="table-harmonic"></table>
    <div class="status-row status-warn" id="status-harmonic">等待上传文件...</div>
  </div>

  <!-- 间谐波面板 -->
  <div class="panel" id="panel-interharmonic">
    <div class="toolbar">
      <input type="text" id="folder-interharmonic" placeholder="粘贴目录路径，如: C:\Users\...\间谐波\">
      <button class="btn btn-blue" onclick="importFolder('interharmonic')">&#128194; 导入路径</button>
      <button class="btn btn-outline" onclick="document.getElementById('folder-picker-interharmonic').click()">&#128193; 选择文件夹</button>
      <input type="file" id="folder-picker-interharmonic" webkitdirectory directory style="display:none" onchange="handleFolderPick(this,'interharmonic')">
      <button class="btn btn-outline" onclick="clearSection('interharmonic')">&#128465; 清空</button>
    </div>
    <div class="result-area" id="result-interharmonic"></div>
    <table class="upload-table" id="table-interharmonic"></table>
    <div class="status-row status-warn" id="status-interharmonic">等待上传文件...</div>
  </div>

  <!-- 电能质量面板 -->
  <div class="panel" id="panel-power_quality">
    <div class="toolbar">
      <input type="text" id="folder-power_quality" placeholder="粘贴目录路径，如: C:\Users\...\电能质量\">
      <button class="btn btn-blue" onclick="importFolder('power_quality')">&#128194; 导入路径</button>
      <button class="btn btn-outline" onclick="document.getElementById('folder-picker-power_quality').click()">&#128193; 选择文件夹</button>
      <input type="file" id="folder-picker-power_quality" webkitdirectory directory style="display:none" onchange="handleFolderPick(this,'power_quality')">
      <button class="btn btn-outline" onclick="clearSection('power_quality')">&#128465; 清空</button>
    </div>
    <div class="result-area" id="result-power_quality"></div>
    <table class="upload-table" id="table-power_quality"></table>
    <div class="status-row status-warn" id="status-power_quality">等待上传文件...</div>
  </div>

  <!-- 底部按钮 -->
  <div class="footer">
    <button class="btn btn-green" onclick="generateReport()">&#128196; 生成报告</button>
    <button class="btn btn-red" onclick="clearAll()">&#128465; 清空全部</button>
    <span style="font-size:12px;color:#888;align-self:center;" id="footer-hint"></span>
  </div>
  <div class="progress-wrap" id="progress-wrap">
    <div style="text-align:center;font-size:12px;color:#666;margin-bottom:6px;">正在生成报告...</div>
    <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
  </div>
  <div style="text-align:center;margin-top:16px;font-size:12px;color:#999;" id="global-status"></div>

</div>

<script>
const INTERVALS = [
  '0%-10%Pn','10%-20%Pn','20%-30%Pn','30%-40%Pn','40%-50%Pn',
  '50%-60%Pn','60%-70%Pn','70%-80%Pn','80%-90%Pn','90%-100%Pn',
  '运行区间综合值'
];
const INTERVAL_LABELS = {
  '0%-10%Pn':'0% – 10% Pn','10%-20%Pn':'10% – 20% Pn','20%-30%Pn':'20% – 30% Pn',
  '30%-40%Pn':'30% – 40% Pn','40%-50%Pn':'40% – 50% Pn','50%-60%Pn':'50% – 60% Pn',
  '60%-70%Pn':'60% – 70% Pn','70%-80%Pn':'70% – 80% Pn','80%-90%Pn':'80% – 90% Pn',
  '90%-100%Pn':'90% – 100% Pn','运行区间综合值':'综合值'
};
let currentTab = 'harmonic';

// 初始化所有面板的表格
['harmonic','interharmonic','power_quality'].forEach(s => buildTable(s));

function buildTable(section) {
  const table = document.getElementById('table-' + section);
  let html = '<tr><th>功率区间</th><th>上传文件</th><th style="width:60px">状态</th></tr>';
  INTERVALS.forEach(iv => {
    html += `<tr>
      <td><strong>${INTERVAL_LABELS[iv] || iv}</strong></td>
      <td>
        <div class="drop-zone" id="drop-${section}-${encodeURIComponent(iv)}"
             onclick="document.getElementById('file-${section}-${encodeURIComponent(iv)}').click()"
             ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropFile(event,'${section}','${iv}')">
          <span class="icon">&#128206;</span> 拖拽或点击上传
        </div>
        <input type="file" id="file-${section}-${encodeURIComponent(iv)}"
               accept=".xls,.xlsx" onchange="uploadFile(this,'${section}','${iv}')">
      </td>
      <td><span id="badge-${section}-${encodeURIComponent(iv)}" style="color:#ccc;">—</span></td>
    </tr>`;
  });
  table.innerHTML = html;
}

function switchTab(section) {
  currentTab = section;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.tab:nth-child(${section==='harmonic'?1:section==='interharmonic'?2:3})`).classList.add('active');
  document.getElementById('panel-' + section).classList.add('active');
  refreshStatus(section);
}

function dragOver(e) { e.preventDefault(); e.currentTarget.classList.add('dragover'); }
function dragLeave(e) { e.currentTarget.classList.remove('dragover'); }

function dropFile(e, section, interval) {
  e.preventDefault();
  e.currentTarget.classList.remove('dragover');
  const file = e.dataTransfer.files[0];
  if (file) doUpload(file, section, interval);
}

function uploadFile(input, section, interval) {
  const file = input.files[0];
  if (file) doUpload(file, section, interval);
}

function doUpload(file, section, interval) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('section', section);
  formData.append('interval', interval);

  const dropZone = document.getElementById('drop-' + section + '-' + encodeURIComponent(interval));
  const badge = document.getElementById('badge-' + section + '-' + encodeURIComponent(interval));

  dropZone.innerHTML = '<span class="icon">&#9203;</span> 上传中...';
  badge.innerHTML = '<span style="color:#f39c12;">&#9203;</span>';

  fetch('/api/upload', { method:'POST', body:formData })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        dropZone.classList.add('has-file');
        dropZone.innerHTML = `<span class="icon">&#128196;</span> ${data.filename}`;
        badge.innerHTML = `<span style="color:#27ae60;" title="${data.rows}">&#10004;</span>`;
      } else {
        dropZone.classList.remove('has-file');
        dropZone.innerHTML = '<span class="icon">&#9888;</span> 上传失败，重试';
        badge.innerHTML = `<span style="color:#e74c3c;" title="${data.error}">&#10008;</span>`;
      }
      refreshStatus(section);
    })
    .catch(err => {
      dropZone.classList.remove('has-file');
      dropZone.innerHTML = '<span class="icon">&#9888;</span> 网络错误，重试';
      badge.innerHTML = '<span style="color:#e74c3c;">&#10008;</span>';
    });
}

function importFolder(section) {
  const path = document.getElementById('folder-' + section).value.trim();
  if (!path) { alert('请输入目录路径'); return; }

  const resultArea = document.getElementById('result-' + section);
  resultArea.style.display = 'block';
  resultArea.innerHTML = '正在扫描目录...';

  fetch('/api/import-folder', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({section, path})
  })
  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      const matched = data.matched;
      const keys = Object.keys(matched);
      resultArea.innerHTML = `&#10004; 成功匹配 ${keys.length} 个区间:<br>` +
        keys.map(k => `&nbsp;&nbsp;${k}: ${matched[k]}`).join('<br>');

      // 更新界面
      keys.forEach(iv => {
        const dropZone = document.getElementById('drop-' + section + '-' + encodeURIComponent(iv));
        const badge = document.getElementById('badge-' + section + '-' + encodeURIComponent(iv));
        if (dropZone) {
          dropZone.classList.add('has-file');
          dropZone.innerHTML = `<span class="icon">&#128196;</span> ${matched[iv]}`;
        }
        if (badge) badge.innerHTML = '<span style="color:#27ae60;">&#10004;</span>';
      });
      refreshStatus(section);
    } else {
      resultArea.innerHTML = `&#10008; ${data.error}`;
    }
  })
  .catch(err => {
    resultArea.innerHTML = '&#10008; 请求失败: ' + err;
  });
}

function refreshStatus(section) {
  fetch('/api/status', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({section})
  })
  .then(r => r.json())
  .then(data => {
    if (!data.ok) return;
    const statusDiv = document.getElementById('status-' + section);
    const ready = data.ready;
    const total = data.total;
    if (ready === total) {
      statusDiv.className = 'status-row status-ok';
      statusDiv.innerHTML = `&#10004; 全部就绪 (${ready}/${total}) — 可以生成报告`;
    } else if (ready > 0) {
      statusDiv.className = 'status-row status-warn';
      statusDiv.innerHTML = `&#9888; 部分就绪 (${ready}/${total}) — 缺少 ${total-ready} 个区间`;
    } else {
      statusDiv.className = 'status-row status-warn';
      statusDiv.innerHTML = `等待上传文件... (0/${total})`;
    }
    // 更新全局状态
    updateGlobalStatus();
  });
}

function updateGlobalStatus() {
  Promise.all(['harmonic','interharmonic','power_quality'].map(s =>
    fetch('/api/status', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({section:s})
    }).then(r => r.json())
  )).then(results => {
    const totalReady = results.reduce((sum, r) => sum + (r.ready||0), 0);
    const totalAll = results.reduce((sum, r) => sum + (r.total||0), 0);
    const gs = document.getElementById('global-status');
    gs.innerHTML = `全局状态: ${totalReady}/${totalAll} 文件就绪`;
  });
}

function clearSection(section) {
  if (!confirm('确定清空当前标签页的所有文件？')) return;
  // 清空上传的文件（后端会清理对应section目录）
  INTERVALS.forEach(iv => {
    const dropZone = document.getElementById('drop-' + section + '-' + encodeURIComponent(iv));
    const badge = document.getElementById('badge-' + section + '-' + encodeURIComponent(iv));
    if (dropZone) {
      dropZone.classList.remove('has-file');
      dropZone.innerHTML = '<span class="icon">&#128206;</span> 拖拽或点击上传';
    }
    if (badge) badge.innerHTML = '<span style="color:#ccc;">—</span>';
  });
  const resultArea = document.getElementById('result-' + section);
  if (resultArea) { resultArea.style.display = 'none'; resultArea.innerHTML = ''; }
  fetch('/api/clear-one', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({section})
  });
  refreshStatus(section);
}

function clearAll() {
  if (!confirm('确定清空所有已上传的文件？')) return;
  fetch('/api/clear', {method:'POST'}).then(() => {
    ['harmonic','interharmonic','power_quality'].forEach(s => {
      INTERVALS.forEach(iv => {
        const dropZone = document.getElementById('drop-' + s + '-' + encodeURIComponent(iv));
        const badge = document.getElementById('badge-' + s + '-' + encodeURIComponent(iv));
        if (dropZone) {
          dropZone.classList.remove('has-file');
          dropZone.innerHTML = '<span class="icon">&#128206;</span> 拖拽或点击上传';
        }
        if (badge) badge.innerHTML = '<span style="color:#ccc;">—</span>';
      });
      document.getElementById('status-' + s).className = 'status-row status-warn';
      document.getElementById('status-' + s).innerHTML = '等待上传文件...';
      const ra = document.getElementById('result-' + s);
      if (ra) { ra.style.display = 'none'; ra.innerHTML = ''; }
    });
    document.getElementById('global-status').innerHTML = '';
  });
}

function getCheckedSections() {
  const all = ['harmonic','interharmonic','power_quality'];
  return all.filter(s => document.getElementById('chk-'+s).checked);
}

function onSectionCheck() {
  const checked = getCheckedSections();
  document.getElementById('check-hint').textContent = '已选 ' + checked.length + ' 项';
  updateGlobalStatus();
}

function handleFolderPick(input, section) {
  const files = input.files;
  if (!files || files.length === 0) return;

  const resultArea = document.getElementById('result-' + section);
  resultArea.style.display = 'block';
  resultArea.innerHTML = '正在导入 ' + files.length + ' 个文件...';

  let done = 0;
  const total = files.length;
  const matched = {};

  function uploadNext(i) {
    if (i >= files.length) {
      // 全部完成
      const keys = Object.keys(matched);
      resultArea.innerHTML = '&#10004; 成功匹配 ' + keys.length + ' 个区间:<br>' +
        keys.map(k => '&nbsp;&nbsp;' + k + ': ' + matched[k]).join('<br>');
      // 更新界面
      keys.forEach(iv => {
        const dropZone = document.getElementById('drop-' + section + '-' + encodeURIComponent(iv));
        const badge = document.getElementById('badge-' + section + '-' + encodeURIComponent(iv));
        if (dropZone) {
          dropZone.classList.add('has-file');
          dropZone.innerHTML = '<span class="icon">&#128196;</span> ' + matched[iv];
        }
        if (badge) badge.innerHTML = '<span style="color:#27ae60;">&#10004;</span>';
      });
      refreshStatus(section);
      return;
    }

    const file = files[i];
    const interval = detectInterval(file.name);
    if (!interval) {
      done++;
      uploadNext(i + 1);
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('section', section);
    formData.append('interval', interval);

    fetch('/api/upload', { method:'POST', body:formData })
      .then(r => r.json())
      .then(data => {
        done++;
        if (data.ok) matched[interval] = data.filename;
        resultArea.innerHTML = '导入中... ' + done + '/' + total;
        uploadNext(i + 1);
      })
      .catch(() => {
        done++;
        uploadNext(i + 1);
      });
  }

  uploadNext(0);
}

function detectInterval(filename) {
  const map = {
    '0～10%':'0%-10%Pn','0~10%':'0%-10%Pn','0-10%':'0%-10%Pn',
    '10～20%':'10%-20%Pn','10~20%':'10%-20%Pn','10-20%':'10%-20%Pn',
    '20～30%':'20%-30%Pn','20~30%':'20%-30%Pn','20-30%':'20%-30%Pn',
    '30～40%':'30%-40%Pn','30~40%':'30%-40%Pn','30-40%':'30%-40%Pn',
    '40～50%':'40%-50%Pn','40~50%':'40%-50%Pn','40-50%':'40%-50%Pn',
    '50～60%':'50%-60%Pn','50~60%':'50%-60%Pn','50-60%':'50%-60%Pn',
    '60～70%':'60%-70%Pn','60~70%':'60%-70%Pn','60-70%':'60%-70%Pn',
    '70～80%':'70%-80%Pn','70~80%':'70%-80%Pn','70-80%':'70%-80%Pn',
    '80～90%':'80%-90%Pn','80~90%':'80%-90%Pn','80-90%':'80%-90%Pn',
    '90～100%':'90%-100%Pn','90~100%':'90%-100%Pn','90-100%':'90%-100%Pn',
    '综合值':'运行区间综合值','综合':'运行区间综合值'
  };
  for (const [kw, iv] of Object.entries(map)) {
    if (filename.includes(kw)) return iv;
  }
  return null;
}

function generateReport() {
  const sections = getCheckedSections();
  if (sections.length === 0) {
    alert('请至少选择一个导出项目');
    return;
  }

  // 检查选中的 section 是否都有文件
  Promise.all(sections.map(s =>
    fetch('/api/status', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({section:s}) })
      .then(r => r.json())
  )).then(results => {
    const noData = results.filter((r, i) => r.ready === 0);
    if (noData.length > 0) {
      const names = noData.map((r, i) => {
        const keys = ['harmonic','interharmonic','power_quality'];
        return ['谐波','间谐波','电能质量'][keys.indexOf(sections[i])];
      }).filter((_,i) => results[i].ready === 0);
      if (!confirm('以下项目无数据：' + names.join('、') + '。\n\n是否继续生成（这些项目将为空）？')) return;
    }

    document.getElementById('footer-hint').textContent = '正在生成 ' + sections.length + ' 个项目...';

    const progressWrap = document.getElementById('progress-wrap');
    const fill = document.getElementById('progress-fill');
    progressWrap.style.display = 'block';
    fill.style.width = '30%';

    fetch('/api/generate', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sections})
    })
    .then(r => {
      fill.style.width = '90%';
      if (!r.ok) return r.json().then(d => { throw new Error(d.error || '生成失败'); });
      return r.blob();
    })
    .then(blob => {
      fill.style.width = '100%';
      setTimeout(() => { progressWrap.style.display = 'none'; fill.style.width = '0%'; document.getElementById('footer-hint').textContent = ''; }, 800);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = '电能质量测试数据汇总报告.docx';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    })
    .catch(err => {
      progressWrap.style.display = 'none';
      document.getElementById('footer-hint').textContent = '';
      alert('生成报告失败: ' + err.message);
    });
  });
}

// 添加清空单个section的后端路由支持
// （在页面加载时检查状态）
['harmonic','interharmonic','power_quality'].forEach(s => refreshStatus(s));
</script>
</body>
</html>
'''


# 额外路由：清空单个 section
@app.route('/api/clear-one', methods=['POST'])
def clear_one_section():
    data = request.get_json()
    section = data.get('section', '')
    if section not in SECTIONS:
        return jsonify({'ok': False}), 400
    sdir = os.path.join(get_session_dir(), section)
    if os.path.isdir(sdir):
        shutil.rmtree(sdir)
        os.makedirs(sdir, exist_ok=True)
    return jsonify({'ok': True})


# ============================================================
# 启动
# ============================================================

def get_local_ip():
    """获取本机局域网 IP"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'


if __name__ == '__main__':
    os.makedirs(UPLOAD_ROOT, exist_ok=True)
    cleanup_stale_sessions()
    local_ip = get_local_ip()
    port = int(os.environ.get('PORT', '5000'))
    host = os.environ.get('HOST', '0.0.0.0')
    print()
    print('=' * 60)
    print('  电能质量测试数据汇总报告生成工具 — Web 版')
    print('=' * 60)
    print()
    print(f'  本机访问:  http://localhost:{port}')
    print(f'  局域网访问: http://{local_ip}:{port}')
    print(f'  上传目录:  {UPLOAD_ROOT}（{SESSION_TTL_HOURS:g} 小时后清理）')
    print()
    print('  按 Ctrl+C 停止服务器')
    print('=' * 60)
    print()
    # 关闭 debug 以允许局域网访问（debug=True 时仅监听 localhost）
    app.run(host=host, port=port, debug=False)
