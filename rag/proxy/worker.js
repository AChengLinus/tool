/**
 * 工具助手 · Cloudflare Worker 代理
 * ------------------------------------------------------------
 * 作用：把网页上的提问转发给大模型，API Key 只保存在 Worker 的环境变量里，
 *       访客的浏览器拿不到 Key。
 *
 * 部署（免费套餐即可）：
 *   1. npm i -g wrangler && wrangler login
 *   2. wrangler secret put LLM_API_KEY        # 粘贴你的 Key
 *   3. wrangler deploy
 *   4. 把部署得到的 https://xxx.workers.dev/chat 填进 rag/config.js 的 proxyUrl
 *
 * 可选变量（wrangler.toml [vars] 或控制台设置）：
 *   LLM_BASE_URL      默认 https://api.deepseek.com/v1
 *   LLM_MODEL         默认 deepseek-chat
 *   ALLOWED_ORIGINS   允许的站点，逗号分隔
 *   MAX_TOKENS        单次回答上限，默认 700
 *   DAILY_LIMIT       每 IP 每日次数，默认 30
 *   RAG_LIMIT         KV 命名空间绑定（不绑定则不做服务端限额）
 */

const DEFAULTS = {
  LLM_BASE_URL: 'https://api.deepseek.com/v1',
  LLM_MODEL: 'deepseek-chat',
  ALLOWED_ORIGINS: 'https://tool.acheng9616.com,http://127.0.0.1:8000,http://localhost:8000',
  MAX_TOKENS: '700',
  DAILY_LIMIT: '30'
};

function corsHeaders(request, env) {
  const origin = request.headers.get('Origin') || '';
  return {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin',
    'Cache-Control': 'no-store'
  };
}

function json(body, status, request, env) {
  return new Response(JSON.stringify(body), {
    status: status || 200,
    headers: corsHeaders(request, env)
  });
}

function allowedOrigins(env) {
  return String(env.ALLOWED_ORIGINS || DEFAULTS.ALLOWED_ORIGINS)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

function originAllowed(request, env) {
  const origin = request.headers.get('Origin') || '';
  if (!origin) return true; // curl / 服务端调用，接口本身不额外放权限
  return allowedOrigins(env).includes(origin);
}

function cleanMessages(input) {
  if (!Array.isArray(input)) return null;
  const out = [];
  for (const m of input.slice(0, 12)) {
    if (!m || typeof m.content !== 'string') continue;
    const role = m.role === 'assistant' ? 'assistant' : m.role === 'system' ? 'system' : 'user';
    const content = m.content.slice(0, 8000);
    if (!content.trim()) continue;
    out.push({ role, content });
  }
  if (!out.length) return null;
  const total = out.reduce((n, m) => n + m.content.length, 0);
  if (total > 24000) return null;
  if (!out.some((m) => m.role === 'system')) {
    out.unshift({
      role: 'system',
      content: '你是「项目工具盒」的站内助手，用简体中文简洁回答访客关于本站工具的问题；不确定时请让访客联系 @AChengLinus。'
    });
  }
  return out;
}

async function bumpQuota(env, ip) {
  if (!env.RAG_LIMIT) return { ok: true, remaining: null };
  const limit = parseInt(env.DAILY_LIMIT || DEFAULTS.DAILY_LIMIT, 10) || 30;
  const day = new Date().toISOString().slice(0, 10);
  const key = `rl:${day}:${ip}`;
  const current = parseInt((await env.RAG_LIMIT.get(key)) || '0', 10) || 0;
  if (current >= limit) return { ok: false, remaining: 0 };
  await env.RAG_LIMIT.put(key, String(current + 1), { expirationTtl: 172800 });
  return { ok: true, remaining: limit - current - 1 };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    }

    if (request.method === 'GET' && url.pathname === '/health') {
      return json({ ok: true }, 200, request, env);
    }

    if (request.method !== 'POST' || url.pathname !== '/chat') {
      return json({ error: 'not_found' }, 404, request, env);
    }

    if (!originAllowed(request, env)) {
      return json({ error: 'origin_not_allowed' }, 403, request, env);
    }

    if (!env.LLM_API_KEY) {
      return json({ error: 'server_not_configured' }, 500, request, env);
    }

    let payload;
    try {
      payload = await request.json();
    } catch (e) {
      return json({ error: 'invalid_json' }, 400, request, env);
    }

    const messages = cleanMessages(payload && payload.messages);
    if (!messages) {
      return json({ error: 'invalid_messages' }, 400, request, env);
    }

    const ip =
      request.headers.get('CF-Connecting-IP') ||
      request.headers.get('X-Forwarded-For') ||
      'unknown';
    const quota = await bumpQuota(env, ip);
    if (!quota.ok) {
      return json({ error: 'quota_exceeded' }, 429, request, env);
    }

    const maxTokens = Math.min(
      parseInt(env.MAX_TOKENS || DEFAULTS.MAX_TOKENS, 10) || 700,
      1200
    );
    const base = String(env.LLM_BASE_URL || DEFAULTS.LLM_BASE_URL).replace(/\/+$/, '');
    const model = env.LLM_MODEL || DEFAULTS.LLM_MODEL;

    let upstream;
    try {
      upstream = await fetch(base + '/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer ' + env.LLM_API_KEY
        },
        body: JSON.stringify({
          model,
          messages,
          max_tokens: maxTokens,
          temperature: 0.2,
          stream: false
        }),
        signal: AbortSignal.timeout(35000)
      });
    } catch (e) {
      console.error('upstream fetch failed', e && e.message);
      return json({ error: 'upstream_unreachable' }, 502, request, env);
    }

    if (upstream.status === 429) {
      return json({ error: 'upstream_rate_limited' }, 429, request, env);
    }
    if (!upstream.ok) {
      const detail = await upstream.text().catch(() => '');
      console.error('upstream error', upstream.status, detail.slice(0, 300));
      return json({ error: 'upstream_error' }, 502, request, env);
    }

    let data;
    try {
      data = await upstream.json();
    } catch (e) {
      return json({ error: 'bad_upstream_json' }, 502, request, env);
    }

    const answer =
      data && data.choices && data.choices[0] && data.choices[0].message
        ? data.choices[0].message.content
        : '';
    if (!answer || !String(answer).trim()) {
      return json({ error: 'empty_answer' }, 502, request, env);
    }

    return json(
      {
        answer: String(answer).trim(),
        remaining: quota.remaining
      },
      200,
      request,
      env
    );
  }
};
