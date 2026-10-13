import type { ReactNode } from "react";

function inline(text: string): ReactNode[] {
  const safe = text.replace(/<[^>]*>/g, "");
  return safe.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith("**") && part.endsWith("**")
    ? <strong key={index}>{part.slice(2, -2)}</strong>
    : <span key={index}>{part}</span>);
}

export function Markdown({ source }: { source: string }) {
  const blocks = source.replace(/\r\n?/g, "\n").split(/\n{2,}/).map((block) => block.trim()).filter(Boolean);
  return <div className="markdown-content">
    {blocks.map((block, index) => {
      const lines = block.split("\n");
      if (lines.length === 1 && /^#{1,3} /.test(lines[0])) {
        const level = Math.min(lines[0].match(/^#+/)![0].length, 3) as 1 | 2 | 3;
        const text = lines[0].replace(/^#+\s+/, "");
        return level === 1 ? <h2 key={index}>{inline(text)}</h2> : level === 2 ? <h3 key={index}>{inline(text)}</h3> : <h4 key={index}>{inline(text)}</h4>;
      }
      return <p key={index}>{lines.map((line, lineIndex) => <span key={lineIndex}>{lineIndex > 0 && <br />}{inline(line)}</span>)}</p>;
    })}
  </div>;
}
