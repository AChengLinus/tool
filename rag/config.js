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

  // 直连模式：没有配置 proxyUrl 时，浏览器直接调用模型。
  // 优先级：localStorage['rag.byok.key']（你本机调试）> 下面的 apiKey（访客共用）。
  //
  // ⚠️ 安全警告：下面的 apiKey 会随网页公开，任何人 F12 都能看到并拿走。
  // 这是“免登录给所有访客用”的代价；只适合免费额度，被刷爆后去七牛控制台重置 Key。
  // 免费模型还有全局并发限制，偶尔返回 429；前端会自动重试 2 次，仍失败则退回站内资料摘录。
  // 以后部署了代理，把 apiKey 清空、改填 proxyUrl，Key 就只留在服务端。
  byok: {
    baseUrl: 'https://api.qnaigc.com/v1',
    model: 'qiniu/conatus-free',
    apiKey: 'sk-4030ac7b4b5f2ca25c58258fc1b244c662fc418f6c336baa7213c756cc54767a'
  }
};
