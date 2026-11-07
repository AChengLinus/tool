/* ============================================================
   工具助手（RAG）配置
   ------------------------------------------------------------
   proxyUrl: 你的 AI 代理地址（Cloudflare Worker / 自有服务器均可）。
             留空 = 纯站内检索模式：回答来自本地知识库摘录，不调用大模型。
             示例：'https://rag.acheng9616.com/chat'
             代理源码与部署步骤见 rag/proxy/worker.js 和 rag/README.md。

   byok:     仅供站长本机调试用（浏览器 localStorage 里放自己的 Key）。
             公开访客页面请勿配置，密钥暴露在浏览器里等于公开。
   ============================================================ */
window.RAG_CONFIG = {
  // 代理地址。部署好 Worker 后把地址填在这里即可启用 AI 回答。
  proxyUrl: '',

  // 回答长度与检索数量
  maxTokens: 700,
  temperature: 0.2,
  topK: 4,

  // 每个浏览器每天最多提问次数（前端软限额，真正的限额在代理端做）
  dailyLimit: 20,

  // 本机调试用直连配置，仅在 localStorage['rag.byok.key'] 存在时生效。
  // 控制台执行 localStorage.setItem('rag.byok.key','sk-你的Key') 后刷新，
  // 只有你自己的浏览器会调用大模型，公开访客仍是站内检索。
  byok: {
    baseUrl: 'https://api.qnaigc.com/v1',
    model: 'qiniu/conatus-free'
  }
};
