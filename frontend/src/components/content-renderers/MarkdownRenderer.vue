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

  // Handle $$ display math $$
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, math) => {
    if (katex) {
      try {
        return katex.renderToString(math, { displayMode: true, throwOnError: false });
      } catch {
        // fallback
      }
    }
    return `<div class="math-display-fallback">$$ ${math.trim()} $$</div>`;
  });

  // Handle $ inline math $
  text = text.replace(/\$([^\$\n]+?)\$/g, (_, math) => {
    if (katex) {
      try {
        return katex.renderToString(math, { displayMode: false, throwOnError: false });
      } catch {
        // fallback
      }
    }
    return `<code class="math-inline-fallback">${math.trim()}</code>`;
  });

  return md.render(text);
});
</script>

<template>
  <div class="markdown-rendered-body" v-html="renderedHtml"></div>
</template>

<style>
.markdown-rendered-body {
  font-size: 14px;
  line-height: 1.65;
  color: var(--text-primary, #0f172a);
}

.markdown-rendered-body h1,
.markdown-rendered-body h2,
.markdown-rendered-body h3,
.markdown-rendered-body h4 {
  font-weight: 800;
  letter-spacing: -0.01em;
  color: #0f172a;
  margin-top: 1.2em;
  margin-bottom: 0.5em;
}

.markdown-rendered-body h1 { font-size: 20px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }
.markdown-rendered-body h2 { font-size: 17px; }
.markdown-rendered-body h3 { font-size: 15px; }

.markdown-rendered-body p {
  margin-bottom: 0.6em;
}

.markdown-rendered-body p:last-child {
  margin-bottom: 0;
}

.markdown-rendered-body strong {
  font-weight: 800;
  color: #0f172a;
}

.markdown-rendered-body ul,
.markdown-rendered-body ol {
  padding-left: 20px;
  margin-top: 0.4em;
  margin-bottom: 0.6em;
}

.markdown-rendered-body li {
  margin-bottom: 4px;
}

.markdown-rendered-body blockquote {
  border-left: 3.5px solid #4f46e5;
  background: #f5f3ff;
  padding: 10px 14px;
  margin: 0.8em 0;
  border-radius: 0 10px 10px 0;
  color: #4338ca;
}

.markdown-rendered-body code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 1px 5px;
  border-radius: 4px;
  color: #4f46e5;
}

.markdown-rendered-body .math-inline-fallback {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #ecfdf5 !important;
  color: #047857 !important;
  border: 1px solid #a7f3d0 !important;
  padding: 1px 6px !important;
  border-radius: 6px !important;
  font-weight: 700 !important;
}

.markdown-rendered-body .math-display-fallback {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #ecfdf5 !important;
  color: #047857 !important;
  border: 1px solid #a7f3d0 !important;
  padding: 8px 12px !important;
  border-radius: 8px !important;
  font-weight: 700 !important;
  margin: 8px 0;
  text-align: center;
}

.markdown-rendered-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.8em 0;
}

.markdown-rendered-body th,
.markdown-rendered-body td {
  border: 1px solid #e2e8f0;
  padding: 8px 12px;
  text-align: left;
}

.markdown-rendered-body th {
  background: #f8fafc;
  font-weight: 700;
}
</style>
