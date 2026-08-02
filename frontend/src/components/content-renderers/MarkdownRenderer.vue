<script setup lang="ts">
import { computed } from 'vue';
import MarkdownIt from 'markdown-it';

const props = defineProps<{
  content: string;
  isStreaming?: boolean;
}>();

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true
});

const renderedHtml = computed(() => {
  if (!props.content) return '';
  let text = props.content;

  const katex = (window as any).katex;

  if (katex) {
    text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, math) => {
      try {
        return katex.renderToString(math, { displayMode: true, throwOnError: false });
      } catch {
        return `<pre class="math-block">${math}</pre>`;
      }
    });

    text = text.replace(/\$([^\$\n]+?)\$/g, (_, math) => {
      try {
        return katex.renderToString(math, { displayMode: false, throwOnError: false });
      } catch {
        return `<code>${math}</code>`;
      }
    });
  }

  return md.render(text);
});
</script>

<template>
  <div class="markdown-rendered-body" v-html="renderedHtml"></div>
</template>

<style>
.markdown-rendered-body {
  font-size: 15px;
  line-height: 1.8;
  color: var(--text-primary);
}

.markdown-rendered-body h1,
.markdown-rendered-body h2,
.markdown-rendered-body h3,
.markdown-rendered-body h4 {
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  margin-top: 1.6em;
  margin-bottom: 0.6em;
}

.markdown-rendered-body h1 { font-size: 24px; border-bottom: 1px solid var(--border-default); padding-bottom: 8px; }
.markdown-rendered-body h2 { font-size: 20px; }
.markdown-rendered-body h3 { font-size: 17px; }

.markdown-rendered-body p {
  margin-bottom: 1.2em;
}

.markdown-rendered-body ul,
.markdown-rendered-body ol {
  padding-left: 24px;
  margin-bottom: 1.2em;
}

.markdown-rendered-body li {
  margin-bottom: 6px;
}

.markdown-rendered-body blockquote {
  border-left: 4px solid var(--color-primary);
  background: var(--color-primary-soft);
  padding: 12px 18px;
  margin: 1.2em 0;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  color: var(--text-secondary);
}

.markdown-rendered-body code {
  font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 13px;
  background: var(--bg-subtle);
  padding: 2px 6px;
  border-radius: var(--radius-xs);
  color: var(--color-primary);
}

.markdown-rendered-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.2em 0;
}

.markdown-rendered-body th,
.markdown-rendered-body td {
  border: 1px solid var(--border-default);
  padding: 10px 14px;
  text-align: left;
}

.markdown-rendered-body th {
  background: var(--bg-subtle);
  font-weight: 700;
}
</style>
