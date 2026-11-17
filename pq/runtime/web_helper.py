# -*- coding: utf-8 -*-
"""静态版（Pyodide）桥接层：给 pq-shim.js 提供上传 / 状态 / 生成 / 清空能力。"""
import json
import os
import shutil
import time

import generate_report as gr
import app as web_app

ROOT = '/uploads'
SID = 'default'


def init(session_id):
    """初始化一个页面会话（只存在浏览器内存文件系统中）。"""
    global SID
    SID = session_id or 'default'
    os.makedirs(root(), exist_ok=True)
    return SID


def root():
    return os.path.join(ROOT, SID)


def _dir(*parts):
    path = os.path.join(root(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def upload(src_path, filename, section, interval):
    """保存用户选择的文件并立即解析校验，返回 JSON 字符串。"""
    if section not in web_app.SECTIONS:
        return json.dumps({'ok': False, 'error': '无效的子项目'}, ensure_ascii=False)

    target_dir = _dir(section, interval)
    for old in os.listdir(target_dir):
        try:
            os.remove(os.path.join(target_dir, old))
        except OSError:
            pass

    dest = os.path.join(target_dir, os.path.basename(filename))
    with open(src_path, 'rb') as src, open(dest, 'wb') as out:
        shutil.copyfileobj(src, out)

    try:
        if web_app.SECTIONS[section]['type'] == 'harmonic':
            data = gr.parse_harmonic_file_both(dest)
            msg = f'电流 {len(data["current"])} 行 + 电压 {len(data["voltage"])} 行'
        else:
            rows = gr.parse_power_quality_file(dest)
            msg = f'{len(rows)} 个参数'
        return json.dumps({'ok': True, 'filename': os.path.basename(filename), 'rows': msg},
                          ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        try:
            os.remove(dest)
        except OSError:
            pass
        return json.dumps({'ok': False, 'error': f'文件解析失败: {exc}'}, ensure_ascii=False)


def status(section):
    if section not in web_app.SECTIONS:
        return json.dumps({'ok': False}, ensure_ascii=False)

    intervals = list(gr.INTERVAL_NAMES) + ['运行区间综合值']
    base = _dir(section)
    result = {}
    for interval in intervals:
        path = os.path.join(base, interval)
        files = []
        if os.path.isdir(path):
            files = [f for f in os.listdir(path) if f.lower().endswith(('.xls', '.xlsx'))]
        result[interval] = files[0] if files else None

    ready = sum(1 for value in result.values() if value)
    return json.dumps({'ok': True, 'status': result, 'ready': ready, 'total': len(intervals)},
                      ensure_ascii=False)


def clear_section(section):
    if section in web_app.SECTIONS:
        target = os.path.join(root(), section)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        _dir(section)
    return json.dumps({'ok': True})


def clear_all():
    shutil.rmtree(root(), ignore_errors=True)
    os.makedirs(root(), exist_ok=True)
    return json.dumps({'ok': True})


def generate(sections_json):
    """生成 Word 报告，返回文件路径（供 JS 用 FS.readFile 读取）。"""
    sections = json.loads(sections_json)
    doc = web_app._build_report(_dir(), sections)
    out = os.path.join(_dir(), f'report_{int(time.time() * 1000)}.docx')
    doc.save(out)
    return out
