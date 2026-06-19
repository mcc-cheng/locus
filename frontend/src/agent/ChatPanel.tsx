import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AgentEvent, ChartRequest, ChatTurn, DatasetSummary, MutationAction } from "../api/types";
import { useApp } from "../store";
import { VegaChart } from "../components/VegaChart";
import { Markdown } from "../components/Markdown";
import { ChevronRight, DataIcon, SendIcon, SparkleIcon } from "../components/icons";

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
interface Ask {
  question: string;
  options: string[];
}
interface Confirm {
  summary: string;
  detail: string;
  note?: string;
  affected: number | null;
  action: MutationAction;
  options: string[];
}
interface AssistantMsg {
  role: "assistant";
  steps: Step[];
  charts: Chart[];
  figures: Figure[];
  ask?: Ask;
  confirm?: Confirm;
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

// Friendly dataset name: the uploaded filename without its extension.
function datasetLabel(d: DatasetSummary | null): string {
  if (!d) return "—";
  return d.source_filename.replace(/\.[^.]+$/, "") || d.name;
}

const TOOL_LABEL: Record<string, string> = {
  run_sql: "Queried the data",
  make_chart: "Built a chart",
  run_stat: "Ran a statistical test",
  propose_change: "Proposed a data change",
  blocked_mutation: "Declined to change data",
};

export function ChatPanel({ onCollapse }: { onCollapse: () => void }) {
  const {
    openInVisualize,
    refreshSchema,
    selectedSection,
    setSelectedSection,
    schemaVersion,
    openChatId,
    chatNonce,
    newChat,
    refreshChats,
  } = useApp();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<string>(crypto.randomUUID()); // id of the current chat

  // Load the chat the sidebar asked for (or reset to a fresh thread). Driven by
  // chatNonce so clicking the same chat / "New" again still re-triggers.
  useEffect(() => {
    if (openChatId == null) {
      sessionRef.current = crypto.randomUUID();
      setMessages([]);
      setInput("");
      return;
    }
    let cancelled = false;
    api
      .getChat(openChatId)
      .then((chat) => {
        if (cancelled) return;
        sessionRef.current = chat.id;
        setMessages((chat.messages as Msg[]) ?? []);
        if (chat.section) {
          setActiveSection(chat.section);
          setSelectedSection(chat.section);
        }
        setInput("");
        scrollDown();
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatNonce]);

  // Persist the conversation after each turn settles (streaming turns off).
  useEffect(() => {
    if (streaming) return;
    const firstUser = messages.find((m) => m.role === "user") as { text: string } | undefined;
    if (!firstUser) return; // nothing meaningful to save yet
    api
      .saveChat({
        id: sessionRef.current,
        title: firstUser.text.slice(0, 80),
        section: activeSection,
        messages,
      })
      .then(() => refreshChats())
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming]);

  // Keep the dataset list fresh; pick a sensible active dataset (the one the user
  // has selected elsewhere, else the first) whenever the set of datasets changes.
  useEffect(() => {
    let cancelled = false;
    api
      .schema()
      .then((s) => {
        if (cancelled) return;
        setDatasets(s.datasets);
        setActiveSection((cur) => {
          const names = s.datasets.map((d) => d.name);
          if (cur && names.includes(cur)) return cur;
          if (selectedSection && names.includes(selectedSection)) return selectedSection;
          return s.datasets[0]?.name ?? null;
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [schemaVersion, selectedSection]);

  const activeDataset = datasets.find((d) => d.name === activeSection) ?? null;

  // Switch which dataset the analyst works in. Starts a fresh conversation so the
  // thread clearly belongs to one dataset, and syncs the app's selection.
  function switchDataset(section: string) {
    setPickerOpen(false);
    if (section === activeSection) return;
    setActiveSection(section);
    setSelectedSection(section);
    newChat(); // fresh thread for the new dataset (the load effect clears messages)
  }

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
    } else if (e.type === "ask") {
      m.ask = { question: e.question, options: e.options };
      m.done = true;
    } else if (e.type === "confirm") {
      m.confirm = {
        summary: e.summary,
        detail: e.detail,
        note: e.note,
        affected: e.affected,
        action: e.action,
        options: e.options,
      };
      m.done = true;
    } else if (e.type === "mutation") {
      m.text = m.text || e.summary;
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
    if (!text || streaming || !activeSection) return;
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
      await api.agentChat(
        text,
        history,
        (e) => {
          pushEvent(e);
          scrollDown();
        },
        { section: activeSection },
      );
    } catch (err) {
      pushEvent({ type: "error", error: String((err as Error).message) });
    } finally {
      setStreaming(false);
      scrollDown();
    }
  }

  // Execute a user-approved data change. Runs the EXACT previewed action
  // server-side (no model), then refreshes so the Data tab reflects the change.
  async function runConfirm(action: MutationAction, label: string) {
    if (streaming) return;
    setMessages((m) => [
      ...m,
      { role: "user", text: label },
      { role: "assistant", steps: [], charts: [], figures: [], text: "" },
    ]);
    setStreaming(true);
    scrollDown();
    try {
      await api.agentChat(
        "",
        [],
        (e) => {
          if (e.type === "mutation") refreshSchema();
          pushEvent(e);
          scrollDown();
        },
        { confirm: action, section: activeSection },
      );
    } catch (err) {
      pushEvent({ type: "error", error: String((err as Error).message) });
    } finally {
      setStreaming(false);
      scrollDown();
    }
  }

  function cancelConfirm() {
    setMessages((m) => [
      ...m,
      { role: "user", text: "Cancel" },
      {
        role: "assistant",
        steps: [],
        charts: [],
        figures: [],
        text: "No changes were made.",
        done: true,
      },
    ]);
    scrollDown();
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

      {/* Active-dataset indicator + switcher */}
      <div className="relative border-b border-slate-200 bg-slate-50/70 px-3 py-2">
        {datasets.length === 0 ? (
          <div className="px-1.5 py-1 text-[11px] text-slate-400">
            No datasets yet — upload one to begin.
          </div>
        ) : (
          <button
            onClick={() => setPickerOpen((o) => !o)}
            disabled={datasets.length <= 1}
            className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left transition enabled:hover:bg-slate-100 disabled:cursor-default"
          >
            <DataIcon className="h-4 w-4 shrink-0 text-indigo-500" />
            <span className="shrink-0 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              Working in
            </span>
            <span className="flex-1 truncate text-sm font-semibold text-slate-800">
              {datasetLabel(activeDataset)}
            </span>
            {datasets.length > 1 && (
              <ChevronRight
                className={`h-4 w-4 shrink-0 text-slate-400 transition ${pickerOpen ? "rotate-90" : ""}`}
              />
            )}
          </button>
        )}
        {pickerOpen && datasets.length > 1 && (
          <div className="absolute left-2 right-2 z-20 mt-1 max-h-64 overflow-auto rounded-xl border border-slate-200 bg-white p-1 shadow-lg">
            {datasets.map((d) => (
              <button
                key={d.name}
                onClick={() => switchDataset(d.name)}
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition hover:bg-slate-50 ${
                  d.name === activeSection ? "font-medium text-indigo-700" : "text-slate-700"
                }`}
              >
                <span className="flex-1 truncate">{datasetLabel(d)}</span>
                <span className="shrink-0 text-[11px] text-slate-400">
                  {d.row_count.toLocaleString()} rows
                </span>
                {d.name === activeSection && <span className="shrink-0 text-indigo-600">✓</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-auto px-4 py-4">
        {messages.length === 0 && (
          <div className="pt-4">
            <p className="text-sm text-slate-500">
              I read your data, run queries and stats, and build charts to answer your
              questions. I can also edit, delete, or restructure data when you ask —
              but only after you confirm, and your original upload is always preserved.
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
            <AssistantBubble
              key={i}
              msg={m}
              streaming={streaming}
              isLast={i === messages.length - 1}
              onOpenChart={openInVisualize}
              onAnswer={send}
              onConfirm={runConfirm}
              onCancel={cancelConfirm}
            />
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
            disabled={!activeSection}
            placeholder={
              activeSection ? `Ask about ${datasetLabel(activeDataset)}…` : "Upload a dataset to begin…"
            }
            className="max-h-32 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none disabled:cursor-not-allowed"
          />
          <button
            onClick={() => send(input)}
            disabled={streaming || !input.trim() || !activeSection}
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
  isLast,
  onOpenChart,
  onAnswer,
  onConfirm,
  onCancel,
}: {
  msg: AssistantMsg;
  streaming: boolean;
  isLast: boolean;
  onOpenChart: (r: ChartRequest) => void;
  onAnswer: (option: string) => void;
  onConfirm: (action: MutationAction, label: string) => void;
  onCancel: () => void;
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

      {/* Human-in-the-loop question with clickable options */}
      {msg.ask && (
        <div className="mt-1">
          <div className="text-sm font-medium text-slate-800">{msg.ask.question}</div>
          <div className="mt-2 flex flex-col gap-1.5">
            {msg.ask.options.map((opt) => (
              <button
                key={opt}
                disabled={!isLast || streaming}
                onClick={() => onAnswer(opt)}
                className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-left text-sm font-medium text-indigo-700 transition hover:border-indigo-300 hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {opt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Proposed data change — requires an explicit confirm click */}
      {msg.confirm &&
        (() => {
          const destructive = msg.confirm.action.op === "delete";
          const confirmLabel = msg.confirm.options[0] ?? "Confirm";
          const disabled = !isLast || streaming;
          return (
            <div className="mt-1.5 rounded-lg border border-amber-200 bg-amber-50/70 p-3">
              <div className="text-sm font-medium text-slate-800">{msg.confirm.summary}</div>
              {msg.confirm.note && (
                <div className="mt-1 text-[11px] text-slate-500">{msg.confirm.note}</div>
              )}
              <pre className="mt-2 overflow-auto rounded bg-slate-900 p-2 text-[10px] text-slate-100">
                {msg.confirm.detail}
              </pre>
              <div className="mt-2.5 flex gap-2">
                <button
                  disabled={disabled}
                  onClick={() => onConfirm(msg.confirm!.action, confirmLabel)}
                  className={
                    "rounded-lg px-3 py-1.5 text-sm font-medium text-white transition disabled:cursor-not-allowed disabled:opacity-50 " +
                    (destructive
                      ? "bg-red-600 hover:bg-red-500"
                      : "bg-indigo-600 hover:bg-indigo-500")
                  }
                >
                  {confirmLabel}
                </button>
                <button
                  disabled={disabled}
                  onClick={onCancel}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          );
        })()}

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
          <ChartActions chart={c} onOpenChart={onOpenChart} />
        </div>
      ))}
    </div>
  );
}

// Save / open actions under an analyst-made chart.
function ChartActions({
  chart,
  onOpenChart,
}: {
  chart: Chart;
  onOpenChart: (r: ChartRequest) => void;
}) {
  const [saved, setSaved] = useState(false);
  async function save() {
    try {
      await api.saveChart({
        title: "Analyst chart",
        section: chart.chartRequest?.section ?? null,
        spec: chart.spec,
        chart_request: chart.chartRequest,
      });
      setSaved(true);
    } catch {
      /* ignore — non-critical */
    }
  }
  return (
    <div className="mt-1.5 flex items-center gap-3">
      <button
        onClick={save}
        disabled={saved}
        className="text-[11px] font-medium text-indigo-600 hover:underline disabled:text-emerald-600 disabled:no-underline"
      >
        {saved ? "Saved ✓" : "Save"}
      </button>
      {chart.chartRequest && (
        <button
          onClick={() => onOpenChart(chart.chartRequest!)}
          className="text-[11px] font-medium text-indigo-600 hover:underline"
        >
          Open in Visualize →
        </button>
      )}
    </div>
  );
}
