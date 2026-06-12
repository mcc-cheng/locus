import type {
  AgentEvent,
  ChartRequest,
  ChatTurn,
  DepsHealth,
  Envelope,
  IngestResult,
  QueryResult,
  SandboxRunResult,
  SectionManifest,
  VisualizationResult,
  WarehouseSummary,
} from "./types";

let API_BASE = (import.meta.env.VITE_LOCUS_API as string | undefined) ?? "/api";

/** The Tauri shell calls this once it knows the sidecar's port. */
export function setApiBase(base: string): void {
  API_BASE = base.replace(/\/$/, "");
}

export function apiBase(): string {
  return API_BASE;
}

async function unwrap<T>(res: Response): Promise<T> {
  let env: Envelope<T>;
  try {
    env = (await res.json()) as Envelope<T>;
  } catch {
    throw new Error(`request failed (${res.status} ${res.statusText})`);
  }
  if (!env.ok || env.data === null) {
    throw new Error(env.error ?? `request failed (${res.status})`);
  }
  return env.data;
}

async function getJSON<T>(path: string): Promise<T> {
  return unwrap<T>(await fetch(`${API_BASE}${path}`));
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  return unwrap<T>(
    await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export const api = {
  health: () => getJSON<{ status: string }>("/health"),
  healthDeps: () => getJSON<DepsHealth>("/health/deps"),

  schema: () => getJSON<WarehouseSummary>("/schema"),
  schemaSection: (section: string) =>
    getJSON<SectionManifest>(`/schema/${encodeURIComponent(section)}`),

  query: (sql: string, page = 1, pageSize = 50, timeoutS?: number) =>
    postJSON<QueryResult>("/query", { sql, page, page_size: pageSize, timeout_s: timeoutS }),

  visualize: (req: ChartRequest) => postJSON<VisualizationResult>("/visualize", req),

  async ingest(
    file: File,
    engine: "deterministic" | "agentic",
    biopack?: Record<string, string>,
  ): Promise<IngestResult> {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("engine", engine);
    if (biopack && Object.keys(biopack).length) {
      form.append("biopack", JSON.stringify(biopack));
    }
    return unwrap<IngestResult>(
      await fetch(`${API_BASE}/ingest`, { method: "POST", body: form }),
    );
  },

  createSandbox: () => postJSON<{ sandbox_id: string }>("/sandboxes", {}),
  deleteSandbox: (id: string) =>
    fetch(`${API_BASE}/sandboxes/${encodeURIComponent(id)}`, { method: "DELETE" }).then(
      (r) => r.ok,
    ),
  runSandbox: (id: string, code: string, timeoutS?: number) =>
    postJSON<SandboxRunResult>(`/sandboxes/${encodeURIComponent(id)}/run`, {
      kind: "script",
      code,
      timeout_s: timeoutS,
    }),
  sandboxResults: (id: string) =>
    getJSON<SandboxRunResult>(`/sandboxes/${encodeURIComponent(id)}/results`),
  artifactUrl: (id: string, runId: string, name: string) =>
    `${API_BASE}/sandboxes/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(runId)}/${encodeURIComponent(name)}`,

  /** Stream the agent's NDJSON response, invoking `onEvent` per line. */
  async agentChat(
    message: string,
    history: ChatTurn[],
    onEvent: (e: AgentEvent) => void,
  ): Promise<void> {
    const res = await fetch(`${API_BASE}/agent/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });
    if (!res.body) throw new Error("no response stream");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (line) onEvent(JSON.parse(line) as AgentEvent);
      }
    }
    const tail = buffer.trim();
    if (tail) onEvent(JSON.parse(tail) as AgentEvent);
  },
};

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}
