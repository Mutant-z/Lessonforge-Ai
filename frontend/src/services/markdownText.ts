/**
 * Agent 输出文本的统一清洗与归一化工具。
 *
 * 解决的问题：
 * 1. Agent 或公式 fallback 曾直接把原始 HTML（如 `<code class="math-inline-fallback">`）
 *    塞进 markdown 源码，被 markdown-it 以 html:false 转义后，标签源码直接暴露给用户。
 * 2. 大量无意义空行 / 空白段落导致内容区域过度拉长。
 * 3. 公式解析失败时直接暴露 LaTeX 源码（如 `F_{上}`）。
 *
 * 目标：只把用户可读的内容交给渲染层；原始 HTML 标签被剥离、LaTeX 转为可读文本、
 * 连续空行被压缩，且不破坏代码围栏内部内容。
 */

import katex from 'katex';

/** 占位符分隔符（显式 NUL 转义，运行时才是真正的 NUL 字符）。 */
const NUL = '\u0000';

/** 已知会被剥离的 HTML 标签名（不含 b/i，避免误伤 `a<b` 这类比较表达式）。 */
const STRAY_TAG_NAMES = new Set([
  'code', 'div', 'span', 'p', 'br', 'hr', 'small', 's', 'u', 'big', 'kbd',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'pre', 'ul', 'ol', 'li', 'blockquote', 'table', 'thead', 'tbody', 'tfoot',
  'tr', 'th', 'td', 'a', 'img', 'sup', 'sub', 'em', 'strong',
  // KaTeX 内部会出现的数学 DOM 标签
  'math', 'annotation', 'annotation-xml', 'semantics', 'svg',
  'mi', 'mo', 'mn', 'mrow', 'mfrac', 'msqrt', 'mtext', 'msub', 'msup', 'mspace',
]);

const STRAY_TAG_RE = /<\/?[a-zA-Z][a-zA-Z0-9-]*(?:\s+[a-zA-Z0-9_:.-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*\s*\/?>/g;

/** 剥离已知的 HTML 标签；未知标签原样保留（可能是 `a<b` 之类的比较写法）。 */
function stripStrayHtmlTags(line: string): string {
  return line.replace(STRAY_TAG_RE, (tag) => {
    const match = tag.match(/^<\/?([a-zA-Z][a-zA-Z0-9-]*)/);
    const name = match?.[1]?.toLowerCase();
    return name && STRAY_TAG_NAMES.has(name) ? '' : tag;
  });
}

/** Unicode 下标映射（支持常见的下标字符）。 */
const SUBSCRIPT_MAP: Record<string, string> = {
  '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅',
  '6': '₆', '7': '₇', '8': '₈', '9': '₉',
  '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
  'a': 'ₐ', 'e': 'ₑ', 'h': 'ₕ', 'i': 'ᵢ', 'j': 'ⱼ', 'k': 'ₖ',
  'l': 'ₗ', 'm': 'ₘ', 'n': 'ₙ', 'o': 'ₒ', 'p': 'ₚ', 'r': 'ᵣ',
  's': 'ₛ', 't': 'ₜ', 'u': 'ᵤ', 'v': 'ᵥ', 'x': 'ₓ',
};

/** Unicode 上标映射。 */
const SUPERSCRIPT_MAP: Record<string, string> = {
  '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵',
  '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
  '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾', 'n': 'ⁿ', 'i': 'ⁱ',
};

function mapScript(content: string, table: Record<string, string>, fallbackOpen: string, fallbackClose: string): string {
  let allMapped = true;
  let mapped = '';
  for (const char of content) {
    const replacement = table[char];
    if (replacement) {
      mapped += replacement;
    } else {
      allMapped = false;
      mapped += char;
    }
  }
  return allMapped ? mapped : `${fallbackOpen}${content}${fallbackClose}`;
}

function toSubscript(content: string): string {
  return mapScript(content, SUBSCRIPT_MAP, '₍', '₎');
}

function toSuperscript(content: string): string {
  return mapScript(content, SUPERSCRIPT_MAP, '⁽', '⁾');
}

/** 常用 LaTeX 命令 → Unicode 符号。 */
const SYMBOL_MAP: Record<string, string> = {
  cdot: '·', times: '×', pm: '±', mp: '∓', div: '÷',
  leq: '≤', geq: '≥', neq: '≠', approx: '≈', sim: '∼', equiv: '≡', propto: '∝',
  rightarrow: '→', leftarrow: '←', Rightarrow: '⇒', Leftarrow: '⇐', leftrightarrow: '↔',
  infty: '∞', pi: 'π', alpha: 'α', beta: 'β', gamma: 'γ', Gamma: 'Γ',
  delta: 'δ', Delta: 'Δ', theta: 'θ', Theta: 'Θ', mu: 'μ', nu: 'ν', xi: 'ξ',
  rho: 'ρ', sigma: 'σ', Sigma: 'Σ', tau: 'τ', phi: 'φ', Phi: 'Φ', omega: 'ω',
  Omega: 'Ω', lambda: 'λ', Lambda: 'Λ', epsilon: 'ε', eta: 'η', zeta: 'ζ',
  chi: 'χ', psi: 'ψ', sum: '∑', int: '∫', oint: '∮', partial: '∂', nabla: '∇',
  ldots: '…', dots: '…', cdots: '·', cdotp: '·', degree: '°', circ: '°', angle: '∠',
  parallel: '∥', perp: '⊥', forall: '∀', exists: '∃', emptyset: '∅',
  in: '∈', notin: '∉', subset: '⊂', subseteq: '⊆', supset: '⊃', supseteq: '⊇',
  cup: '∪', cap: '∩', vee: '∨', wedge: '∧', neg: '¬', oplus: '⊕', otimes: '⊗',
};

const COMBINING_ACCENT: Record<string, string> = {
  vec: '⃗', hat: '̂', bar: '̄', overline: '̄',
  tilde: '̃', dot: '̇', ddot: '̈',
};

export interface LatexOptions {
  /** 是否转换不带花括号的下标（如 `x_1`）。正文清洗默认关闭，避免误伤 snake_case。 */
  bareSubscript?: boolean;
  /** 是否转换不带花括号的上标（如 `x^2`）。 */
  bareSuperscript?: boolean;
}

/**
 * 将 LaTeX 片段转换为人类可读的普通文本。
 * 用于 katex 不可用或解析失败时的兜底，禁止把 `_{...}` 之类的源码直接展示给用户。
 */
export function latexToReadableText(src: string, options: LatexOptions = {}): string {
  const { bareSubscript = true, bareSuperscript = true } = options;
  let out = '';
  let i = 0;

  const readGroup = (start: number): { content: string; end: number } | null => {
    if (src[start] !== '{') return null;
    let depth = 0;
    let content = '';
    for (let j = start; j < src.length; j++) {
      const ch = src[j];
      if (ch === '{') {
        depth += 1;
        if (depth > 1) content += ch;
      } else if (ch === '}') {
        depth -= 1;
        if (depth === 0) return { content, end: j + 1 };
        content += ch;
      } else {
        content += ch;
      }
    }
    return null;
  };

  const readBracketGroup = (start: number): { content: string; end: number } | null => {
    if (src[start] !== '[') return null;
    let depth = 0;
    let content = '';
    for (let j = start; j < src.length; j++) {
      const ch = src[j];
      if (ch === '[') {
        depth += 1;
        if (depth > 1) content += ch;
      } else if (ch === ']') {
        depth -= 1;
        if (depth === 0) return { content, end: j + 1 };
        content += ch;
      } else {
        content += ch;
      }
    }
    return null;
  };

  while (i < src.length) {
    const ch = src[i];
    // 处理 `\command` 或单字符转义
    if (ch === '\\') {
      const cmdMatch = src.slice(i).match(/^\\([a-zA-Z]+)/);
      if (cmdMatch) {
        const cmd = cmdMatch[1];
        const cmdLen = cmdMatch[0].length;
        const groupStart = i + cmdLen;
        const hasGroup = src[groupStart] === '{';

        if (cmd === 'frac' || cmd === 'dfrac' || cmd === 'tfrac' || cmd === 'cfrac') {
          const num = hasGroup ? readGroup(groupStart) : null;
          const denStart = num ? num.end : groupStart;
          const den = src[denStart] === '{' ? readGroup(denStart) : null;
          const numerator = num ? latexToReadableText(num.content, options) : '';
          const denominator = den ? latexToReadableText(den.content, options) : '';
          const wrap = (value: string) => (/[+\-×÷·=<>~≈≤≥±∓]/.test(value) ? `(${value})` : value);
          out += `${wrap(numerator)}/${wrap(denominator)}`;
          i = den ? den.end : num ? num.end : groupStart;
          continue;
        }

        if (cmd === 'sqrt') {
          let cursor = groupStart;
          const root = src[cursor] === '[' ? readBracketGroup(cursor) : null;
          if (root) cursor = root.end;
          const radicand = src[cursor] === '{' ? readGroup(cursor) : null;
          const body = radicand ? latexToReadableText(radicand.content, options) : '';
          out += root ? `${toSuperscript(root.content)}√${body}` : `√${body}`;
          i = radicand ? radicand.end : root ? root.end : groupStart;
          continue;
        }

        if (cmd === 'text' || cmd === 'mathrm' || cmd === 'textnormal' || cmd === 'mbox' || cmd === 'operatorname') {
          const group = hasGroup ? readGroup(groupStart) : null;
          out += group ? latexToReadableText(group.content, options) : '';
          i = group ? group.end : groupStart;
          continue;
        }

        if (cmd === 'left' || cmd === 'right' || cmd === 'middle') {
          i += cmdLen + (src[i + cmdLen] === '.' ? 1 : 0);
          continue;
        }

        if (COMBINING_ACCENT[cmd]) {
          const group = hasGroup ? readGroup(groupStart) : null;
          const content = group ? group.content : src[i + cmdLen] ?? '';
          const base = latexToReadableText(content, options);
          out += base.charAt(0) + COMBINING_ACCENT[cmd] + base.slice(1);
          i = group ? group.end : i + cmdLen + (content ? content.length : 0);
          continue;
        }

        if (SYMBOL_MAP[cmd]) {
          out += SYMBOL_MAP[cmd];
          i += cmdLen;
          continue;
        }

        // 布局类命令直接丢弃
        if (['quad', 'qquad', 'displaystyle', 'textstyle', 'scriptstyle', 'limits', 'nolimits',
          'big', 'Big', 'bigg', 'Bigg', 'bigl', 'bigr', 'Bigl', 'Bigr', 'biggl', 'biggr', 'Biggl', 'Biggr',
        ].includes(cmd)) {
          i += cmdLen;
          continue;
        }

        // 未知命令：丢弃命令本身，保留后续花括号组内容
        i += cmdLen;
        continue;
      }
      // 单字符转义（如 `\,`、`\;`、`\{`）
      out += src[i + 1] ?? '';
      i += 2;
      continue;
    }

    // 上标 / 下标
    if (ch === '_' || ch === '^') {
      const next = src[i + 1];
      const braced = next === '{';
      const group = braced ? readGroup(i + 1) : null;
      const bare = group ? null : (next && !/[\s]/.test(next) ? next : null);
      const canConvertBare = ch === '^' ? bareSuperscript : bareSubscript;
      if (group) {
        out += ch === '_' ? toSubscript(latexToReadableText(group.content, options)) : toSuperscript(latexToReadableText(group.content, options));
        i = group.end;
        continue;
      }
      if (bare && canConvertBare) {
        out += ch === '_' ? toSubscript(bare) : toSuperscript(bare);
        i += 2;
        continue;
      }
      // 无法安全转换（如正文里的 snake_case）：原样保留
      out += ch;
      i += 1;
      continue;
    }

    out += ch;
    i += 1;
  }

  return out;
}

/**
 * 归一化 Agent 输出的 Markdown 文本：
 * - `\r\n` / `\r` → `\n`；
 * - 去除每行末尾空格；
 * - 压缩连续空行（最多保留一个段落分隔）；
 * - 清理仅含空白字符的行；
 * - 剥离已知的 HTML 标签（代码围栏内不受影响）；
 * - 把裸 LaTeX 下标/上标/分式转换为可读文本（`$...$` 公式与代码围栏内的内容原样保留）；
 * - 保留代码围栏内部内容原样。
 *
 * 该函数可独立用于原始内容；渲染管道中在 extractMath 之后调用也安全——
 * 因为此时 `$...$` 已被替换为占位符，内部的数学保护逻辑自动变为空操作。
 */
export function normalizeAgentMarkdown(input: string): string {
  if (!input) return '';
  const normalizedEol = input.replace(/\r\n?/g, '\n');
  const mathTokens: string[] = [];

  const { value, restore } = withProtectedCodeBlocks(normalizedEol, (outside) => {
    let text = outside.replace(/\\\$/g, `${NUL}LFDOL${NUL}`);
    text = text.replace(DISPLAY_MATH_RE, (whole, math) => {
      mathTokens.push(`$$${math}$$`);
      return `${NUL}LFMATH${mathTokens.length - 1}${NUL}`;
    });
    text = text.replace(INLINE_MATH_RE, (whole, math) => {
      // 公式内容首尾不允许是空白，避免把 “价格 $5 元” 之类的货币写法误判为公式
      if (/^\s|\s$/.test(math)) return whole;
      mathTokens.push(`$${math}$`);
      return `${NUL}LFMATH${mathTokens.length - 1}${NUL}`;
    });
    return text;
  });

  // 此时代码围栏与公式都已被占位符保护，可以对正文安全清洗
  let processed = stripStrayHtmlTags(value);
  processed = latexToReadableText(processed, { bareSubscript: false, bareSuperscript: true });

  // 压缩连续空行、清理空白行
  const lines = processed.split('\n').map(line => line.replace(/[ \t]+$/g, ''));
  const cleaned: string[] = [];
  let pendingBlank = false;
  for (const line of lines) {
    if (line.trim() === '') {
      if (cleaned.length && cleaned[cleaned.length - 1] !== '') {
        pendingBlank = true;
      }
      continue;
    }
    if (pendingBlank && cleaned.length && cleaned[cleaned.length - 1] !== '') {
      cleaned.push('');
    }
    pendingBlank = false;
    cleaned.push(line);
  }
  while (cleaned.length && cleaned[0] === '') cleaned.shift();
  while (cleaned.length && cleaned[cleaned.length - 1] === '') cleaned.pop();

  const collapsed = cleaned.join('\n');
  const withMath = collapsed.replace(new RegExp(`${NUL}LFMATH(\\d+)${NUL}`, 'g'), (_, i) => mathTokens[Number(i)] ?? '');
  return restore(withMath);
}

const FENCE_OPENER_RE = /^\s*(`{3,}|~{3,})/;
const FENCE_CLOSER_RE = /^\s*([`~])\1{2,}\s*$/;

/**
 * 保护代码围栏：对围栏外的文本执行 fn，围栏内部内容原样保留。
 * 用于公式提取等需要跳过代码块的场景。
 * 采用逐行扫描而非单条正则，避免 m 标志下 `$` 匹配行尾导致围栏被拆散。
 */
export function withProtectedCodeBlocks<T>(text: string, fn: (outsideText: string) => T): { value: T; restore: (processedOutside: string) => string } {
  const blocks: string[] = [];
  let result = '';
  let i = 0;

  while (i < text.length) {
    const lineEnd = text.indexOf('\n', i);
    const lineLimit = lineEnd === -1 ? text.length : lineEnd;
    const opener = text.slice(i, lineLimit).match(FENCE_OPENER_RE);

    if (!opener) {
      if (lineEnd === -1) {
        result += text.slice(i);
        break;
      }
      result += text.slice(i, lineEnd + 1);
      i = lineEnd + 1;
      continue;
    }

    // 找到与开启行同字符的闭合围栏行；未闭合则取到文本末尾
    const fenceChar = opener[1][0];
    let closeEnd = -1;
    let j = lineLimit + 1;
    while (j < text.length) {
      const nl = text.indexOf('\n', j);
      const limit = nl === -1 ? text.length : nl;
      const line = text.slice(j, limit);
      if (line.match(FENCE_CLOSER_RE) && line.trim().startsWith(fenceChar)) {
        closeEnd = nl === -1 ? text.length : nl + 1;
        break;
      }
      if (nl === -1) break;
      j = nl + 1;
    }

    if (closeEnd === -1) {
      blocks.push(text.slice(i));
      result += `${NUL}LFCODE${blocks.length - 1}${NUL}`;
      break;
    }

    blocks.push(text.slice(i, closeEnd));
    result += `${NUL}LFCODE${blocks.length - 1}${NUL}`;
    i = closeEnd;
  }

  const value = fn(result);
  const restore = (processedOutside: string) =>
    processedOutside.replace(new RegExp(`${NUL}LFCODE(\\d+)${NUL}`, 'g'), (_, index) => blocks[Number(index)] ?? '');
  return { value, restore };
}

export interface ExtractedMath {
  /** 已把公式替换为占位符的文本（占位符不含 `_`/`^`/`\`，不会被后续清洗误伤）。 */
  text: string;
  inline: string[];
  display: string[];
}

const INLINE_MATH_RE = /\$([^$\n]+?)\$/g;
const DISPLAY_MATH_RE = /\$\$([\s\S]+?)\$\$/g;

/**
 * 从文本中提取 `$...$` 与 `$$...$$` 公式，替换为占位符。
 * 提取时跳过代码围栏，避免 `echo $PATH` 之类的内容被误判。
 */
export function extractMath(source: string): ExtractedMath {
  const inline: string[] = [];
  const display: string[] = [];

  const { value, restore } = withProtectedCodeBlocks(source, (outside) => {
    // 先处理被 `\$` 转义的美金符号，避免被当作公式分隔符
    let text = outside.replace(/\\\$/g, `${NUL}LFDOL${NUL}`);

    text = text.replace(DISPLAY_MATH_RE, (whole, math) => {
      display.push(math);
      return `@@LF-MATHd-${display.length - 1}@@`;
    });

    text = text.replace(INLINE_MATH_RE, (whole, math) => {
      // 公式内容首尾不允许是空白，避免把 “价格 $5 元” 之类的货币写法误判为公式
      if (/^\s|\s$/.test(math)) return whole;
      inline.push(math);
      return `@@LF-MATHi-${inline.length - 1}@@`;
    });

    return text;
  });

  return { text: restore(value), inline, display };
}

/**
 * 渲染数学公式：优先 katex，失败时回退为可读的普通文本。
 * 返回可直接插入 HTML 的字符串。
 */
export function renderMathHtml(math: string, displayMode: boolean): string {
  const renderFallback = (readable: string) =>
    displayMode
      ? `<div class="math-display-fallback">${escapeHtml(readable)}</div>`
      : `<span class="math-inline-fallback">${escapeHtml(readable)}</span>`;

  if (!math.trim()) return '';

  try {
    return katex.renderToString(math, {
      displayMode,
      throwOnError: true,
      strict: false,
      output: 'html',
    });
  } catch {
    // katex 解析失败 → 转为可读文本，禁止暴露原始 LaTeX
    return renderFallback(latexToReadableText(math, { bareSubscript: true, bareSuperscript: true }));
  }
}

/** 把 LaTeX 公式转为可读的普通文本（katex 完全不可用时的兜底）。 */
export function mathToReadableText(math: string): string {
  return latexToReadableText(math, { bareSubscript: true, bareSuperscript: true });
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** 把提取出的公式占位符还原为渲染结果。 */
export function restoreMathPlaceholders(html: string, inline: string[], display: string[]): string {
  return html
    .replace(new RegExp(`${NUL}LFDOL${NUL}`, 'g'), '$$')
    .replace(/@@LF-MATHi-(\d+)@@/g, (_, i) => renderMathHtml(inline[Number(i)], false))
    .replace(/@@LF-MATHd-(\d+)@@/g, (_, i) => renderMathHtml(display[Number(i)], true));
}
