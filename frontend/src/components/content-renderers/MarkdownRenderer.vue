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
function renderExerciseMarkdown(content: string): string {
  if (!content.includes('ex_')) {
    const extracted = extractMath(content);
    const normalized = normalizeAgentMarkdown(extracted.text);
    const html = md.render(normalized);
    return restoreMathPlaceholders(html, extracted.inline, extracted.display);
  }

  // 按 ex_XX 题号进行大块切割
  const parts = content.split(/(?=ex_\d+[\s·.:])/g);

  const renderedParts = parts.map(part => {
    const trimmed = part.trim();
    if (!trimmed.startsWith('ex_')) {
      const extracted = extractMath(trimmed);
      const normalized = normalizeAgentMarkdown(extracted.text);
      const html = md.render(normalized);
      return restoreMathPlaceholders(html, extracted.inline, extracted.display);
    }

    // 提取题号 (ex_01 -> 01)
    const qNumMatch = trimmed.match(/^ex_(\d+)[\s·.:]*/);
    const qNum = qNumMatch ? qNumMatch[1] : '01';

    let body = trimmed.replace(/^ex_\d+[\s·.:]*/, '');

    // 提取答案
    let answerText = '';
    const answerMatch = body.match(/(?:\*\*|\b)答案[：:]\s*(?:\*\*)?\s*([^\n]+)/);
    if (answerMatch) {
      answerText = (answerMatch[1] || '').trim();
      body = body.replace(/(?:\*\*|\b)答案[：:]\s*(?:\*\*)?\s*[^\n]+/, '');
    }

    // 提取解析
    let analysisText = '';
    const analysisMatch = body.match(/(?:\*\*|\b)解析[：:]\s*(?:\*\*)?\s*([\s\S]+?)(?=$|\n\s*ex_\d+)/);
    if (analysisMatch) {
      analysisText = (analysisMatch[1] || '').trim();
      body = body.replace(/(?:\*\*|\b)解析[：:]\s*(?:\*\*)?\s*[\s\S]+?(?=$|\n\s*ex_\d+)/, '');
    }

    // 提取选项 (A. xx, B. xx, C. xx, D. xx)
    const options: Array<{ letter: string; text: string }> = [];
    const optRegex = /(?:^|\n)\s*([A-D])[\.\:]\s*([^\n]+)/g;
    let optMatch: RegExpExecArray | null;
    while ((optMatch = optRegex.exec(body)) !== null) {
      options.push({ letter: optMatch[1], text: optMatch[2].trim() });
    }

    // 剥离选项后的题干
    let stemText = body.replace(/(?:^|\n)\s*([A-D])[\.\:]\s*[^\n]+/g, '').trim();

    // 渲染数学公式与 Markdown
    const renderPiece = (str: string) => {
      if (!str) return '';
      const ext = extractMath(str);
      const norm = normalizeAgentMarkdown(ext.text);
      const h = md.render(norm);
      return restoreMathPlaceholders(h, ext.inline, ext.display);
    };

    const renderedStem = renderPiece(stemText);
    const renderedAnswer = renderPiece(answerText);
    const renderedAnalysis = renderPiece(analysisText);

    const typeLabel = options.length > 0 ? '单选题' : '综合问答题';

    let cardHtml = `<div class="md-question-card-block">`;
    cardHtml += `<div class="card-head-row"><span class="q-badge">${qNum}</span><span class="q-type">${typeLabel}</span></div>`;
    cardHtml += `<div class="q-stem-body">${renderedStem}</div>`;

    if (options.length > 0) {
      cardHtml += `<div class="q-options-grid">`;
      for (const opt of options) {
        cardHtml += `<div class="opt-pill"><span class="opt-letter">${opt.letter}</span><span class="opt-text">${opt.text}</span></div>`;
      }
      cardHtml += `</div>`;
    }

    const cleanAnswer = renderedAnswer.replace(/^<p>|<\/p>\s*$/gi, '').trim();
    const cleanAnalysis = renderedAnalysis.replace(/^<p>|<\/p>\s*$/gi, '').trim();

    if (cleanAnswer) {
      cardHtml += `<div class="q-callout answer-callout"><span class="callout-tag green">✓ 参考答案</span><span class="callout-val-text">${cleanAnswer}</span></div>`;
    }

    if (cleanAnalysis) {
      cardHtml += `<div class="q-callout analysis-callout"><div class="callout-header"><span class="callout-tag violet">💡 详细解析</span></div><div class="callout-body-text">${cleanAnalysis}</div></div>`;
    }

    cardHtml += `</div>`;
    return cardHtml;
  });

  return renderedParts.join('\n');
}

function formatDocumentHtml(html: string): string {
  let result = html;

  // 0. 教学设计顶部 Masthead 看板转译 (`<h1>教学设计 V2.0</h1>` 与 `课程：... 学科/年级：... 时长：...`)
  result = result.replace(
    /<h1\b[^>]*>\s*(?:教学设计|课程教学设计)(?:\s*V[\d\.]+)?\s*<\/h1>(?:\s*<p>\s*课程[：:]\s*([^\n<]+?)\s*·\s*学科\/年级[：:]\s*([^\n<]*?)\s*·\s*时长[：:]\s*([^\n<]+?)\s*<\/p>)?/gi,
    (_, courseTitle, subjectGrade, duration) => {
      const cleanCourse = (courseTitle || '').trim() || '课堂教学设计方案';
      let cleanGrade = (subjectGrade || '').trim().replace(/^\/+|\/+$/g, '').trim();
      if (!cleanGrade || cleanGrade === '/') cleanGrade = '物理 · 初中八年级';
      const cleanDuration = (duration || '').trim() || '10.0 分钟';

      return `
        <div class="lp-masthead-card">
          <div class="lp-masthead-badge-row">
            <span class="lp-masthead-kicker"><span class="lp-pulse-dot"></span>STAGE 01 · 核心教学设计与方案蓝图</span>
            <span class="lp-masthead-status-chip">✓ 核心素养对齐</span>
          </div>
          <h1 class="lp-masthead-main-title">${cleanCourse} · 教学设计</h1>
          <div class="lp-meta-row">
            <span class="lp-meta-tag grade">${cleanGrade}</span>
            <span class="lp-meta-tag duration">⏱️ 微课时长: ${cleanDuration}</span>
            <span class="lp-meta-tag version">版本 V2.0</span>
          </div>
          <div class="lp-metric-grid">
            <div class="lp-metric-card">
              <span class="metric-icon">⏱️</span>
              <div class="metric-info">
                <span class="metric-label">建议时长</span>
                <span class="metric-val highlight">${cleanDuration}</span>
              </div>
            </div>
            <div class="lp-metric-card">
              <span class="metric-icon">🎯</span>
              <div class="metric-info">
                <span class="metric-label">教学目标</span>
                <span class="metric-val">3 维素养目标</span>
              </div>
            </div>
            <div class="lp-metric-card">
              <span class="metric-icon">💡</span>
              <div class="metric-info">
                <span class="metric-label">认知突破</span>
                <span class="metric-val">破解深度迷思</span>
              </div>
            </div>
            <div class="lp-metric-card">
              <span class="metric-icon">🚀</span>
              <div class="metric-info">
                <span class="metric-label">模式机制</span>
                <span class="metric-val success">翻转微课 / 逻辑拆解</span>
              </div>
            </div>
          </div>
        </div>
      `;
    }
  );

  // 1. 教学设计 / 学情分析 Tag 替换：【已有知识基底】、【认知与思维特点】、【迷思概念与直觉误区】及 `● 已有知识基底`
  result = result.replace(
    /(?:【|●\s*)已有知识基底(?:】)?/g,
    '<span class="md-tag-chip blue"><span class="chip-dot"></span>已有知识基底</span>'
  );
  result = result.replace(
    /(?:【|●\s*)认知与思维特点(?:】)?/g,
    '<span class="md-tag-chip violet"><span class="chip-dot"></span>认知与思维特点</span>'
  );
  result = result.replace(
    /(?:【|●\s*)迷思概念与直觉误区(?:】)?/g,
    '<span class="md-tag-chip amber"><span class="chip-dot"></span>迷思概念与直觉误区</span>'
  );
  result = result.replace(
    /【([^】]+)】/g,
    '<span class="md-tag-chip indigo"><span class="chip-dot"></span>$1</span>'
  );

  // 1.1 教学目标子标题徽标化：`一、知识与技能`、`二、过程与方法`、`三、情感态度与价值观`
  result = result.replace(
    /(一、\s*知识与技能[^\n<：:]*?)(?:[：:])?/g,
    '<div class="lp-obj-pillar-badge knowledge"><span class="pillar-icon">📘</span>$1</div>'
  );
  result = result.replace(
    /(二、\s*过程与方法[^\n<：:]*?)(?:[：:])?/g,
    '<div class="lp-obj-pillar-badge process"><span class="pillar-icon">🔬</span>$1</div>'
  );
  result = result.replace(
    /(三、\s*(?:情感态度与价值观|核心素养与探究)[^\n<：:]*?)(?:[：:])?/g,
    '<div class="lp-obj-pillar-badge attitude"><span class="pillar-icon">✨</span>$1</div>'
  );

  // 1.2 公式高亮 (p=ρgh, F浮 = F下 - F上, F浮 = G排, F=pS, Δh, G桶, G总 等)
  result = result.replace(
    /\b(F\s*浮\s*=\s*F\s*下\s*[-－]\s*F\s*上|F\s*浮\s*=\s*G\s*排|F\s*浮\s*=\s*G\s*[-－]\s*F\s*拉|G\s*排\s*=\s*G\s*总\s*[-－]\s*G\s*桶|p\s*=\s*ρgh|F\s*=\s*pS|F\s*浮|F\s*上|F\s*下|G\s*排|G\s*桶|G\s*总|F\s*拉|Δh)\b/g,
    '<code class="math-badge">$1</code>'
  );

  // 2. 教学设计主要 Section 标题增强 (内容分析、学情分析、教学目标、教学重点、教学难点)
  const lessonIcons: Record<string, string> = {
    '内容分析': '📖',
    '学情分析': '👥',
    '教学目标': '🎯',
    '教学重点': '💡',
    '教学难点': '🔥',
    '教学过程': '⏱️',
    '教学反思': '✨'
  };
  result = result.replace(
    /<h2>\s*(内容分析|学情分析|教学目标|教学重点|教学难点|教学过程|教学反思)\s*<\/h2>/gi,
    (_, title) => `<h2 class="lesson-section-header"><span class="section-icon">${lessonIcons[title] || '📌'}</span><span class="section-title">${title}</span></h2>`
  );

  // 3. 视频脚本时间轴标题：`## 00:00-02:00 · 趣味引入：潜水艇的困惑`
  result = result.replace(
    /<h2>\s*(\d{2}:\d{2}-\d{2}:\d{2})\s*[·.:]?\s*(.*?)\s*<\/h2>/gi,
    '<div class="script-timestamp-card"><div class="time-pill">⏱️ $1</div><h3 class="script-title">$2</h3></div>'
  );

  // 4. 视频脚本分镜列表项 (画面 / 旁白 / 动作)
  result = result.replace(
    /<li>\s*(?:<strong>)?\s*画面[：:]\s*(?:<\/strong>)?\s*([\s\S]+?)<\/li>/gi,
    '<li class="script-row scene-row"><div class="script-badge-col"><span class="script-badge scene-badge">🎥 画面</span></div><div class="script-body-col">$1</div></li>'
  );
  result = result.replace(
    /<li>\s*(?:<strong>)?\s*旁白[：:]\s*(?:<\/strong>)?\s*([\s\S]+?)<\/li>/gi,
    '<li class="script-row narration-row"><div class="script-badge-col"><span class="script-badge narration-badge">🎙️ 旁白</span></div><div class="script-body-col">$1</div></li>'
  );
  result = result.replace(
    /<li>\s*(?:<strong>)?\s*动作[：:]\s*(?:<\/strong>)?\s*([\s\S]+?)<\/li>/gi,
    '<li class="script-row action-row"><div class="script-badge-col"><span class="script-badge action-badge">🎬 动作</span></div><div class="script-body-col">$1</div></li>'
  );

  // 5. 教师逐字稿 Header/Masthead 增强 (`<h1>教师逐字稿</h1>` 与 `建议语速`)
  result = result.replace(
    /<h[12]>\s*教师逐字稿\s*<\/h[12]>(?:\s*<p>\s*(?:<strong>)?\s*建议语速[：:]\s*(?:<\/strong>)?\s*([\s\S]*?)\s*<\/p>)?/gi,
    (_, speed) => {
      const speedVal = (speed || '').trim() || 'standard (120-140字/分)';
      return `
        <div class="verbatim-masthead-card">
          <div class="masthead-badge-row">
            <span class="masthead-kicker"><span class="pulse-dot"></span>教师口播逐字稿 · 提词台本</span>
            <span class="masthead-status-chip">微课 / 现场讲授</span>
          </div>
          <h1 class="masthead-main-title">教师逐字稿</h1>
          <div class="masthead-meta-grid">
            <div class="meta-pill-item speed">
              <span class="meta-icon">⚡</span>
              <span class="meta-label">建议语速:</span>
              <span class="meta-value">${speedVal}</span>
            </div>
            <div class="meta-pill-item highlight">
              <span class="meta-icon">🎯</span>
              <span class="meta-label">重点标注:</span>
              <span class="meta-value">分段时间轴 · 交互动作 · 拓展补充</span>
            </div>
          </div>
        </div>
      `;
    }
  );

  // 独立的 `建议语速： standard` 替换 (避免未跟随 h1 时遗漏)
  result = result.replace(
    /<p>\s*(?:<strong>)?\s*建议语速[：:]\s*(?:<\/strong>)?\s*([\s\S]*?)\s*<\/p>/gi,
    (_, speed) => `<div class="verbatim-speed-chip"><span class="chip-icon">⚡</span><span class="chip-label">建议语速：</span><span class="chip-value">${(speed || '').trim()}</span></div>`
  );

  // 6. 教师逐字稿段落标题：`## seg_01 · 00:00-02:00 · slide_01,slide_02...`
  result = result.replace(
    /<h2>\s*(seg_\d+)\s*·\s*(\d{2}:\d{2}-\d{2}:\d{2})\s*·\s*([^\n<]+)\s*<\/h2>/gi,
    (_, segId, timeStr, slidesStr) => {
      const slides = slidesStr.split(',').map((s: string) => {
        const slideName = s.trim();
        return `<span class="slide-tag" title="对应 PPT 页面: ${slideName}"><span class="slide-icon">📑</span>${slideName}</span>`;
      }).join('');
      return `
        <div class="verbatim-seg-card">
          <div class="seg-head-left">
            <span class="seg-chip"><span class="seg-icon">🚀</span>${segId}</span>
            <span class="time-chip"><span class="time-icon">⏱️</span>${timeStr}</span>
          </div>
          <div class="seg-head-right">
            <span class="slides-label">关联胶片：</span>
            <div class="slides-group">${slides}</div>
          </div>
        </div>
      `;
    }
  );

  // 7. 教师逐字稿 Callout：`可选补充:` 与 `互动:` / `互动提示:`
  result = result.replace(
    /(?:<blockquote\s*>\s*)?(?:<p>|<br\s*\/?>|^)\s*(?:<strong>)?\s*(?:可选补充|补充说明)[：:]\s*(?:<\/strong>)?\s*([\s\S]*?)(?:<\/p>|(?=<br\s*\/?>|$))(?:<\/blockquote>)?/gi,
    (_, bodyText) => {
      const cleanBody = (bodyText || '').trim();
      if (!cleanBody) return '';
      return `
        <div class="verbatim-callout supplement-callout">
          <div class="callout-header">
            <span class="callout-badge purple"><span class="badge-icon">💡</span> 可选补充</span>
            <span class="callout-hint">拓展讲解提示</span>
          </div>
          <div class="callout-body">${cleanBody}</div>
        </div>
      `;
    }
  );

  result = result.replace(
    /(?:<blockquote\s*>\s*)?(?:<p>|<br\s*\/?>|^)\s*(?:<strong>)?\s*(?:互动提示|互动)[：:]\s*(?:<\/strong>)?\s*([\s\S]*?)(?:<\/p>|(?=<br\s*\/?>|$))(?:<\/blockquote>)?/gi,
    (_, bodyText) => {
      let text = (bodyText || '').trim();
      if (!text) return '';
      // 增强渲染：动态突出动作、停顿与镜头
      text = text.replace(/(停顿\s*\d+(?:\.\d+)?\s*秒)/g, '<mark class="action-tag pause"><span class="tag-icon">⏱️</span>$1</mark>');
      text = text.replace(/((?:[^\s,，。；;]*?画中画|镜头打招呼))/g, '<span class="action-tag camera"><span class="tag-icon">📹</span>$1</span>');
      text = text.replace(/(手势[^\s,，。；;]*?|比出[^\s,，。；;]*?手势|做出[^\s,，。；;]*?状)/g, '<span class="action-tag gesture"><span class="tag-icon">👉</span>$1</span>');
      
      return `
        <div class="verbatim-callout interaction-callout">
          <div class="callout-header">
            <span class="callout-badge blue"><span class="badge-icon">🎭</span> 互动提示与台风指南</span>
            <span class="callout-hint">肢体 / 镜头 / 停顿节奏</span>
          </div>
          <div class="callout-body">${text}</div>
        </div>
      `;
    }
  );

  // 清理因替换产生的空标签
  result = result.replace(/<blockquote\s*>\s*(?:<p>\s*<\/p>)?\s*<\/blockquote>/gi, '');

  return result;
}

/**
 * 视频生成专属结构化卡片渲染器：
 * 将微课视频生成 Markdown（包含制作模式、输出规格、总时长，以及 VG-01 各分镜头、画面提示词、旁白等）
 * 转换为高颜值的专业分镜故事板（Storyboard Scene Cards）和指标仪表盘（Masthead Metrics）。
 */
function renderVideoGenerationMarkdown(content: string): string {
  // 1. 提取顶部配置信息（制作模式、规格、声音风格、画面模式、字幕、总时长、费用等）
  const titleMatch = content.match(/^#\s*(微课视频生成|Seedance\s*原生有声微课视频|[^\n]+)/m);
  const mainTitle = titleMatch ? titleMatch[1].trim() : '微课视频生成';

  const modeMatch = content.match(/[-*]\s*(?:制作模式|模型)[：:]\s*([^\n]+)/);
  const specMatch = content.match(/[-*]\s*(?:输出规格|输出)[：:]\s*([^\n]+)/);
  const voiceMatch = content.match(/[-*]\s*(?:声音风格|原生音频)[：:]\s*([^\n]+)/);
  const visualModeMatch = content.match(/[-*]\s*(?:画面模式|连续性(?:分组)?)[：:]\s*([^\n]+)/);
  const subtitleMatch = content.match(/[-*]\s*字幕[：:]\s*([^\n]+)/);
  const durationMatch = content.match(/[-*]\s*总时长[：:]\s*([^\n]+)/);
  const costMatch = content.match(/[-*]\s*(?:实际费用|预估费用|实耗)[：:]\s*([^\n]+)/);

  const mode = modeMatch ? modeMatch[1].trim() : 'hybrid';
  const spec = specMatch ? specMatch[1].trim() : '1280x720 · 16:9';
  const voice = voiceMatch ? voiceMatch[1].trim() : 'natural (自然亲和)';
  const visualMode = visualModeMatch ? visualModeMatch[1].trim() : 'hybrid_director';
  const subtitle = subtitleMatch ? subtitleMatch[1].trim() : '开启';
  const duration = durationMatch ? durationMatch[1].trim() : '600.0 秒';
  const cost = costMatch ? costMatch[1].trim() : '';

  // 格式化总时长辅助文本
  let durationExtra = '';
  const numSeconds = parseFloat(duration.replace(/[^\d.]/g, ''));
  if (!isNaN(numSeconds) && numSeconds > 0) {
    const mins = Math.floor(numSeconds / 60);
    const secs = Math.round(numSeconds % 60);
    durationExtra = mins > 0 ? ` (${mins}分${String(secs).padStart(2, '0')}秒)` : ` (${secs}秒)`;
  }

  let html = `
    <div class="vg-masthead-card">
      <div class="vg-masthead-badge-row">
        <span class="vg-masthead-kicker"><span class="vg-pulse-dot"></span>STAGE 06 · 微课视频生成工作流</span>
        <span class="vg-masthead-status-chip">✓ 规格已就绪</span>
      </div>
      <h1 class="vg-masthead-main-title">${mainTitle}</h1>
      <div class="vg-meta-grid">
        <div class="vg-meta-pill primary">
          <span class="vg-pill-icon">⚙️</span>
          <div class="vg-pill-text">
            <span class="vg-pill-label">制作模式</span>
            <span class="vg-pill-val highlight">${mode}</span>
          </div>
        </div>
        <div class="vg-meta-pill">
          <span class="vg-pill-icon">📐</span>
          <div class="vg-pill-text">
            <span class="vg-pill-label">输出规格</span>
            <span class="vg-pill-val">${spec}</span>
          </div>
        </div>
        <div class="vg-meta-pill">
          <span class="vg-pill-icon">🎙️</span>
          <div class="vg-pill-text">
            <span class="vg-pill-label">声音风格</span>
            <span class="vg-pill-val">${voice}</span>
          </div>
        </div>
        <div class="vg-meta-pill">
          <span class="vg-pill-icon">👁️</span>
          <div class="vg-pill-text">
            <span class="vg-pill-label">画面模式</span>
            <span class="vg-pill-val">${visualMode}</span>
          </div>
        </div>
        <div class="vg-meta-pill">
          <span class="vg-pill-icon">💬</span>
          <div class="vg-pill-text">
            <span class="vg-pill-label">字幕生成</span>
            <span class="vg-pill-val ${subtitle.includes('开启') || subtitle === '是' ? 'success' : ''}">${subtitle}</span>
          </div>
        </div>
        <div class="vg-meta-pill">
          <span class="vg-pill-icon">⏱️</span>
          <div class="vg-pill-text">
            <span class="vg-pill-label">总时长</span>
            <span class="vg-pill-val duration">${duration}${durationExtra}</span>
          </div>
        </div>
        ${cost ? `
        <div class="vg-meta-pill cost">
          <span class="vg-pill-icon">💰</span>
          <div class="vg-pill-text">
            <span class="vg-pill-label">实际费用</span>
            <span class="vg-pill-val amber">${cost}</span>
          </div>
        </div>` : ''}
      </div>
    </div>
  `;

  // 2. 切割各分镜头卡片 (以 `## VG-` 或 `## scene_` 或其他 `## ` 开头)
  const sceneSections = content.split(/(?=^##\s+)/m);

  html += `<div class="vg-storyboard-stream">`;

  let renderedSceneCount = 0;
  for (const rawSec of sceneSections) {
    const sec = rawSec.trim();
    if (!sec.startsWith('##')) continue;

    renderedSceneCount++;

    // 匹配标题行：如 `## VG-01 · 0.0s—30.0s` 或 `## VG-01`
    const headerLineMatch = sec.match(/^##\s+([^\n]+)/);
    const headerText = headerLineMatch ? headerLineMatch[1].trim() : `分镜 ${renderedSceneCount}`;
    
    // 拆分分镜 ID 与时间区间
    const timeMatch = headerText.match(/(\d+(?:\.\d+)?s?\s*[-—~]\s*\d+(?:\.\d+)?s?)/);
    const timeRangeStr = timeMatch ? timeMatch[1] : '';
    const sceneId = headerText.replace(/[·:：].*$/, '').trim();

    // 提取字段
    const scriptSceneMatch = sec.match(/[-*]\s*脚本分镜[：:]\s*([^\n]+)/);
    const statusMatch = sec.match(/[-*]\s*状态[：:]\s*([^\n]+)/);
    const visualSourceMatch = sec.match(/[-*]\s*画面来源[：:]\s*([^\n]+)/);
    const continuityMatch = sec.match(/[-*]\s*连续性分组[：:]\s*([^\n]+)/);
    const qaMatch = sec.match(/[-*]\s*(?:教学事实\s*QA|QA\s*状态)[：:]\s*([^\n]+)/);
    const sceneCostMatch = sec.match(/[-*]\s*片段费用[：:]\s*([^\n]+)/);

    // 提取画面提示词
    let visualPrompt = '';
    const vpMatch = sec.match(/[-*]\s*画面提示词[：:]\s*([\s\S]+?)(?=(?:^[-*]\s*(?:脚本分镜|状态|画面来源|连续性分组|教学事实|片段费用|旁白|计划口播|实际口播|字幕)[：:])|$)/m);
    if (vpMatch) {
      visualPrompt = vpMatch[1].trim();
    }

    // 提取旁白/口播
    let narration = '';
    const narrMatch = sec.match(/[-*]\s*(?:旁白|计划口播)[：:]\s*([\s\S]+?)(?=(?:^[-*]\s*(?:脚本分镜|状态|画面来源|连续性分组|教学事实|片段费用|实际口播|字幕)[：:])|$)/m);
    if (narrMatch) {
      narration = narrMatch[1].trim();
    }

    // 提取实际转写/字幕
    let transcript = '';
    const transMatch = sec.match(/[-*]\s*(?:实际口播|字幕)[：:]\s*([\s\S]+?)(?=(?:^[-*]\s*(?:脚本分镜|状态|画面来源|连续性分组|教学事实|片段费用)[：:])|$)/m);
    if (transMatch) {
      transcript = transMatch[1].trim();
    }

    const scriptScene = scriptSceneMatch ? scriptSceneMatch[1].trim() : '';
    const status = statusMatch ? statusMatch[1].trim() : 'ready';
    const visualSource = visualSourceMatch ? visualSourceMatch[1].trim() : '';
    const continuity = continuityMatch ? continuityMatch[1].trim() : '';
    const qaStatus = qaMatch ? qaMatch[1].trim() : '';
    const sceneCost = sceneCostMatch ? sceneCostMatch[1].trim() : '';

    // 对画面提示词进行语义高亮美化，避免一大坨文字无法阅读
    let formattedPrompt = visualPrompt;
    if (formattedPrompt) {
      // 1. 结构化标记转换
      formattedPrompt = formattedPrompt.replace(
        /(画面任务[：:])/g,
        '<span class="vg-clause-tag blue"><span class="vg-tag-icon">🎯</span>画面任务</span>'
      );
      formattedPrompt = formattedPrompt.replace(
        /(版式[：:])/g,
        '<span class="vg-clause-tag indigo"><span class="vg-tag-icon">📐</span>版式设计</span>'
      );
      formattedPrompt = formattedPrompt.replace(
        /(PPT\s*页面语义[：:])/g,
        '<span class="vg-clause-tag slate"><span class="vg-tag-icon">📑</span>PPT 页面语义</span>'
      );
      formattedPrompt = formattedPrompt.replace(
        /(教学语义[：:])/g,
        '<span class="vg-clause-tag emerald"><span class="vg-tag-icon">💡</span>教学语义</span>'
      );
      formattedPrompt = formattedPrompt.replace(
        /(制作要求[：:])/g,
        '<span class="vg-clause-tag amber"><span class="vg-tag-icon">⚠️</span>制作要求</span>'
      );
      formattedPrompt = formattedPrompt.replace(
        /(左侧[^：:；\n]+[：:])/g,
        '<span class="vg-clause-tag cyan"><span class="vg-tag-icon">👈</span>$1</span>'
      );
      formattedPrompt = formattedPrompt.replace(
        /(右侧[^：:；\n]+[：:])/g,
        '<span class="vg-clause-tag violet"><span class="vg-tag-icon">👉</span>$1</span>'
      );

      // 2. asset_id / 引用标记高亮
      formattedPrompt = formattedPrompt.replace(
        /\(asset_id:\s*([a-f0-9-]+)\)/gi,
        '<span class="vg-asset-tag"><span class="vg-asset-icon">🖼️</span>素材: <code>$1</code></span>'
      );
      formattedPrompt = formattedPrompt.replace(
        /\b(slide_\d+)\b/gi,
        '<span class="vg-slide-tag"><span class="vg-slide-icon">📑</span>$1</span>'
      );
      formattedPrompt = formattedPrompt.replace(
        /\b(seg_\w+|obj_\w+|kp_\w+)\b/gi,
        '<span class="vg-code-tag">$1</span>'
      );
    }

    const statusClass = status.toLowerCase() === 'ready' || status.toLowerCase() === 'passed' ? 'success' : (status.toLowerCase() === 'failed' ? 'danger' : 'info');

    html += `
      <article class="vg-scene-card">
        <header class="vg-scene-header">
          <div class="vg-scene-header-left">
            <span class="vg-seq-chip"><span class="vg-seq-icon">🎬</span>${sceneId}</span>
            ${scriptScene ? `<span class="vg-sub-chip script">分镜: ${scriptScene}</span>` : ''}
            ${continuity ? `<span class="vg-sub-chip continuity">组: ${continuity}</span>` : ''}
            ${timeRangeStr ? `<span class="vg-time-chip"><span class="vg-time-icon">⏱️</span>${timeRangeStr}</span>` : ''}
          </div>
          <div class="vg-scene-header-right">
            <span class="vg-status-chip ${statusClass}"><span class="vg-dot"></span>${status}</span>
            ${visualSource ? `<span class="vg-source-chip">📑 来源: ${visualSource.toUpperCase()}</span>` : ''}
            ${qaStatus ? `<span class="vg-qa-chip ${qaStatus === 'passed' ? 'passed' : ''}">QA: ${qaStatus}</span>` : ''}
            ${sceneCost ? `<span class="vg-cost-chip">${sceneCost}</span>` : ''}
          </div>
        </header>

        <div class="vg-scene-body">
          ${formattedPrompt ? `
            <div class="vg-box vg-visual-box">
              <div class="vg-box-header">
                <span class="vg-box-icon">🎨</span>
                <span class="vg-box-title">画面与视觉设计要求</span>
              </div>
              <div class="vg-box-content">${formattedPrompt}</div>
            </div>
          ` : ''}

          ${narration ? `
            <div class="vg-box vg-narration-box">
              <div class="vg-box-header">
                <span class="vg-box-icon">🎙️</span>
                <span class="vg-box-title">教学口播与旁白台词</span>
              </div>
              <div class="vg-box-content">
                <blockquote class="vg-narration-quote">“${narration}”</blockquote>
              </div>
            </div>
          ` : ''}

          ${transcript && transcript !== narration ? `
            <div class="vg-box vg-transcript-box">
              <div class="vg-box-header">
                <span class="vg-box-icon">💬</span>
                <span class="vg-box-title">字幕 / ASR 识别结果</span>
              </div>
              <div class="vg-box-content">${transcript}</div>
            </div>
          ` : ''}
        </div>
      </article>
    `;
  }

  html += `</div>`;
  return html;
}

function renderDocumentMarkdown(content: string): string {
  // 1. 练习题识别
  if (content.includes('ex_')) {
    return renderExerciseMarkdown(content);
  }

  // 2. 微课视频生成识别
  if (
    content.includes('# 微课视频生成') ||
    content.includes('# Seedance 原生有声微课视频') ||
    (content.includes('VG-') && (content.includes('画面提示词') || content.includes('画面来源') || content.includes('制作模式')))
  ) {
    return renderVideoGenerationMarkdown(content);
  }

  const extracted = extractMath(content);
  const normalized = normalizeAgentMarkdown(extracted.text);
  const html = md.render(normalized);
  const restored = restoreMathPlaceholders(html, extracted.inline, extracted.display);

  return formatDocumentHtml(restored);
}

const renderedHtml = computed(() => {
  if (!props.content) return '';
  return renderDocumentMarkdown(props.content);
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
  color: inherit;
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
  color: inherit;
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
  color: inherit;
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

/* 课后练习 Markdown 高保真全能大卡片样式 */
.markdown-rendered-body .md-question-card-block {
  margin-top: 24px;
  margin-bottom: 28px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-left: 5px solid #4f46e5;
  border-radius: 16px;
  padding: 22px 26px;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.06);
  transition: all 200ms ease;
}

.markdown-rendered-body .md-question-card-block:hover {
  border-color: #94a3b8;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.1);
  transform: translateY(-2px);
}

.markdown-rendered-body .card-head-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.markdown-rendered-body .q-badge {
  font-size: 12px;
  font-weight: 900;
  color: #ffffff;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  padding: 3px 12px;
  border-radius: 999px;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.3);
}

.markdown-rendered-body .q-type {
  font-size: 12px;
  font-weight: 800;
  color: #4f46e5;
  background: #eef2ff;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid #c7d2fe;
}

.markdown-rendered-body .q-stem-body {
  font-size: 15.5px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.7;
  margin-bottom: 16px;
}

.markdown-rendered-body .q-stem-body p {
  margin: 0;
  font-size: 15.5px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.7;
}

.markdown-rendered-body .q-options-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin: 16px 0;
}

.markdown-rendered-body .opt-pill {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 16px;
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  font-size: 14px;
  transition: all 180ms ease;
}

.markdown-rendered-body .opt-pill:hover {
  background: #ffffff;
  border-color: #818cf8;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.1);
}

.markdown-rendered-body .opt-letter {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #e0e7ff;
  color: #4f46e5;
  font-size: 12px;
  font-weight: 900;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.markdown-rendered-body .opt-text {
  color: #1e293b;
  font-weight: 600;
  line-height: 1.5;
}

.markdown-rendered-body .q-callout {
  margin-top: 14px;
  padding: 14px 18px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.65;
}

.markdown-rendered-body .q-callout.answer-callout {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-left: 4px solid #10b981;
  border-radius: 10px;
  padding: 10px 16px;
  margin-top: 14px;
}

.markdown-rendered-body .q-callout.answer-callout .callout-tag.green {
  margin-bottom: 0;
  font-size: 11px;
  font-weight: 800;
  color: #047857;
  background: #d1fae5;
  padding: 3px 10px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
}

.markdown-rendered-body .q-callout.answer-callout .callout-val-text {
  font-size: 14px;
  font-weight: 800;
  color: #065f46;
}

.markdown-rendered-body .q-callout.analysis-callout {
  background: #f5f3ff;
  border: 1px solid #ddd6fe;
  border-left: 4px solid #8b5cf6;
  border-radius: 10px;
  padding: 12px 16px;
  margin-top: 10px;
}

.markdown-rendered-body .q-callout.analysis-callout .callout-header {
  margin-bottom: 6px;
}

.markdown-rendered-body .q-callout.analysis-callout .callout-tag.violet {
  margin-bottom: 0;
  font-size: 11px;
  font-weight: 800;
  color: #6d28d9;
  background: #ede9fe;
  padding: 3px 10px;
  border-radius: 999px;
  display: inline-block;
}

.markdown-rendered-body .q-callout.analysis-callout .callout-body-text {
  font-size: 13.5px;
  color: #3b0764;
  line-height: 1.65;
  font-weight: 600;
}

.markdown-rendered-body .q-callout.analysis-callout .callout-body-text p {
  margin: 0;
}

/* -------------------------------------------------------------
   0. 教学设计方案顶部 Masthead 看板 & 目标柱头样式
   ------------------------------------------------------------- */
.markdown-rendered-body .lp-masthead-card {
  margin: 0 0 24px;
  padding: 24px;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 55%, #1e293b 100%);
  border-radius: 18px;
  color: #ffffff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.12);
  position: relative;
  overflow: hidden;
}

.markdown-rendered-body .lp-masthead-card::after {
  content: '';
  position: absolute;
  top: -40%;
  right: -20%;
  width: 260px;
  height: 260px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.25) 0%, rgba(99, 102, 241, 0) 70%);
  pointer-events: none;
}

.markdown-rendered-body .lp-masthead-badge-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.markdown-rendered-body .lp-masthead-kicker {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #818cf8;
  background: rgba(99, 102, 241, 0.16);
  border: 1px solid rgba(99, 102, 241, 0.3);
  padding: 4px 12px;
  border-radius: 999px;
}

.markdown-rendered-body .lp-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 8px #34d399;
  animation: pulse-dot-anim 2s infinite ease-in-out;
}

.markdown-rendered-body .lp-masthead-status-chip {
  font-size: 11px;
  font-weight: 700;
  color: #6ee7b7;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 3px 10px;
  border-radius: 999px;
}

.markdown-rendered-body .lp-masthead-main-title {
  margin: 4px 0 10px;
  font-size: 22px;
  font-weight: 900;
  color: #ffffff;
  letter-spacing: -0.02em;
  border: none;
  padding: 0;
}

.markdown-rendered-body .lp-meta-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.markdown-rendered-body .lp-meta-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 6px;
}

.markdown-rendered-body .lp-meta-tag.grade {
  color: #c7d2fe;
  background: rgba(99, 102, 241, 0.2);
  border: 1px solid rgba(99, 102, 241, 0.3);
}

.markdown-rendered-body .lp-meta-tag.duration {
  color: #fde68a;
  background: rgba(217, 119, 6, 0.2);
  border: 1px solid rgba(217, 119, 6, 0.3);
}

.markdown-rendered-body .lp-meta-tag.version {
  color: #a7f3d0;
  background: rgba(16, 185, 129, 0.2);
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.markdown-rendered-body .lp-metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}

.markdown-rendered-body .lp-metric-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  backdrop-filter: blur(8px);
}

.markdown-rendered-body .lp-metric-card .metric-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.markdown-rendered-body .lp-metric-card .metric-info {
  display: flex;
  flex-direction: column;
}

.markdown-rendered-body .lp-metric-card .metric-label {
  font-size: 10.5px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.markdown-rendered-body .lp-metric-card .metric-val {
  font-size: 13px;
  font-weight: 900;
  color: #f8fafc;
  margin-top: 1px;
}

.markdown-rendered-body .lp-metric-card .metric-val.highlight {
  color: #38bdf8;
  font-variant-numeric: tabular-nums;
}

.markdown-rendered-body .lp-metric-card .metric-val.success {
  color: #6ee7b7;
}

/* 教学目标素养支柱标签 */
.markdown-rendered-body .lp-obj-pillar-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 12px 0 6px;
  padding: 4px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.02em;
}

.markdown-rendered-body .lp-obj-pillar-badge.knowledge {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1.5px solid #bfdbfe;
}

.markdown-rendered-body .lp-obj-pillar-badge.process {
  background: #f5f3ff;
  color: #6d28d9;
  border: 1.5px solid #ddd6fe;
}

.markdown-rendered-body .lp-obj-pillar-badge.attitude {
  background: #ecfdf5;
  color: #047857;
  border: 1.5px solid #a7f3d0;
}

.markdown-rendered-body .lp-obj-pillar-badge .pillar-icon {
  font-size: 14px;
}

/* -------------------------------------------------------------
   1. 教学设计 & 学情分析 标签徽章样式
   ------------------------------------------------------------- */
.markdown-rendered-body .md-tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 800;
  padding: 2px 10px;
  border-radius: 999px;
  margin: 0 4px 2px 0;
  vertical-align: baseline;
}

.markdown-rendered-body .md-tag-chip .chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.markdown-rendered-body .md-tag-chip.blue {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}
.markdown-rendered-body .md-tag-chip.blue .chip-dot { background: #2563eb; }

.markdown-rendered-body .md-tag-chip.violet {
  background: #f5f3ff;
  color: #6d28d9;
  border: 1px solid #ddd6fe;
}
.markdown-rendered-body .md-tag-chip.violet .chip-dot { background: #7c3aed; }

.markdown-rendered-body .md-tag-chip.amber {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fde68a;
}
.markdown-rendered-body .md-tag-chip.amber .chip-dot { background: #d97706; }

.markdown-rendered-body .md-tag-chip.indigo {
  background: #eef2ff;
  color: #4338ca;
  border: 1px solid #c7d2fe;
}
.markdown-rendered-body .md-tag-chip.indigo .chip-dot { background: #4f46e5; }

.markdown-rendered-body .lesson-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 900;
  color: #0f172a;
  margin: 22px 0 12px;
  padding-bottom: 6px;
  border-bottom: 2.5px solid #e2e8f0;
}

.markdown-rendered-body .lesson-section-header .section-icon {
  font-size: 18px;
}

/* -------------------------------------------------------------
   2. 视频脚本制作时间轴卡片 & 画面/旁白/动作结构行
   ------------------------------------------------------------- */
.markdown-rendered-body .script-timestamp-card {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 24px 0 12px;
  padding: 10px 16px;
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border-radius: 12px;
  color: #ffffff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.12);
}

.markdown-rendered-body .script-timestamp-card .time-pill {
  font-size: 12px;
  font-weight: 900;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.25);
  color: #38bdf8;
  padding: 3px 12px;
  border-radius: 999px;
  white-space: nowrap;
  letter-spacing: 0.05em;
}

.markdown-rendered-body .script-timestamp-card .script-title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: #f8fafc;
}

.markdown-rendered-body .script-row {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 12px;
  align-items: start;
  list-style: none;
  margin: 8px 0;
  padding: 12px 16px;
  border-radius: 10px;
  border: 1.5px solid #e2e8f0;
  background: #ffffff;
  transition: all 150ms ease;
}

.markdown-rendered-body .script-row:hover {
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
}

.markdown-rendered-body .script-row.scene-row {
  background: #f8fafc;
  border-color: #cbd5e1;
  border-left: 4px solid #64748b;
}

.markdown-rendered-body .script-row.narration-row {
  background: #f0f9ff;
  border-color: #bae6fd;
  border-left: 4px solid #0284c7;
}

.markdown-rendered-body .script-row.action-row {
  background: #fffbe6;
  border-color: #ffe58f;
  border-left: 4px solid #d4b106;
}

.markdown-rendered-body .script-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 800;
  padding: 4px 10px;
  border-radius: 8px;
  white-space: nowrap;
}

.markdown-rendered-body .scene-badge { background: #e2e8f0; color: #334155; }
.markdown-rendered-body .narration-badge { background: #e0f2fe; color: #0369a1; }
.markdown-rendered-body .action-badge { background: #fff1b8; color: #873800; }

.markdown-rendered-body .script-body-col {
  font-size: 13.5px;
  line-height: 1.65;
  color: #1e293b;
  font-weight: 600;
}

/* -------------------------------------------------------------
   3. 教师逐字稿 (Verbatim Script) Ultra-Modern Visual System
   ------------------------------------------------------------- */

/* Header / Masthead Card */
.markdown-rendered-body .verbatim-masthead-card {
  margin: 0 0 24px 0;
  padding: 24px 28px;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  border: 1.5px solid #e2e8f0;
  border-left: 6px solid #4f46e5;
  border-radius: 16px;
  box-shadow: 0 4px 20px -4px rgba(79, 70, 229, 0.08), 0 2px 6px rgba(15, 23, 42, 0.03);
  position: relative;
  overflow: hidden;
}

.markdown-rendered-body .verbatim-masthead-card::after {
  content: '';
  position: absolute;
  top: -40px;
  right: -40px;
  width: 140px;
  height: 140px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.12) 0%, rgba(255, 255, 255, 0) 70%);
  pointer-events: none;
}

.markdown-rendered-body .masthead-badge-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.markdown-rendered-body .masthead-kicker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #4f46e5;
  letter-spacing: 0.04em;
  background: #eef2ff;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid #c7d2fe;
}

.markdown-rendered-body .pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #6366f1;
  box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.7);
  animation: pulse-ring 2s infinite;
}

@keyframes pulse-ring {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(99, 102, 241, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(99, 102, 241, 0); }
}

.markdown-rendered-body .masthead-status-chip {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 3px 10px;
  border-radius: 6px;
}

.markdown-rendered-body .masthead-main-title {
  margin: 4px 0 16px;
  font-size: 24px;
  font-weight: 900;
  color: #0f172a;
  letter-spacing: -0.02em;
  border: none;
  padding: 0;
}

.markdown-rendered-body .masthead-meta-grid {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.markdown-rendered-body .meta-pill-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 10px;
  font-size: 12px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
}

.markdown-rendered-body .meta-pill-item.speed {
  background: #faf5ff;
  border-color: #e9d5ff;
}

.markdown-rendered-body .meta-pill-item.speed .meta-value {
  color: #7e22ce;
  font-weight: 800;
}

.markdown-rendered-body .meta-pill-item.highlight {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.markdown-rendered-body .meta-pill-item.highlight .meta-value {
  color: #15803d;
  font-weight: 700;
}

.markdown-rendered-body .meta-icon {
  font-size: 13px;
}

.markdown-rendered-body .meta-label {
  color: #64748b;
  font-weight: 600;
}

.markdown-rendered-body .verbatim-speed-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 8px 0 16px;
  padding: 6px 14px;
  background: #faf5ff;
  border: 1.5px solid #e9d5ff;
  border-radius: 10px;
  font-size: 13px;
}

.markdown-rendered-body .verbatim-speed-chip .chip-label {
  color: #6b21a8;
  font-weight: 600;
}

.markdown-rendered-body .verbatim-speed-chip .chip-value {
  color: #7e22ce;
  font-weight: 800;
}

/* Segment Header (seg_01 / seg_02) Card */
.markdown-rendered-body .verbatim-seg-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin: 28px 0 16px;
  padding: 12px 18px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border: 1.5px solid #cbd5e1;
  border-left: 5px solid #4f46e5;
  border-radius: 14px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
  transition: all 0.2s ease;
}

.markdown-rendered-body .verbatim-seg-card:hover {
  border-color: #a5b4fc;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.1);
}

.markdown-rendered-body .seg-head-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.markdown-rendered-body .seg-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  font-weight: 900;
  color: #ffffff;
  background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
  padding: 4px 12px;
  border-radius: 999px;
  letter-spacing: 0.02em;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.3);
}

.markdown-rendered-body .time-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 800;
  color: #3730a3;
  background: #e0e7ff;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid #c7d2fe;
}

.markdown-rendered-body .seg-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.markdown-rendered-body .slides-label {
  color: #475569;
  font-weight: 700;
  white-space: nowrap;
}

.markdown-rendered-body .slides-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.markdown-rendered-body .slide-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 700;
  color: #1e293b;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  padding: 3px 9px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: all 0.15s ease;
}

.markdown-rendered-body .slide-tag:hover {
  border-color: #6366f1;
  color: #4f46e5;
  transform: translateY(-1px);
}

.markdown-rendered-body .slide-icon {
  font-size: 11px;
}

/* Callout Cards (可选补充 & 互动提示) */
.markdown-rendered-body .verbatim-callout {
  margin: 16px 0;
  padding: 16px 20px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.7;
  transition: all 0.2s ease;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.03);
}

.markdown-rendered-body .verbatim-callout .callout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.markdown-rendered-body .verbatim-callout .callout-hint {
  font-size: 11px;
  font-weight: 700;
  opacity: 0.75;
}

.markdown-rendered-body .supplement-callout {
  background: linear-gradient(135deg, #f5f3ff 0%, #faf5ff 100%);
  border: 1.5px solid #ddd6fe;
  border-left: 5px solid #8b5cf6;
  color: #4c1d95;
}

.markdown-rendered-body .supplement-callout:hover {
  box-shadow: 0 4px 16px rgba(139, 92, 246, 0.12);
}

.markdown-rendered-body .supplement-callout .callout-badge.purple {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 900;
  color: #6d28d9;
  background: #ede9fe;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid #ddd6fe;
}

.markdown-rendered-body .interaction-callout {
  background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
  border: 1.5px solid #bae6fd;
  border-left: 5px solid #0284c7;
  color: #0369a1;
}

.markdown-rendered-body .interaction-callout:hover {
  box-shadow: 0 4px 16px rgba(2, 132, 199, 0.12);
}

.markdown-rendered-body .interaction-callout .callout-badge.blue {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 900;
  color: #0369a1;
  background: #e0f2fe;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid #bae6fd;
}

.markdown-rendered-body .callout-body {
  font-size: 14px;
  line-height: 1.75;
}

/* Action Tags in Interaction Guidance */
.markdown-rendered-body .action-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 6px;
  margin: 0 2px;
  vertical-align: baseline;
}

.markdown-rendered-body .action-tag.pause {
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fde68a;
}

.markdown-rendered-body .action-tag.camera {
  background: #e0e7ff;
  color: #3730a3;
  border: 1px solid #c7d2fe;
}

.markdown-rendered-body .action-tag.gesture {
  background: #dcfce7;
  color: #166534;
  border: 1px solid #bbf7d0;
}

.markdown-rendered-body .tag-icon {
  font-size: 11px;
}

/* -------------------------------------------------------------
   4. 微课视频生成看板 & 分镜头故事板（Storyboard Cards）
   ------------------------------------------------------------- */
.markdown-rendered-body .vg-masthead-card {
  margin: 0 0 24px;
  padding: 24px;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 55%, #1e293b 100%);
  border-radius: 18px;
  color: #ffffff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.12);
  position: relative;
  overflow: hidden;
}

.markdown-rendered-body .vg-masthead-card::after {
  content: '';
  position: absolute;
  top: -50%;
  right: -20%;
  width: 280px;
  height: 280px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.25) 0%, rgba(99, 102, 241, 0) 70%);
  pointer-events: none;
}

.markdown-rendered-body .vg-masthead-badge-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.markdown-rendered-body .vg-masthead-kicker {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #818cf8;
  background: rgba(99, 102, 241, 0.16);
  border: 1px solid rgba(99, 102, 241, 0.3);
  padding: 4px 12px;
  border-radius: 999px;
}

.markdown-rendered-body .vg-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 8px #34d399;
  animation: pulse-dot-anim 2s infinite ease-in-out;
}

.markdown-rendered-body .vg-masthead-status-chip {
  font-size: 11px;
  font-weight: 700;
  color: #6ee7b7;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 3px 10px;
  border-radius: 999px;
}

.markdown-rendered-body .vg-masthead-main-title {
  margin: 4px 0 16px;
  font-size: 22px;
  font-weight: 900;
  color: #ffffff;
  letter-spacing: -0.02em;
  border: none;
  padding: 0;
}

.markdown-rendered-body .vg-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}

.markdown-rendered-body .vg-meta-pill {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  backdrop-filter: blur(8px);
  transition: all 0.2s ease;
}

.markdown-rendered-body .vg-meta-pill:hover {
  background: rgba(255, 255, 255, 0.12);
  border-color: rgba(129, 140, 248, 0.4);
}

.markdown-rendered-body .vg-meta-pill.primary {
  border-color: rgba(99, 102, 241, 0.4);
  background: rgba(99, 102, 241, 0.15);
}

.markdown-rendered-body .vg-pill-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.markdown-rendered-body .vg-pill-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.markdown-rendered-body .vg-pill-label {
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.markdown-rendered-body .vg-pill-val {
  font-size: 12.5px;
  font-weight: 800;
  color: #f8fafc;
  margin-top: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.markdown-rendered-body .vg-pill-val.highlight {
  color: #c7d2fe;
}

.markdown-rendered-body .vg-pill-val.success {
  color: #6ee7b7;
}

.markdown-rendered-body .vg-pill-val.duration {
  color: #38bdf8;
  font-variant-numeric: tabular-nums;
}

.markdown-rendered-body .vg-pill-val.amber {
  color: #fcd34d;
}

/* 分镜头故事板列表 */
.markdown-rendered-body .vg-storyboard-stream {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.markdown-rendered-body .vg-scene-card {
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
  overflow: hidden;
  transition: all 0.2s ease;
}

.markdown-rendered-body .vg-scene-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.markdown-rendered-body .vg-scene-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-bottom: 1.5px solid #e2e8f0;
  flex-wrap: wrap;
}

.markdown-rendered-body .vg-scene-header-left,
.markdown-rendered-body .vg-scene-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.markdown-rendered-body .vg-seq-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  font-weight: 900;
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  padding: 4px 12px;
  border-radius: 999px;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.3);
}

.markdown-rendered-body .vg-sub-chip {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 800;
  color: #475569;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  padding: 3px 8px;
  border-radius: 6px;
}

.markdown-rendered-body .vg-sub-chip.continuity {
  color: #7c3aed;
  background: #f5f3ff;
  border-color: #ddd6fe;
}

.markdown-rendered-body .vg-time-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 800;
  color: #0369a1;
  background: #e0f2fe;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid #bae6fd;
  font-variant-numeric: tabular-nums;
}

.markdown-rendered-body .vg-status-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 800;
  padding: 3px 9px;
  border-radius: 999px;
  text-transform: uppercase;
}

.markdown-rendered-body .vg-status-chip.success {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.markdown-rendered-body .vg-status-chip.success .vg-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.markdown-rendered-body .vg-status-chip.danger {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.markdown-rendered-body .vg-status-chip.danger .vg-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #ef4444;
}

.markdown-rendered-body .vg-status-chip.info {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
}

.markdown-rendered-body .vg-status-chip.info .vg-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #94a3b8;
}

.markdown-rendered-body .vg-source-chip {
  font-size: 11px;
  font-weight: 700;
  color: #4338ca;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 3px 8px;
  border-radius: 6px;
}

.markdown-rendered-body .vg-qa-chip {
  font-size: 11px;
  font-weight: 800;
  color: #047857;
  background: #d1fae5;
  border: 1px solid #a7f3d0;
  padding: 3px 8px;
  border-radius: 6px;
}

.markdown-rendered-body .vg-cost-chip {
  font-size: 12px;
  font-weight: 900;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fde68a;
  padding: 3px 8px;
  border-radius: 6px;
}

.markdown-rendered-body .vg-scene-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.markdown-rendered-body .vg-box {
  border-radius: 12px;
  padding: 14px 16px;
  font-size: 13.5px;
  line-height: 1.7;
}

.markdown-rendered-body .vg-box-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.markdown-rendered-body .vg-box-icon {
  font-size: 14px;
}

.markdown-rendered-body .vg-box-title {
  font-size: 11.5px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.markdown-rendered-body .vg-visual-box {
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  color: #1e293b;
}

.markdown-rendered-body .vg-visual-box .vg-box-title {
  color: #334155;
}

.markdown-rendered-body .vg-visual-box .vg-box-content {
  color: #334155;
  font-size: 13.5px;
  line-height: 1.75;
}

.markdown-rendered-body .vg-narration-box {
  background: #f0fdf4;
  border: 1.5px solid #bbf7d0;
  color: #166534;
}

.markdown-rendered-body .vg-narration-box .vg-box-title {
  color: #15803d;
}

.markdown-rendered-body .vg-narration-quote {
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: #14532d;
  font-size: 14.5px;
  font-weight: 600;
  line-height: 1.7;
  font-style: normal;
}

.markdown-rendered-body .vg-transcript-box {
  background: #f0f9ff;
  border: 1.5px solid #bae6fd;
  color: #0369a1;
}

.markdown-rendered-body .vg-transcript-box .vg-box-title {
  color: #0284c7;
}

/* 提示词内部子标签美化 */
.markdown-rendered-body .vg-clause-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: 6px;
  margin: 2px 4px 2px 0;
  vertical-align: baseline;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.markdown-rendered-body .vg-clause-tag.blue {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.markdown-rendered-body .vg-clause-tag.indigo {
  background: #eef2ff;
  color: #4338ca;
  border: 1px solid #c7d2fe;
}

.markdown-rendered-body .vg-clause-tag.slate {
  background: #f1f5f9;
  color: #334155;
  border: 1px solid #cbd5e1;
}

.markdown-rendered-body .vg-clause-tag.emerald {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.markdown-rendered-body .vg-clause-tag.amber {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fde68a;
}

.markdown-rendered-body .vg-clause-tag.cyan {
  background: #ecfeff;
  color: #0e7490;
  border: 1px solid #a5f3fc;
}

.markdown-rendered-body .vg-clause-tag.violet {
  background: #f5f3ff;
  color: #6d28d9;
  border: 1px solid #ddd6fe;
}

.markdown-rendered-body .vg-tag-icon {
  font-size: 11px;
}

.markdown-rendered-body .vg-asset-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  padding: 2px 6px;
  border-radius: 6px;
  margin: 0 2px;
}

.markdown-rendered-body .vg-asset-tag code {
  font-size: 10.5px;
  color: #4f46e5;
  background: transparent;
  border: none;
  padding: 0;
}

.markdown-rendered-body .vg-slide-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11.5px;
  font-weight: 700;
  color: #4338ca;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 2px 7px;
  border-radius: 6px;
  margin: 0 2px;
}

.markdown-rendered-body .vg-code-tag {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  color: #0369a1;
  background: #e0f2fe;
  border: 1px solid #bae6fd;
  padding: 1px 5px;
  border-radius: 4px;
  margin: 0 2px;
}
</style>

