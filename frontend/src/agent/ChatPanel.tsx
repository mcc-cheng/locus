import { useRef, useState } from "react";
import { api } from "../api/client";
import type { AgentEvent, ChartRequest, ChatTurn } from "../api/types";
import { useApp } from "../store";
import { VegaChart } from "../components/VegaChart";
import { Markdown } from "../components/Markdown";
import { ChevronRight, SendIcon, SparkleIcon } from "../components/icons";

interface Step {
  tool: string;
  thought?: string;
  sql?: string;
  summary?: string;
}
interface Chart {
  spec: Record<string, unknown>;
  chartRequest: ChartRequest | null;
}
interface Figure {
  image: string;
  caption?: string;
}
interface AssistantMsg {
  role: "assistant";
  steps: Step[];
  charts: Chart[];
  figures: Figure[];
  text: string;
  error?: string | null;
  done?: boolean;
}
type Msg = { role: "user"; text: string } | AssistantMsg;

const SUGGESTIONS = [
  "Summarize what's in my data.",
  "How many rows are in each category?",
  "Plot a histogram of a numeric column.",
  "Are the groups significantly different?",
];

const TOOL_LABEL: Record<string, string> = {
  run_sql: "Queried the data",
  make_chart: "Built a chart",
  run_stat: "Ran a statistical test",
};

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

  // PURE updater: never mutate existing state (React StrictMode double-invokes
  // updaters in dev — an in-place mutation would apply each event twice).
  function applyEvent(prev: AssistantMsg, e: AgentEvent): AssistantMsg {
    const m: AssistantMsg = {
      ...prev,
      steps: [...prev.steps],
      charts: [...prev.charts],
      figures: [...prev.figures],
    };
    if (e.type === "step") {
      m.steps.push({ tool: e.tool, thought: e.thought, sql: e.sql, summary: e.summary });
    } else if (e.type === "chart") {
      m.charts.push({ spec: e.spec, chartRequest: e.chart_request });
    } else if (e.type === "figure") {
      m.figures.push({ image: e.image, caption: e.caption });
    } else if (e.type === "token") {
      m.text += e.text;
    } else if (e.type === "final") {
      if (e.response) m.text = e.response;
      m.done = true;
    } else if (e.type === "error") {
      m.text = m.text || e.error;
      m.error = e.error;
      m.done = true;
    }
    return m;
  }

  function pushEvent(e: AgentEvent) {
    setMessages((msgs) => {
      const last = msgs[msgs.length - 1] as AssistantMsg;
      return [...msgs.slice(0, -1), applyEvent(last, e)];
    });
  }

  async function send(text: string) {
    text = text.trim();
    if (!text || streaming) return;
    const history: ChatTurn[] = messages
      .filter((m) => (m.role === "assistant" ? m.text : true))
      .map((m) => ({ role: m.role, content: m.role === "assistant" ? m.text : m.text }));
    setMessages((m) => [
      ...m,
      { role: "user", text },
      { role: "assistant", steps: [], charts: [], figures: [], text: "" },
    ]);
    setInput("");
    setStreaming(true);
    scrollDown();
    try {
      await api.agentChat(text, history, (e) => {
        pushEvent(e);
        scrollDown();
      });
    } catch (err) {
      pushEvent({ type: "error", error: String((err as Error).message) });
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
            <div className="text-[11px] text-slate-400">explores your data · runs locally</div>
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
          <div className="pt-4">
            <p className="text-sm text-slate-500">
              I read your data, run queries and stats, and build charts to answer your
              questions — and I never change your originals.
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
            <AssistantBubble key={i} msg={m} streaming={streaming} onOpenChart={openInVisualize} />
          ),
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
            placeholder="Ask about your data…"
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
  streaming,
  onOpenChart,
}: {
  msg: AssistantMsg;
  streaming: boolean;
  onOpenChart: (r: ChartRequest) => void;
}) {
  const [openSql, setOpenSql] = useState<number | null>(null);
  const working = streaming && !msg.done;
  return (
    <div className="animate-in rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 shadow-sm">
      {/* Thinking trace */}
      {msg.steps.length > 0 && (
        <div className="mb-2 space-y-1 border-l-2 border-slate-100 pl-2.5">
          {msg.steps.map((s, i) => (
            <div key={i} className="text-xs text-slate-500">
              <div className="flex items-center gap-1.5">
                <span className="text-slate-400">▸</span>
                <span className="font-medium text-slate-600">{TOOL_LABEL[s.tool] ?? s.tool}</span>
                {s.summary && <span className="text-slate-400">· {s.summary}</span>}
                {s.sql && (
                  <button
                    onClick={() => setOpenSql(openSql === i ? null : i)}
                    className="text-indigo-500 hover:underline"
                  >
                    SQL
                  </button>
                )}
              </div>
              {openSql === i && s.sql && (
                <pre className="mt-1 overflow-auto rounded bg-slate-900 p-2 text-[10px] text-slate-100">
                  {s.sql}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Answer (Markdown) */}
      <div>
        {msg.text ? <Markdown text={msg.text} /> : null}
        {working && (
          <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-indigo-400 align-middle" />
        )}
      </div>

      {/* Figures (matplotlib, for reports) */}
      {msg.figures.map((f, i) => (
        <figure key={`fig-${i}`} className="mt-2.5">
          <img
            src={f.image}
            alt={f.caption || "figure"}
            className="w-full rounded-lg border border-slate-200"
          />
          <figcaption className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
            <span>{f.caption}</span>
            <a href={f.image} download={`figure-${i + 1}.png`} className="font-medium text-indigo-600 hover:underline">
              Download PNG
            </a>
          </figcaption>
        </figure>
      ))}

      {/* Charts */}
      {msg.charts.map((c, i) => (
        <div key={i} className="mt-2.5">
          <div className="rounded-lg border border-slate-100 bg-slate-50 p-2">
            <VegaChart spec={c.spec} />
          </div>
          {c.chartRequest && (
            <button
              onClick={() => onOpenChart(c.chartRequest!)}
              className="mt-1.5 text-[11px] font-medium text-indigo-600 hover:underline"
            >
              Open in Visualize →
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
