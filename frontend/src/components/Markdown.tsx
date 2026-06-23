import { useMemo } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import katex from "katex";
import "katex/dist/katex.min.css";

marked.setOptions({ breaks: true, gfm: true });

// Private-use sentinels so math placeholders survive Markdown + sanitization.
const OPEN = "";
const CLOSE = "";

/** Pull LaTeX out of the text and pre-render it with KaTeX, leaving placeholders
 *  that Markdown won't touch. Handles $$…$$ / \[…\] (block) and $…$ / \(…\)
 *  (inline). The inline $ form requires non-space boundaries so prose like
 *  "it cost $5 and $10" isn't treated as math. */
function extractMath(text: string): { text: string; math: string[] } {
  const math: string[] = [];
  const stash = (tex: string, display: boolean) => {
    let html: string;
    try {
      html = katex.renderToString(tex.trim(), { displayMode: display, throwOnError: false });
    } catch {
      html = display ? `$$${tex}$$` : `$${tex}$`;
    }
    math.push(html);
    return `${OPEN}${math.length - 1}${CLOSE}`;
  };
  return {
    text: text
      .replace(/\$\$([\s\S]+?)\$\$/g, (_, e) => stash(e, true))
      .replace(/\\\[([\s\S]+?)\\\]/g, (_, e) => stash(e, true))
      .replace(/\\\(([\s\S]+?)\\\)/g, (_, e) => stash(e, false))
      .replace(/\$(?!\s)([^$\n]+?)(?<!\s)\$/g, (_, e) => stash(e, false)),
    math,
  };
}

/** Render a Markdown string (with LaTeX) as sanitized HTML. */
export function Markdown({ text }: { text: string }) {
  const html = useMemo(() => {
    const { text: protectedText, math } = extractMath(text ?? "");
    const raw = marked.parse(protectedText, { async: false }) as string;
    let clean = DOMPurify.sanitize(raw);
    // Re-insert the locally-generated (trusted) KaTeX HTML after sanitization,
    // so its spans/styles aren't stripped.
    clean = clean.replace(
      new RegExp(`${OPEN}(\\d+)${CLOSE}`, "g"),
      (_, i) => math[Number(i)] ?? "",
    );
    return clean;
  }, [text]);

  return (
    <div
      className="md text-sm leading-relaxed text-slate-800
        [&_p]:my-1.5
        [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5
        [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-5
        [&_li]:my-0.5
        [&_strong]:font-semibold [&_strong]:text-slate-900
        [&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[12px]
        [&_h1]:mt-2 [&_h1]:mb-1 [&_h1]:text-base [&_h1]:font-semibold
        [&_h2]:mt-2 [&_h2]:mb-1 [&_h2]:text-sm [&_h2]:font-semibold
        [&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:text-sm [&_h3]:font-semibold
        [&_a]:text-indigo-600 [&_a]:underline
        [&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:text-xs
        [&_th]:border [&_th]:border-slate-200 [&_th]:bg-slate-50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left
        [&_td]:border [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
