import { useRef, useState } from "react";
import { api } from "../api/client";
import type { ChartRequest, ChatTurn } from "../api/types";
import { useApp } from "../store";
import { VegaChart } from "../components/VegaChart";
import { ChevronRight, SendIcon, SparkleIcon } from "../components/icons";

interface AssistantMsg {
  role: "assistant";
  text: string;
  actionType?: string;
  sql?: string | null;
  spec?: Record<string, unknown> | null;
  chartRequest?: ChartRequest | null;
  error?: string | null;
}
type Msg = { role: "user"; text: string } | AssistantMsg;

const SUGGESTIONS = [
  "How many rows are in each dataset?",
  "Plot a histogram of the numeric columns.",
  "Which categories are most common?",
];

export function ChatPanel({ onCollapse }: { onCollapse: () => void }) {
  const { openInVisualize } = useApp();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  function scrollDown() {
    requestAnimationFrame(() =>
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }),
    );
  }

  async function send(text: string) {
    text = text.trim();
    if (!text || streaming) return;
    const history: ChatTurn[] = messages.map((m) => ({ role: m.role, content: m.text }));
    setMessages((m) => [...m, { role: "user", text }, { role: "assistant", text: "" }]);
    setInput("");
    setStreaming(true);
    scrollDown();
    try {
      await api.agentChat(text, history, (e) => {
        setMessages((msgs) => {
          const copy = [...msgs];
          const last = copy[copy.length - 1] as AssistantMsg;
          if (e.type === "action") {
            last.actionType = e.action_type;
            last.sql = e.sql;
            last.spec = e.spec;
            last.chartRequest = e.chart_request;
          } else if (e.type === "message") {
            last.text = e.response;
            last.error = e.error;
          } else if (e.type === "error") {
            last.text = "⚠️ " + e.error;
            last.error = e.error;
          }
          return copy;
        });
        scrollDown();
      });
    } catch (err) {
      setMessages((msgs) => {
        const copy = [...msgs];
        (copy[copy.length - 1] as AssistantMsg).text = "⚠️ " + String((err as Error).message);
        return copy;
      });
    } finally {
      setStreaming(false);
      scrollDown();
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
            <SparkleIcon className="h-4 w-4" />
          </span>
          <div>
            <div className="text-sm font-semibold text-slate-800">Analyst</div>
            <div className="text-[11px] text-slate-400">read-only · runs locally</div>
          </div>
        </div>
        <button
          onClick={onCollapse}
          title="Collapse"
          className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <ChevronRight />
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-auto px-4 py-4">
        {messages.length === 0 && (
          <div className="pt-6">
            <p className="text-sm text-slate-500">
              Ask anything about your data. I can query it, build charts, and run
              statistics — and I never change your originals.
            </p>
            <div className="mt-4 space-y-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="block w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs text-slate-600 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-3.5 py-2 text-sm text-white">
                {m.text}
              </div>
            </div>
          ) : (
            <AssistantBubble key={i} msg={m} onOpenChart={openInVisualize} />
          ),
        )}
        {streaming && (
          <div className="flex items-center gap-1.5 px-1 text-xs text-slate-400">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-300 [animation-delay:-0.2s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-300 [animation-delay:-0.1s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-300" />
          </div>
        )}
      </div>

      <div className="border-t border-slate-200 p-3">
        <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white p-1.5 focus-within:border-indigo-400 focus-within:ring-2 focus-within:ring-indigo-100">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={1}
            placeholder="Ask the analyst…"
            className="max-h-32 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none"
          />
          <button
            onClick={() => send(input)}
            disabled={streaming || !input.trim()}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white transition hover:bg-indigo-500 disabled:opacity-40"
          >
            <SendIcon className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function AssistantBubble({
  msg,
  onOpenChart,
}: {
  msg: AssistantMsg;
  onOpenChart: (r: ChartRequest) => void;
}) {
  const [showCode, setShowCode] = useState(false);
  return (
    <div className="animate-in rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 shadow-sm">
      <div className="whitespace-pre-wrap leading-relaxed">{msg.text || "…"}</div>

      {(msg.sql || msg.spec) && (
        <button
          onClick={() => setShowCode((s) => !s)}
          className="mt-2 inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-200"
        >
          {showCode ? "Hide" : msg.sql ? "SQL used" : "Chart spec"}
        </button>
      )}
      {showCode && (
        <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-slate-900 p-2.5 text-[11px] leading-relaxed text-slate-100">
          {msg.sql ?? JSON.stringify(msg.spec, null, 2)}
        </pre>
      )}

      {msg.spec && (
        <div className="mt-2.5">
          <div className="rounded-lg border border-slate-100 bg-slate-50 p-2">
            <VegaChart spec={msg.spec} />
          </div>
          {msg.chartRequest && (
            <button
              onClick={() => onOpenChart(msg.chartRequest!)}
              className="mt-1.5 text-[11px] font-medium text-indigo-600 hover:underline"
            >
              Open in Visualize →
            </button>
          )}
        </div>
      )}
    </div>
  );
}
