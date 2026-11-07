/**
 * 站内检索：中文 bigram + BM25，无第三方依赖。
 * 浏览器里挂到 window.RAGRetriever；Node 里可 require（测试用）。
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RAGRetriever = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  var CJK_RE = /[\u4e00-\u9fff]+/g;
  var ASCII_RE = /[a-z0-9][a-z0-9+#_.\-]*/g;

  var STOP_CHARS = '的了吗呢吧啊呀哦嗯是我你他她它这那么什怎如何哪谁请帮想问下可不可以能要会';

  function isStopBigram(a, b) {
    return STOP_CHARS.indexOf(a) !== -1 && STOP_CHARS.indexOf(b) !== -1;
  }

  function tokenize(text) {
    if (!text) return [];
    var lower = String(text).toLowerCase();
    var tokens = [];

    var ascii = lower.match(ASCII_RE) || [];
    for (var i = 0; i < ascii.length; i++) {
      if (ascii[i].length > 1 || /[0-9]/.test(ascii[i])) tokens.push(ascii[i]);
    }

    var runs = lower.match(CJK_RE) || [];
    for (var r = 0; r < runs.length; r++) {
      var run = runs[r];
      if (run.length === 1) {
        tokens.push(run);
        continue;
      }
      for (var j = 0; j < run.length - 1; j++) {
        var a = run.charAt(j);
        var b = run.charAt(j + 1);
        if (!isStopBigram(a, b)) tokens.push(a + b);
      }
      // 短词整体保留，帮助命中「无人机」「黑边」这类固定词
      if (run.length <= 4) tokens.push(run);
    }
    return tokens;
  }

  function buildIndex(kb) {
    var chunks = (kb && kb.chunks) || [];
    var docs = [];
    var df = Object.create(null);
    var totalLen = 0;

    for (var i = 0; i < chunks.length; i++) {
      var c = chunks[i];
      var searchable = [c.title, c.aliases, c.heading, c.text].join('\n');
      var tokens = tokenize(searchable);
      var tf = Object.create(null);
      for (var t = 0; t < tokens.length; t++) {
        tf[tokens[t]] = (tf[tokens[t]] || 0) + 1;
      }
      var keys = Object.keys(tf);
      for (var k = 0; k < keys.length; k++) df[keys[k]] = (df[keys[k]] || 0) + 1;
      totalLen += tokens.length;
      docs.push({
        chunk: c,
        tf: tf,
        len: tokens.length,
        titleTokens: tokenize(c.title + ' ' + c.aliases),
        headingTokens: tokenize(c.heading),
      });
    }

    return {
      docs: docs,
      df: df,
      avgdl: docs.length ? totalLen / docs.length : 0,
      n: docs.length,
    };
  }

  function bm25(index, queryTokens, k1, b) {
    var n = index.n || 1;
    var avgdl = index.avgdl || 1;
    var scores = new Array(index.docs.length).fill(0);
    var seen = Object.create(null);

    for (var q = 0; q < queryTokens.length; q++) {
      var term = queryTokens[q];
      if (seen[term]) continue;
      seen[term] = 1;
      var df = index.df[term] || 0;
      if (!df) continue;
      var idf = Math.log(1 + (n - df + 0.5) / (df + 0.5));
      for (var d = 0; d < index.docs.length; d++) {
        var doc = index.docs[d];
        var tf = doc.tf[term];
        if (!tf) continue;
        scores[d] += idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + (b * doc.len) / avgdl)));
      }
    }

    // 标题 / 小标题命中加权，让「EL 怎么用」优先落到对应工具
    for (var d2 = 0; d2 < index.docs.length; d2++) {
      var doc2 = index.docs[d2];
      for (var q2 = 0; q2 < queryTokens.length; q2++) {
        var term2 = queryTokens[q2];
        if (doc2.headingTokens.indexOf(term2) !== -1) scores[d2] += 1.1;
        if (doc2.titleTokens.indexOf(term2) !== -1) scores[d2] += 0.9;
      }
    }
    return scores;
  }

  function search(index, query, limit) {
    limit = limit || 4;
    var qTokens = tokenize(query);
    if (!qTokens.length) return [];
    var scores = bm25(index, qTokens, 1.5, 0.75);
    var ranked = [];
    for (var i = 0; i < scores.length; i++) {
      if (scores[i] > 0) ranked.push({ chunk: index.docs[i].chunk, score: scores[i] });
    }
    ranked.sort(function (a, b) { return b.score - a.score; });
    return ranked.slice(0, limit);
  }

  function trimAtSentence(text, maxLen) {
    if (text.length <= maxLen) return text;
    var cut = text.slice(0, maxLen);
    var idx = Math.max(cut.lastIndexOf('。'), cut.lastIndexOf('！'), cut.lastIndexOf('？'), cut.lastIndexOf('\n'));
    if (idx > maxLen * 0.55) return cut.slice(0, idx + 1);
    return cut + '…';
  }

  /** 没有接入大模型时的兜底回答：直接给最相关的资料摘录。 */
  function localAnswer(results, query) {
    if (!results || !results.length) {
      return {
        text: '我在站内资料里没有找到和这个问题直接相关的内容。可以换个说法再问，或者到 GitHub 联系 AChengLinus。',
        sources: [],
      };
    }
    var top = results[0].chunk;
    var text = top.text.replace(/^#+\s*/gm, '').trim();
    text = trimAtSentence(text, 420);
    var out = '根据站内资料：\n\n' + text;
    if (results.length > 1 && results[1].score > results[0].score * 0.55) {
      var second = trimAtSentence(results[1].chunk.text.replace(/^#+\s*/gm, '').trim(), 220);
      out += '\n\n补充：' + second;
    }
    out += '\n\n（当前未接入大模型，以上为资料检索结果。）';
    return { text: out, sources: results.map(function (r) { return r.chunk; }) };
  }

  return {
    tokenize: tokenize,
    buildIndex: buildIndex,
    search: search,
    localAnswer: localAnswer,
  };
});
