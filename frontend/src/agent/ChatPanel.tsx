import { useRef, useState } from "react";
import { api } from "../api/client";
import type { ChartRequest, ChatTurn } from "../api/types";
import { useApp } from "../store";
import { VegaChart } from "../components/VegaChart";

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

export function ChatPanel({ onClose }: { onClose: () => void }) {
  const { openInVisualize } = useApp();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  function scrollDown() {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
    });
  }

  async function send() {
    const text = input.trim();
    if (!text || streaming) return;
    const history: ChatTurn[] = messages.map((m) => ({
      role: m.role,
      content: m.text,
    }));
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    setStreaming(true);

    const draft: AssistantMsg = { role: "assistant", text: "" };
    setMessages((m) => [...m, draft]);
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
        <span className="text-sm font-semibold text-slate-700">Analyst</span>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
          ✕
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-auto p-4">
        {messages.length === 0 && (
          <p className="text-sm text-slate-400">
            Ask about your data — e.g. “How many rows are in each dataset?” or “Plot dose vs
            response.” I have read-only access and never change your data.
          </p>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="ml-8 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white">
              {m.text}
            </div>
          ) : (
            <AssistantBubble key={i} msg={m} onOpenChart={openInVisualize} />
          ),
        )}
        {streaming && <div className="text-xs text-slate-400">analyst is thinking…</div>}
      </div>

      <div className="border-t border-slate-200 p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            placeholder="Ask the analyst…"
            className="flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            onClick={send}
            disabled={streaming || !input.trim()}
            className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Send
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
    <div className="mr-8 rounded-lg bg-white px-3 py-2 text-sm text-slate-800 shadow-sm">
      <div className="whitespace-pre-wrap">{msg.text || "…"}</div>

      {(msg.sql || msg.spec) && (
        <button
          onClick={() => setShowCode((s) => !s)}
          className="mt-2 text-xs font-medium text-indigo-600 hover:underline"
        >
          {showCode ? "Hide" : msg.sql ? "SQL used" : "Chart spec used"}
        </button>
      )}
      {showCode && (
        <pre className="mt-1 max-h-48 overflow-auto rounded bg-slate-900 p-2 text-xs text-slate-100">
          {msg.sql ?? JSON.stringify(msg.spec, null, 2)}
        </pre>
      )}

      {msg.spec && (
        <div className="mt-2">
          <VegaChart spec={msg.spec} />
          {msg.chartRequest && (
            <button
              onClick={() => onOpenChart(msg.chartRequest!)}
              className="mt-1 text-xs font-medium text-indigo-600 hover:underline"
            >
              Open in Visualize →
            </button>
          )}
        </div>
      )}
    </div>
  );
}
