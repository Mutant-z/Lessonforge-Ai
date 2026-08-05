<script setup lang="ts">
import { computed } from 'vue';
import MarkdownIt from 'markdown-it';
import {
  extractMath,
  normalizeAgentMarkdown,
  restoreMathPlaceholders,
} from '../../services/markdownText';

const props = defineProps<{
  content: string;
  isStreaming?: boolean;
}>();

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true
});

/**
 * 安全渲染管道：
 * 1. 提取 `$...$` / `$$...$$` 公式为占位符（代码围栏内的内容不受影响）；
 * 2. 归一化正文：统一换行、压缩空行、剥离残余 HTML 标签、LaTeX → 可读文本；
 * 3. markdown-it 渲染（html:false，原始 HTML 一律转义，不会注入执行）；
 * 4. 还原公式：优先 katex，失败时回退为可读普通文本，绝不把 LaTeX 或标签源码展示给用户。
 */
const renderedHtml = computed(() => {
  if (!props.content) return '';

  const extracted = extractMath(props.content);
  const normalized = normalizeAgentMarkdown(extracted.text);
  const html = md.render(normalized);
  return restoreMathPlaceholders(html, extracted.inline, extracted.display);
});
</script>

<template>
  <div class="markdown-rendered-body" v-html="renderedHtml"></div>
</template>

<style>
/* 统一的 Agent 输出排版规则：标题、列表、正文、公式、代码共享同一套视觉层级。 */
.markdown-rendered-body {
  font-size: 14px;
  line-height: 1.65;
  color: var(--text-primary, #0f172a);
  /* 覆盖父级可能残留的 pre-wrap，避免把 markdown-it 生成的换行渲染成大段空白 */
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
  max-width: 100%;
  min-width: 0;
}

.markdown-rendered-body > :first-child {
  margin-top: 0;
}

.markdown-rendered-body > :last-child {
  margin-bottom: 0;
}

/* 标题层级：紧凑且与正文拉开主次 */
.markdown-rendered-body h1,
.markdown-rendered-body h2,
.markdown-rendered-body h3,
.markdown-rendered-body h4 {
  font-weight: 800;
  letter-spacing: -0.01em;
  color: #0f172a;
  margin: 0.75em 0 0.35em;
  line-height: 1.35;
}

.markdown-rendered-body h1 {
  font-size: 19px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 5px;
}

.markdown-rendered-body h2 { font-size: 16px; }
.markdown-rendered-body h3 { font-size: 14.5px; }
.markdown-rendered-body h4 { font-size: 14px; }

/* 正文：紧凑段落间距，避免内容被大段空白拉长 */
.markdown-rendered-body p {
  margin: 0 0 0.45em;
}

.markdown-rendered-body p:last-child {
  margin-bottom: 0;
}

.markdown-rendered-body strong {
  font-weight: 800;
  color: #0f172a;
}

/* 列表：紧凑排列，不产生大面积留白 */
.markdown-rendered-body ul,
.markdown-rendered-body ol {
  padding-left: 1.35em;
  margin: 0.15em 0 0.45em;
}

.markdown-rendered-body li {
  margin: 0;
}

.markdown-rendered-body li + li {
  margin-top: 2px;
}

.markdown-rendered-body li > p {
  margin: 0;
}

.markdown-rendered-body li > ul,
.markdown-rendered-body li > ol {
  margin: 2px 0;
}

.markdown-rendered-body blockquote {
  border-left: 3.5px solid #4f46e5;
  background: #f5f3ff;
  padding: 8px 14px;
  margin: 0.6em 0;
  border-radius: 0 10px 10px 0;
  color: #4338ca;
}

.markdown-rendered-body blockquote p {
  margin: 0.2em 0;
}

/* 行内代码与代码块 */
.markdown-rendered-body code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 1px 5px;
  border-radius: 4px;
  color: #4f46e5;
  overflow-wrap: break-word;
}

.markdown-rendered-body pre {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  margin: 0.6em 0;
  overflow-x: auto;
  overflow-y: hidden;
  line-height: 1.55;
}

.markdown-rendered-body pre code {
  background: transparent;
  border: 0;
  padding: 0;
  color: #334155;
  font-size: 12.5px;
  overflow-wrap: normal;
  word-break: normal;
}

.markdown-rendered-body pre code .hljs {
  background: transparent;
}

/* 公式：katex 渲染为主；兜底为可读普通文本 */
.markdown-rendered-body .math-inline-fallback {
  font-style: italic;
  background: #eef2ff;
  color: #3730a3;
  border: 1px solid #c7d2fe;
  padding: 0 4px;
  border-radius: 4px;
  white-space: normal;
}

.markdown-rendered-body .math-display-fallback {
  font-style: italic;
  text-align: center;
  background: #f5f3ff;
  color: #3730a3;
  border: 1px solid #e0e7ff;
  padding: 8px 12px;
  margin: 0.5em 0;
  border-radius: 8px;
  overflow-x: auto;
}

/* katex 细节微调：避免过大的公式上下留白，长公式允许横向滚动 */
.markdown-rendered-body .katex-display {
  margin: 0.4em 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 2px 0;
}

.markdown-rendered-body .katex {
  font-size: 1.04em;
}

.markdown-rendered-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.6em 0;
}

.markdown-rendered-body th,
.markdown-rendered-body td {
  border: 1px solid #e2e8f0;
  padding: 6px 10px;
  text-align: left;
}

.markdown-rendered-body th {
  background: #f8fafc;
  font-weight: 700;
}

.markdown-rendered-body hr {
  border: 0;
  border-top: 1px solid #e2e8f0;
  margin: 0.8em 0;
}

.markdown-rendered-body a {
  color: #4f46e5;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.markdown-rendered-body img {
  max-width: 100%;
  height: auto;
  border-radius: 8px;
}
</style>
