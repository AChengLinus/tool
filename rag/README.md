# 工具助手（站内 RAG 问答）

项目工具盒右下角的悬浮助手：访客可以问 EL 裁剪、PR 数据处理、图片标记、电站仿真偏差分析这 4 个工具怎么用、参数怎么填、常见问题怎么处理。回答只基于本站整理的资料，不编造别的内容。

## 它是怎么工作的

```
访客提问
  │
  ├─ 1. 本地检索（浏览器内，零请求）
  │     rag/retriever.js 用 BM25 + 中文 bigram 从 rag/kb.json 里找出最相关的 4 段资料
  │
  └─ 2. 组织回答
        ├─ 没配置代理（默认）：直接把检索到的资料摘录展示给访客
        └─ 配置了 proxyUrl：把「问题 + 检索到的资料」发给代理，由大模型组织成自然语言回答
```

- 检索、分块、排序全部在浏览器里完成，不依赖任何第三方搜索服务。
- 没有配置模型时也能用：访客看到的是资料原文摘录 + 来源链接，不消耗任何额度。
- 配置模型后，页面只发送「问题 + 命中的资料片段」，不会上传整页内容或访客信息。

## 关于 API Key 的安全（重要）

**静态网页里不能放共享 Key。** GitHub Pages 只分发 HTML/JS，任何写进 JS 的 Key 打开开发者工具就能看到，等于公开。所以本站采用：

| 方式 | Key 在哪 | 适用场景 |
| --- | --- | --- |
| 站内检索（默认） | 没有 Key | 公开访客，零成本 |
| 服务端代理（推荐） | 只存在 Worker / 服务器的环境变量里 | 公开访客 + 真实 AI 回答 |
| 本机 BYOK | 只存在**你自己浏览器**的 localStorage | 站长本机调试，不要给访客用 |

`rag/config.js` 的 `byok.apiKeys` 是**公开共享 Key**（方案 D，当前线上采用），访客页面会带 Key；`localStorage['rag.byok.key']` 只用于站长本机覆盖测试。安全取舍见下文「方案 D」。

## 目录结构

```
rag/
├── knowledge/            知识库源文件（改这里）
│   ├── platform.md       平台介绍、入口、通用问题
│   ├── el.md             EL 裁剪
│   ├── pr.md             PR 数据处理
│   ├── pt.md             图片标记
│   └── dat.md            电站仿真偏差分析
├── build-kb.mjs          把 knowledge/*.md 编译成 kb.json（Node，无依赖）
├── kb.json               编译产物（页面实际加载的文件）
├── retriever.js          浏览器端检索（BM25 + 中文分词）
├── test-retriever.mjs    检索回归测试（10 条）
├── config.js             前端配置（代理地址、限额等）
├── assistant.js          悬浮形象 + 面板 + 问答逻辑
├── assistant.css         样式
└── proxy/
    ├── worker.js         Cloudflare Worker 代理
    ├── wrangler.toml     Worker 配置
    └── server.py         通用 Python 代理（标准库，无依赖）
```

## 改知识库

1. 编辑 `rag/knowledge/*.md`。格式：

```markdown
---
title: EL 裁剪
aliases: [EL, el裁剪, 电致发光]
url: https://el.acheng9616.com/
---

## 这是什么

……

### 常见问题

……

## 怎么使用

……
```

- `##` 是一级小节，`###` 是子问题；两者都会成为独立检索块。
- 一段太长会按段落自动切到 1100 字以内。
- `aliases` 用来补充同义词（访客可能说“EL 裁剪”“el 工具”“电致发光”）。

2. 重新编译并跑测试：

```bash
node rag/build-kb.mjs        # 生成 rag/kb.json
node rag/test-retriever.mjs  # 10 条检索用例，应全部 PASS
```

3. 刷新页面即可（`index.html` 已引入 `rag/assistant.js`）。

## 启用 AI 回答

### 方案 A：Cloudflare Worker（有 HTTPS，免费额度够用）

```bash
cd rag/proxy
npm i -g wrangler
wrangler login
wrangler secret put LLM_API_KEY     # 粘贴 Key，不会进入代码仓库
wrangler deploy
```

部署成功后会得到 `https://tool-rag-proxy.xxx.workers.dev/chat`，把它填到 `rag/config.js`：

```js
window.RAG_CONFIG = {
  proxyUrl: 'https://tool-rag-proxy.xxx.workers.dev/chat',
  // ...
};
```

建议在 Cloudflare 控制台给 Worker 绑定 KV（变量名 `RAG_LIMIT`），这样服务端会按 IP 做每日限额（默认 30 次）。不绑定也能用，只是限额只在前端。

> 注意：`*.workers.dev` 在国内部分网络下可能不稳定。如果访客主要在国内，优先用方案 B 或给 Worker 绑定自己的域名（需要把域名接入 Cloudflare）。

#### 七牛云 / qnaigc 配置（当前使用的模型）

`wrangler.toml` 里的 `[vars]` 已经填好，部署时只需要写 Secret：

| 项 | 值 |
|---|---|
| Base URL | `https://api.qnaigc.com/v1` |
| Model ID | `qiniu/conatus-free` |
| API Key | 只通过 `wrangler secret put LLM_API_KEY` 写入 |

```bash
wrangler secret put LLM_API_KEY     # 粘贴七牛云 Key，回车
wrangler deploy
```

站点目前证书还没签发、走的是 `http://tool.acheng9616.com`，所以 `ALLOWED_ORIGINS` 里 http/https 两条都留着；证书生效并切到 HTTPS 后，可以把 http 那条删掉再部署一次。

> 安全提醒：任何出现在聊天、截图、Git 历史里的 Key 都应视为已泄露。如果 Key 曾经发出去过，先在七牛控制台重置，再把新 Key 写进 Secret；不要写进 `config.js` 或任何会提交的文件。

### 方案 B：自己的服务器（Python，标准库）

```bash
set LLM_API_KEY=sk-xxxx
set LLM_BASE_URL=https://api.qnaigc.com/v1
set LLM_MODEL=qiniu/conatus-free
set ALLOWED_ORIGINS=https://tool.acheng9616.com,http://tool.acheng9616.com
set HOST=0.0.0.0
set PORT=8787
python rag/proxy/server.py
```

页面是 HTTPS，所以代理也必须是 HTTPS（用 Nginx / Caddy 反代到 8787 并配证书），否则浏览器会拦截混合内容。然后把 `https://你的域名/chat` 填进 `proxyUrl`。

### 方案 C：本机调试（BYOK）

不想部署代理、只想自己试试时，在浏览器控制台执行一次：

```js
localStorage.setItem('rag.byok.key', 'sk-你的Key');
```

刷新后助手会用 `config.js` 里 `byok.baseUrl` + `byok.model` 直连。**这只适合你自己的浏览器**；公开页面上不要预置 Key。

### 方案 D：前端直连共享 Key（当前线上采用）

`config.js` 的 `byok.apiKeys` 里预置了七牛云的主 Key 和备用 Key，访客浏览器直接请求 `api.qnaigc.com`，不需要部署代理。

- 优点：零运维，打开网页就能用。
- 缺点：Key 随网页公开，任何人都能拿走；免费模型还有全局限流，偶尔 429。
- 前端已做：按「主 Key → 备用 Key」轮换，遇到 429/5xx/Key 失效自动换下一个并退避重试（最多 6 次），仍失败就退回站内资料摘录；每浏览器每天 20 次软限额。
- 某个 Key 被刷爆/吊销时：去七牛控制台重置，更新 `config.js` 的 `apiKeys` 数组并推送；长期使用建议换回方案 A/B。

## 限额与成本

- 前端：`config.js` 的 `dailyLimit`（默认 20 次/浏览器/天），存在 localStorage，清缓存可绕过，只是体验层限制。
- 服务端：Worker KV 或 `server.py` 的 `DAILY_LIMIT`（默认 30 次/IP/天），这才是真正的限额。
- 回答长度：`maxTokens` 默认 700；检索固定 4 段资料，单次请求的输入通常 2~4k 字符。

## 本地预览

```bash
# 在仓库根目录
python -m http.server 8000
# 打开 http://127.0.0.1:8000/?rag=open
```

`?rag=open` 会直接展开助手面板，`?ask=EL 怎么用` 可以自动提一个问题，方便调试。

## 悬浮形象

- `assets/rag/pet-1..4.png`：右下角随机切换的人物图（透明背景、无圆框，整张图完整显示，不裁头）。
- 每次重新打开或刷新页面会随机换一张（同一次页面会话内保持不变）；打开/关闭面板不会换。
- 想换图：把新图按 `pet-1..4.png` 命名覆盖即可，建议透明 PNG、人物高度 ≥ 400px；面板头部、欢迎语和消息里的小图会自动复用同一张。
- 目前的 4 张原图是半身构图（到大腿/手部为止）。如果要真正“从头到脚”的立绘，用全身图覆盖同名文件即可，无需改代码。

## 排错

- **面板打开但一直“正在加载站内资料”**：`rag/kb.json` 没上传或路径不对；检查 Network 面板。
- **回答总是“站内资料里没有这个说明”**：资料没覆盖这个问题，补充 `knowledge/*.md` 后重新 `build-kb`。
- **状态显示“AI 已就绪”但回答报错**：看 Console 的 `[assistant] 模型调用失败`；多为代理地址、CORS（`ALLOWED_ORIGINS` 没包含当前域名）或 Key 失效。
- **改了知识库但页面没变**：忘记跑 `node rag/build-kb.mjs`，或浏览器缓存了 `kb.json`（已设置 `cache: 'no-cache'`，一般刷新即可）。
