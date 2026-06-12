import { useMemo } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";

marked.setOptions({ breaks: true, gfm: true });

/** Render a Markdown string as sanitized HTML with compact, readable styling. */
export function Markdown({ text }: { text: string }) {
  const html = useMemo(() => {
    const raw = marked.parse(text ?? "", { async: false }) as string;
    return DOMPurify.sanitize(raw);
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
