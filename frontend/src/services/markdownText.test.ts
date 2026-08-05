import { describe, expect, it } from 'vitest';
import MarkdownIt from 'markdown-it';
import {
  extractMath,
  latexToReadableText,
  mathToReadableText,
  normalizeAgentMarkdown,
  renderMathHtml,
  restoreMathPlaceholders,
} from './markdownText';

/**
 * 复刻 MarkdownRenderer.vue 的渲染管道，用于端到端断言。
 */
function renderLikeComponent(content: string): string {
  const extracted = extractMath(content);
  const normalized = normalizeAgentMarkdown(extracted.text);
  const md = new MarkdownIt({ html: false, breaks: true, linkify: true });
  const html = md.render(normalized);
  return restoreMathPlaceholders(html, extracted.inline, extracted.display);
}

describe('normalizeAgentMarkdown — 空行与空白段落', () => {
  it('将 CRLF / CR 统一为 LF', () => {
    expect(normalizeAgentMarkdown('第一行\r\n第二行\r第三行')).toBe('第一行\n第二行\n第三行');
  });

  it('去除每行末尾的多余空格', () => {
    expect(normalizeAgentMarkdown('第一行   \n第二行\t')).toBe('第一行\n第二行');
  });

  it('把三个及以上连续换行压缩为一个段落分隔', () => {
    expect(normalizeAgentMarkdown('第一段\n\n\n\n\n\n第二段\n\n\n\n第三段')).toBe('第一段\n\n第二段\n\n第三段');
  });

  it('清理仅含空格/制表符的空白段落', () => {
    expect(normalizeAgentMarkdown('第一段\n   \n\t\n第二段')).toBe('第一段\n\n第二段');
  });

  it('去掉首尾的空行', () => {
    expect(normalizeAgentMarkdown('\n\n\n第一段\n\n')).toBe('第一段');
  });

  it('保留代码围栏内部的原样内容与空行', () => {
    const input = '开头\n\n```python\n\ndef f():\n    return 1\n\n\nprint(f())\n\n```\n\n结尾';
    const result = normalizeAgentMarkdown(input);
    expect(result).toContain('def f():');
    expect(result).toContain('\n\n\nprint(f())');
    expect(result).toContain('```python');
    // 围栏外的连续空行应被压缩
    expect(result.startsWith('开头\n\n```')).toBe(true);
  });
});

describe('normalizeAgentMarkdown — 残留 HTML 标签剥离', () => {
  it('剥离 <code> 与 </code> 等历史泄漏标签', () => {
    const input = '<code class="math-inline-fallback">F_{上}</code> 与 </code>F_{下}<code>';
    const result = normalizeAgentMarkdown(input);
    expect(result).not.toContain('<code');
    expect(result).not.toContain('</code>');
    expect(result).not.toContain('F_{');
  });

  it('剥离 <div>/<span> 等标签但保留含义', () => {
    const input = '<div class="math-display-fallback">压强公式</div> 与 <span>浮力</span>';
    const result = normalizeAgentMarkdown(input);
    expect(result).not.toContain('<div');
    expect(result).not.toContain('<span');
    expect(result).toContain('压强公式');
    expect(result).toContain('浮力');
  });

  it('不误伤 a<b 这类比较表达式', () => {
    const result = normalizeAgentMarkdown('比较 5 < 10 与 a<b 的结果');
    expect(result).toContain('5 < 10');
    expect(result).toContain('a<b');
  });

  it('不破坏代码围栏内的 < 与 $', () => {
    const result = normalizeAgentMarkdown('```bash\necho $PATH | grep -E "<div>"\n```');
    expect(result).toContain('<div>');
    expect(result).toContain('$PATH');
  });
});

describe('normalizeAgentMarkdown — 裸 LaTeX 转可读文本', () => {
  it('把 F_{上}/F_{下} 转为可读下标', () => {
    expect(normalizeAgentMarkdown('合力为 F_{上}、F_{下} 与 F_{浮}。')).toBe('合力为 F₍上₎、F₍下₎ 与 F₍浮₎。');
  });

  it('把 x^2 转为上标', () => {
    expect(normalizeAgentMarkdown('面积公式 s = x^2')).toBe('面积公式 s = x²');
  });

  it('不误伤 snake_case 标识符', () => {
    expect(normalizeAgentMarkdown('字段 file_path 与 user_id 保持原样')).toBe('字段 file_path 与 user_id 保持原样');
  });

  it('保护 $...$ 公式不被清洗误伤', () => {
    const result = normalizeAgentMarkdown('浮力公式 $F_{浮}=\\rho g V_{排}$ 是核心。');
    expect(result).toContain('$F_{浮}=\\rho g V_{排}$');
  });
});

describe('latexToReadableText — 公式兜底可读化', () => {
  it('分式转为 a/b', () => {
    expect(latexToReadableText('\\frac{1}{2}')).toBe('1/2');
    expect(latexToReadableText('\\frac{a+b}{c}')).toBe('(a+b)/c');
  });

  it('根式转为 √', () => {
    expect(latexToReadableText('\\sqrt{16}')).toBe('√16');
    expect(latexToReadableText('\\sqrt[3]{8}')).toBe('³√8');
  });

  it('中文下标转为可读形式', () => {
    expect(latexToReadableText('F_{上}')).toBe('F₍上₎');
  });

  it('常见符号命令转为 Unicode（保留源空格）', () => {
    expect(latexToReadableText('\\rho g \\cdot h')).toBe('ρ g · h');
    expect(latexToReadableText('\\leq \\geq \\neq')).toBe('≤ ≥ ≠');
  });

  it('布局命令与 \text 正确处理', () => {
    expect(latexToReadableText('\\text{浮力} \\quad F_{浮}')).toBe('浮力  F₍浮₎');
  });
});

describe('extractMath — 公式提取', () => {
  it('提取行内公式并替换为占位符', () => {
    const { text, inline } = extractMath('这是 $F_{上}$ 与 $x^2$。');
    expect(text).toBe('这是 @@LF-MATHi-0@@ 与 @@LF-MATHi-1@@。');
    expect(inline).toEqual(['F_{上}', 'x^2']);
  });

  it('提取独立行公式', () => {
    const { text, display } = extractMath('示例：\n\n$$ F = ma $$\n\n结束');
    expect(text).toContain('@@LF-MATHd-0@@');
    expect(display).toEqual([' F = ma ']);
  });

  it('不把货币写法 $5 误判为公式', () => {
    const { text, inline } = extractMath('花费 $5 元，单价 $3。');
    expect(inline).toEqual([]);
    expect(text).toContain('$5');
  });

  it('跳过代码围栏内的 $', () => {
    const { text, inline } = extractMath('```bash\necho $PATH\n```\n外面 $x$');
    expect(inline).toEqual(['x']);
    expect(text).toContain('echo $PATH');
  });
});

describe('renderMathHtml — 公式渲染', () => {
  it('katex 可渲染时返回 katex HTML，不泄漏源码', () => {
    const html = renderMathHtml('F = ma', true);
    expect(html).toContain('class="katex"');
    expect(html).not.toContain('<code class="math-inline-fallback">');
  });

  it('katex 解析失败时回退为可读普通文本', () => {
    const html = renderMathHtml('\\frac{a}{', false);
    expect(html).toContain('math-inline-fallback');
    expect(html).not.toContain('\\frac');
    expect(html).not.toContain('a/b'); // 未闭合的分式应退化为干净文本
  });

  it('回退文本经过 HTML 转义', () => {
    // \badcommand 会让 katex 抛错，从而触发可读文本回退，再经 escapeHtml 转义
    const html = renderMathHtml('\\badcommand{x}<y', false);
    expect(html).toContain('math-inline-fallback');
    expect(html).toContain('&lt;y');
    expect(html).not.toContain('<y');
  });
});

describe('完整渲染管道 — 用户要求的 6 类场景', () => {
  it('场景1：加粗标题 + 有序列表', () => {
    const html = renderLikeComponent('## 一、教学目标\n\n1. 理解浮力的概念\n2. 掌握公式 **$F_{浮}=\\rho g V_{排}$**\n3. 能解释沉浮条件');
    expect(html).toContain('<h2');
    expect(html).toContain('<ol>');
    expect(html).toContain('<li>');
    expect(html).toContain('<strong>');
    expect(html).not.toContain('<code class="math-inline-fallback">');
    expect(html).not.toContain('F_{');
  });

  it('场景2：数学公式（行内 + 独立行）', () => {
    const html = renderLikeComponent('阿基米德原理：\n\n$$ F_{浮} = \\rho_{\\text{液}} g V_{排} $$\n\n其中 $F_{浮}$ 表示浮力。');
    expect(html).toContain('katex-display');
    expect(html).toContain('class="katex"');
    expect(html).not.toContain('<code class="math-inline-fallback">');
    expect(html).not.toContain('F_{');
  });

  it('场景3：包含错误 <code> 标签的历史输出', () => {
    const html = renderLikeComponent('之前的结果：<code class="math-inline-fallback">F_{上}</code>、<code>F_{下}</code>、F_{浮}');
    expect(html).not.toContain('<code class="math-inline-fallback">');
    expect(html).not.toContain('</code>');
    expect(html).not.toContain('F_{');
  });

  it('场景4：大量连续换行', () => {
    const html = renderLikeComponent('第一段\n\n\n\n\n\n第二段\n\n\n\n第三段');
    // markdown-it 会把段落渲染成 <p>，连续空行已被压缩
    expect(html).toContain('<p>第一段</p>\n<p>第二段</p>\n<p>第三段</p>');
    expect(html).not.toContain('<p>第一段</p>\n\n\n\n<p>');
  });

  it('场景5：流式追加文本的排版与最终一致', () => {
    // 模拟流式 delta 不断追加后统一归一化渲染
    let streamed = '';
    const deltas = ['## 步骤一\n', '\n\n\n', '1. 测量质量\n', '2. 计算密度\n', '\n\n', '结论：$\\rho = m/V$'];
    for (const delta of deltas) {
      streamed += delta;
      const html = renderLikeComponent(streamed);
      expect(html).not.toContain('<code class="math-inline-fallback">');
    }
    const finalHtml = renderLikeComponent(streamed);
    expect(finalHtml).toContain('<ol>');
    expect(finalHtml).toContain('class="katex"');
    // 流式中间与最终排版一致：都不存在 4 连换行
    expect(renderLikeComponent(streamed)).not.toMatch(/\n{4,}/);
  });

  it('场景6：中英文混合、长文本与特殊字符', () => {
    const input = '本节课讲解 Newton\'s Laws of Motion（牛顿运动定律）。\n\n'
      + '单位：m/s²、kg·m/s，温度 25 ℃，比例 50%。\n\n'
      + '**重点**：$F = ma$，$E_k = \\frac{1}{2}mv^2$。\n\n'
      + '引用符号：< 5、> 3、a & b、"引号"。';
    const html = renderLikeComponent(input);
    expect(html).toContain("Newton's Laws of Motion");
    expect(html).not.toContain('<code class="math-inline-fallback">');
    expect(html).not.toContain('F = ma$'); // 公式已渲染，不应残留美元分隔符
    expect(html).toContain('class="katex"');
  });
});

describe('mathToReadableText / restoreMathPlaceholders', () => {
  it('mathToReadableText 输出可读文本', () => {
    expect(mathToReadableText('\\rho g h')).toBe('ρ g h');
  });

  it('restoreMathPlaceholders 还原占位符', () => {
    const html = restoreMathPlaceholders(
      '<p>面积 @@LF-MATHi-0@@ 平方米</p>',
      ['x^2'],
      [],
    );
    expect(html).toContain('class="katex"');
    expect(html).not.toContain('@@LF-MATH');
  });

  it('转义的美金符号原样保留', () => {
    const extracted = extractMath('预算 \\$500 与 $x$');
    expect(extracted.inline).toEqual(['x']);
    const html = restoreMathPlaceholders('<p>预算 \\$500 与 @@LF-MATHi-0@@</p>', ['x'], []);
    expect(html).toContain('$500');
  });
});
