# -*- coding: utf-8 -*-
"""极简 flask 兼容层，只用于在浏览器（Pyodide）里导入 app.py 的 _build_report。

app.py 顶层只用到 Flask 类、route 装饰器、config 和若干响应函数；
真正的请求处理由 pq-shim.js 完成，这里不需要实现任何 Web 行为。
"""


class _Config(dict):
    pass


class Flask:
    def __init__(self, *args, **kwargs):
        self.config = _Config()
        self.secret_key = None

    def route(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

    def run(self, *args, **kwargs):
        return None


class _Request:
    form = {}
    files = {}

    @staticmethod
    def get_json(*args, **kwargs):
        return {}


request = _Request()
session = {}


def jsonify(*args, **kwargs):
    return None


def send_file(*args, **kwargs):
    return None


def render_template_string(template):
    return template
