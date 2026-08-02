declare module 'highlight.js' {
  const hljs: any;
  export default hljs;
}

declare module 'katex' {
  const katex: {
    renderToString(math: string, options?: any): string;
    [key: string]: any;
  };
  export default katex;
}

declare module 'mermaid' {
  const mermaid: {
    initialize(config: any): void;
    render(id: string, text: string): Promise<{ svg: string }>;
    [key: string]: any;
  };
  export default mermaid;
}

declare module 'markdown-it' {
  class MarkdownIt {
    constructor(options?: any);
    render(src: string, env?: any): string;
    [key: string]: any;
  }
  export default MarkdownIt;
}
