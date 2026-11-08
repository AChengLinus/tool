#!/usr/bin/env node
/**
 * 把 rag/knowledge/*.md 切成检索分块，生成 rag/kb.json。
 * 用法：node rag/build-kb.mjs
 * 无第三方依赖。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const KNOWLEDGE_DIR = path.join(HERE, 'knowledge');
const OUT_FILE = path.join(HERE, 'kb.json');
const DOC_ORDER = ['platform', 'el', 'pr', 'pt', 'report', 'dat'];

const MAX_CHUNK = 1100;
const MIN_CHUNK = 60;

function parseFrontMatter(raw) {
  const meta = {};
  let body = raw.replace(/^\uFEFF/, '');
  if (body.startsWith('---')) {
    const end = body.indexOf('\n---', 3);
    if (end !== -1) {
      const block = body.slice(3, end).trim();
      body = body.slice(body.indexOf('\n', end + 1) + 1);
      for (const line of block.split(/\r?\n/)) {
        const m = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
        if (m) meta[m[1]] = m[2].trim();
      }
    }
  }
  return { meta, body: body.trim() };
}

function splitSections(body) {
  const lines = body.split(/\r?\n/);
  const sections = [];
  let h2 = '简介';
  let h3 = null;
  let current = { heading: h2, lines: [] };

  function flush() {
    if (current.lines.join('\n').trim()) sections.push(current);
  }

  for (const line of lines) {
    if (/^##\s+\S/.test(line)) {
      flush();
      h2 = line.replace(/^##\s+/, '').trim();
      h3 = null;
      current = { heading: h2, lines: [] };
    } else if (/^###\s+\S/.test(line)) {
      flush();
      h3 = line.replace(/^###\s+/, '').trim();
      current = { heading: h2 + ' / ' + h3, lines: [] };
    } else {
      current.lines.push(line);
    }
  }
  flush();
  return sections;
}

function splitLong(text, limit) {
  const paras = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  const out = [];
  let buf = '';
  for (const p of paras) {
    if (!buf) {
      buf = p;
    } else if ((buf + '\n\n' + p).length <= limit) {
      buf += '\n\n' + p;
    } else {
      out.push(buf);
      buf = p;
    }
  }
  if (buf) out.push(buf);
  // 单个段落仍超长时按句子切
  const final = [];
  for (const piece of out) {
    if (piece.length <= limit * 1.6) {
      final.push(piece);
      continue;
    }
    let buf2 = '';
    for (const sentence of piece.split(/(?<=[。！？!?；;])/)) {
      if (buf2.length + sentence.length > limit && buf2) {
        final.push(buf2);
        buf2 = sentence;
      } else {
        buf2 += sentence;
      }
    }
    if (buf2.trim()) final.push(buf2.trim());
  }
  return final;
}

function main() {
  if (!fs.existsSync(KNOWLEDGE_DIR)) {
    console.error(`[build-kb] 目录不存在: ${KNOWLEDGE_DIR}`);
    process.exit(1);
  }
  const files = fs.readdirSync(KNOWLEDGE_DIR).filter((f) => f.endsWith('.md'));
  const ordered = DOC_ORDER.map((id) => `${id}.md`).filter((f) => files.includes(f));
  const extra = files.filter((f) => !ordered.includes(f)).sort();
  const allFiles = ordered.concat(extra);

  const docs = [];
  const chunks = [];

  for (const file of allFiles) {
    const docId = path.basename(file, '.md');
    const raw = fs.readFileSync(path.join(KNOWLEDGE_DIR, file), 'utf8');
    const { meta, body } = parseFrontMatter(raw);
    const title = meta.title || docId;
    const aliases = meta.aliases || '';
    const url = meta.url || '';

    docs.push({ id: docId, title, aliases, url });

    for (const section of splitSections(body)) {
      const text = section.lines.join('\n').trim();
      if (!text) continue;
      const pieces = splitLong(text, MAX_CHUNK);
      pieces.forEach((piece, i) => {
        if (piece.trim().length < MIN_CHUNK && pieces.length > 1) return;
        chunks.push({
          id: `${docId}-${String(chunks.length + 1).padStart(2, '0')}`,
          docId,
          title,
          heading: section.heading,
          text: piece.trim(),
          url,
          aliases,
        });
      });
    }
  }

  const payload = {
    version: 1,
    builtAt: new Date().toISOString(),
    docs,
    chunks,
  };

  fs.writeFileSync(OUT_FILE, JSON.stringify(payload, null, 0), 'utf8');

  const size = fs.statSync(OUT_FILE).size;
  const perDoc = docs.map((d) => `${d.id}:${chunks.filter((c) => c.docId === d.id).length}`).join(' ');
  console.log(`[build-kb] 写入 ${path.relative(process.cwd(), OUT_FILE)} (${(size / 1024).toFixed(1)} KB)`);
  console.log(`[build-kb] ${chunks.length} 块 / ${docs.length} 篇  (${perDoc})`);
  const tooLong = chunks.filter((c) => c.text.length > MAX_CHUNK * 1.5);
  if (tooLong.length) console.warn(`[build-kb] 警告: ${tooLong.length} 块超过 ${MAX_CHUNK} 字符`);
}

main();
