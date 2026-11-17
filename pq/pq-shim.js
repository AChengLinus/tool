/* 电能质量报告工具 — 纯静态版运行环境
 * 用 Pyodide 在浏览器里跑原来的 Python 解析 / Word 生成代码，
 * 通过覆写 window.fetch 把页面里的 /api/* 请求转成浏览器内调用。
 * 文件只写入浏览器内存文件系统，不会上传到任何服务器。
 */
(function () {
  'use strict';

  var PYODIDE_BASES = [
    'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/',
    'https://fastly.jsdelivr.net/pyodide/v0.28.3/full/',
  ];

  var nativeFetch = window.fetch.bind(window);
  var initPromise = null;
  var pyodide = null;
  var helper = null;
  var sid = (window.crypto && crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random())
    .replace(/[^a-z0-9]/gi, '').slice(0, 12) || 'session';

  function setBanner(text, kind) {
    var el = document.getElementById('pq-runtime');
    if (!el) return;
    el.textContent = text;
    el.className = 'pq-banner' + (kind ? ' pq-banner--' + kind : '');
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error('加载失败: ' + src)); };
      document.head.appendChild(s);
    });
  }

  async function fetchText(url) {
    var res = await nativeFetch(url, { cache: 'no-cache' });
    if (!res.ok) throw new Error('读取 ' + url + ' 失败: ' + res.status);
    return res.text();
  }

  function wheelURL(name) {
    return new URL('vendor/' + name, document.baseURI).href;
  }

  async function boot() {
    setBanner('正在加载浏览器运行环境（首次约 15–40 MB，之后浏览器会缓存）…', 'loading');

    var lastErr = null;
    for (var i = 0; i < PYODIDE_BASES.length; i++) {
      try {
        await loadScript(PYODIDE_BASES[i] + 'pyodide.js');
        pyodide = await loadPyodide({ indexURL: PYODIDE_BASES[i] });
        break;
      } catch (err) {
        lastErr = err;
        pyodide = null;
      }
    }
    if (!pyodide) throw lastErr || new Error('无法加载 Pyodide');

    setBanner('正在准备 Python 依赖（pandas / lxml / python-docx）…', 'loading');
    await pyodide.loadPackage(['pandas', 'lxml', 'micropip']);

    var micropip = pyodide.pyimport('micropip');
    await micropip.install(wheelURL('typing_extensions-4.16.0-py3-none-any.whl'), { deps: false });
    await micropip.install(wheelURL('et_xmlfile-2.0.0-py3-none-any.whl'), { deps: false });
    await micropip.install(wheelURL('openpyxl-3.1.5-py2.py3-none-any.whl'), { deps: false });
    await micropip.install(wheelURL('python_docx-1.1.2-py3-none-any.whl'), { deps: false });
    await micropip.install(wheelURL('xlrd-2.0.1-py2.py3-none-any.whl'), { deps: false });

    pyodide.FS.mkdirTree('/pq');
    var files = ['flask.py', 'generate_report.py', 'app.py', 'web_helper.py'];
    for (var j = 0; j < files.length; j++) {
      var code = await fetchText('runtime/' + files[j]);
      pyodide.FS.writeFile('/pq/' + files[j], code);
    }

    pyodide.runPython("import sys; sys.path.insert(0, '/pq')");
    helper = pyodide.runPython('import web_helper; web_helper');
    pyodide.runPython('web_helper.init(' + JSON.stringify(sid) + ')');

    window.__pqReady = true;
    setBanner('✓ 纯浏览器运行环境已就绪 · 所有文件只在本机处理，不会上传服务器', 'ready');
  }

  function ensureReady() {
    if (!initPromise) {
      initPromise = boot().catch(function (err) {
        window.__pqError = String(err && err.message ? err.message : err);
        setBanner('运行环境加载失败：' + window.__pqError + '（请刷新重试）', 'error');
        if (window.console) console.error(err);
        throw err;
      });
    }
    return initPromise;
  }

  function jsonResponse(obj, status) {
    return new Response(JSON.stringify(obj), {
      status: status || 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
    });
  }

  function fileToTempPath(file) {
    return file.arrayBuffer().then(function (buf) {
      pyodide.FS.writeFile('/tmp/pq-upload.bin', new Uint8Array(buf));
      return '/tmp/pq-upload.bin';
    });
  }

  function readJSONBody(init) {
    if (!init || !init.body) return Promise.resolve({});
    var body = init.body;
    if (typeof body === 'string') {
      try { return Promise.resolve(JSON.parse(body)); } catch (e) { return Promise.resolve({}); }
    }
    if (body && typeof body.text === 'function') {
      return body.text().then(function (text) {
        try { return JSON.parse(text); } catch (e) { return {}; }
      });
    }
    return Promise.resolve({});
  }

  async function handleUpload(init) {
    var fd = init && init.body;
    if (!fd || typeof fd.get !== 'function') return jsonResponse({ ok: false, error: '缺少参数' }, 400);

    var file = fd.get('file');
    var section = fd.get('section');
    var interval = fd.get('interval');
    if (!file || !section || !interval) return jsonResponse({ ok: false, error: '缺少参数' }, 400);

    var tempPath = await fileToTempPath(file);
    var py = 'web_helper.upload(' + JSON.stringify(tempPath) + ',' + JSON.stringify(file.name) + ',' +
      JSON.stringify(section) + ',' + JSON.stringify(interval) + ')';
    var result = pyodide.runPython(py);
    return jsonResponse(JSON.parse(result));
  }

  async function handleStatus(init) {
    var body = await readJSONBody(init);
    var result = pyodide.runPython('web_helper.status(' + JSON.stringify(body.section || '') + ')');
    return jsonResponse(JSON.parse(result));
  }

  async function handleClear(init) {
    var body = await readJSONBody(init);
    var result;
    if (body && body.section) {
      result = pyodide.runPython('web_helper.clear_section(' + JSON.stringify(body.section) + ')');
    } else {
      result = pyodide.runPython('web_helper.clear_all()');
    }
    return jsonResponse(JSON.parse(result));
  }

  async function handleGenerate(init) {
    var body = await readJSONBody(init);
    var sections = body.sections || ['harmonic', 'interharmonic', 'power_quality'];
    var path;
    try {
      path = pyodide.runPython('web_helper.generate(' + JSON.stringify(JSON.stringify(sections)) + ')');
    } catch (err) {
      if (window.console) console.error(err);
      return jsonResponse({ ok: false, error: String(err) }, 500);
    }
    var bytes = pyodide.FS.readFile(path);
    var copy = new Uint8Array(bytes);
    window.__pqLastReport = copy;
    try { pyodide.FS.unlink(path); } catch (e) { /* ignore */ }
    return new Response(copy, {
      status: 200,
      headers: {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'Content-Disposition': 'attachment; filename="power-quality-report.docx"',
      },
    });
  }

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    var path = url.split('?')[0];

    if (path.indexOf('/api/') !== 0) return nativeFetch(input, init);

    return ensureReady().then(function () {
      switch (path) {
        case '/api/upload': return handleUpload(init);
        case '/api/status': return handleStatus(init);
        case '/api/clear':
        case '/api/clear-one': return handleClear(init);
        case '/api/generate': return handleGenerate(init);
        case '/api/import-folder':
          return jsonResponse({ ok: false, error: '静态版无法读取本机目录路径，请用右侧「选择文件夹」按钮导入' });
        default:
          return jsonResponse({ ok: false, error: '静态版未实现该接口: ' + path }, 404);
      }
    });
  };

  // 页面加载后预热运行环境，用户点上传时无需再等
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureReady);
  } else {
    ensureReady();
  }
})();
