#!/usr/bin/env node
/**
 * 检索回归测试：node rag/test-retriever.mjs
 * 用例格式：[问题, 期望的文档 id, 期望命中的小节标题片段（可选）]
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const retriever = require(path.join(HERE, 'retriever.js'));
const kb = JSON.parse(fs.readFileSync(path.join(HERE, 'kb.json'), 'utf8'));
const index = retriever.buildIndex(kb);

const cases = [
  ['EL 裁剪结果全黑怎么办', 'el', '裁剪结果是全黑的'],
  ['PR 工具怎么导入数据', 'pr'],
  ['图片标记支持多大的 TIFF 文件', 'pt'],
  ['仿真偏差里的五区间是什么意思', 'dat'],
  ['PRstc 怎么算的', 'pr'],
  ['工具打不开一直转圈', 'platform', '页面打不开'],
  ['无人机模式能裁出几块面板', 'el', '参数与设置'],
  ['导出整图是灰色的，提示导出窗口', 'pt', '导出整图'],
  ['GB/T 32892 的阈值是多少', 'dat', '偏差指标与阈值'],
  ['这个网站是干什么的', 'platform', '项目工具盒是什么'],
];

let failed = 0;
for (const [query, expectDoc, expectHeading] of cases) {
  const results = retriever.search(index, query, 3);
  const top = results[0];
  const docIds = results.map((r) => r.chunk.docId).join(',');
  const docOk = top && top.chunk.docId === expectDoc;
  const headingOk = !expectHeading || (top && top.chunk.heading.includes(expectHeading));
  const ok = docOk && headingOk;
  if (!ok) failed++;
  console.log(
    `${ok ? 'PASS' : 'FAIL'}  ${query.padEnd(22)} -> ${top ? `${top.chunk.docId}/${top.chunk.heading} (${top.score.toFixed(2)})` : 'no hit'}  [${docIds}]`
  );
}

// 无命中时兜底回答不能抛错
const empty = retriever.localAnswer([], '???');
if (!empty.text) {
  failed++;
  console.log('FAIL  localAnswer empty');
}

if (failed) {
  console.error(`\n${failed} 个用例失败`);
  process.exit(1);
}
console.log('\n全部通过');
