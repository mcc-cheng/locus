import type {
  AgentEvent,
  ChartRequest,
  ChartSuggestion,
  ChatSummary,
  ChatTurn,
  MutationAction,
  SavedChat,
  SavedItem,
  DepsHealth,
  Envelope,
  IngestResult,
  QueryResult,
  RowPage,
  SandboxRunResult,
  SectionManifest,
  VisualizationResult,
  WarehouseSummary,
} from "./types";

let API_BASE = (import.meta.env.VITE_ANNULUS_API as string | undefined) ?? "/api";

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
  async deleteDataset(section: string): Promise<{ deleted: string }> {
    return unwrap<{ deleted: string }>(
      await fetch(`${API_BASE}/schema/${encodeURIComponent(section)}`, { method: "DELETE" }),
    );
  },

  // ---- editable rows ----
  readRows: (section: string, offset = 0, limit = 100) =>
    getJSON<RowPage>(
      `/datasets/${encodeURIComponent(section)}/rows?offset=${offset}&limit=${limit}`,
    ),
  addRow: (section: string, values: Record<string, string | null> = {}) =>
    postJSON<{ rid: number }>(`/datasets/${encodeURIComponent(section)}/rows`, { values }),
  addColumn: (section: string, name: string, formula?: string) =>
    postJSON<{ column: string; computed: boolean; rows?: number }>(
      `/datasets/${encodeURIComponent(section)}/columns`,
      { name, formula: formula ?? null },
    ),
  async patchCell(section: string, rid: number, column: string, value: string | null) {
    return unwrap<{ rid: number; column: string }>(
      await fetch(`${API_BASE}/datasets/${encodeURIComponent(section)}/rows/${rid}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ column, value }),
      }),
    );
  },
  async deleteRow(section: string, rid: number) {
    return unwrap<{ deleted: number }>(
      await fetch(`${API_BASE}/datasets/${encodeURIComponent(section)}/rows/${rid}`, {
        method: "DELETE",
      }),
    );
  },

  query: (sql: string, page = 1, pageSize = 50, timeoutS?: number) =>
    postJSON<QueryResult>("/query", { sql, page, page_size: pageSize, timeout_s: timeoutS }),

  visualize: (req: ChartRequest) => postJSON<VisualizationResult>("/visualize", req),
  chartSuggestions: (section: string, table = "raw") =>
    getJSON<ChartSuggestion[]>(
      `/visualize/suggestions?section=${encodeURIComponent(section)}&table=${encodeURIComponent(table)}`,
    ),

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

  // ---- library: saved items (charts + figures) ----
  listItems: () => getJSON<SavedItem[]>("/library/items"),
  saveItem: (item: {
    kind: "chart" | "figure";
    title?: string;
    folder?: string;
    section?: string | null;
    spec?: Record<string, unknown> | null;
    chart_request?: ChartRequest | null;
    image?: string | null;
    caption?: string | null;
  }) => postJSON<SavedItem>("/library/items", item),
  async moveItem(id: string, folder: string) {
    return unwrap<SavedItem>(
      await fetch(`${API_BASE}/library/items/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder }),
      }),
    );
  },
  async deleteItem(id: string) {
    return unwrap<{ deleted: string }>(
      await fetch(`${API_BASE}/library/items/${encodeURIComponent(id)}`, { method: "DELETE" }),
    );
  },

  // ---- library: folders (virtual tree) ----
  listFolders: () => getJSON<string[]>("/library/folders"),
  createFolder: (path: string) => postJSON<string[]>("/library/folders", { path }),
  async deleteFolder(path: string) {
    return unwrap<{ deleted: string }>(
      await fetch(`${API_BASE}/library/folders?path=${encodeURIComponent(path)}`, {
        method: "DELETE",
      }),
    );
  },
  listChats: () => getJSON<ChatSummary[]>("/library/chats"),
  getChat: (id: string) => getJSON<SavedChat>(`/library/chats/${encodeURIComponent(id)}`),
  async saveChat(chat: { id: string; title?: string; section?: string | null; messages: unknown[] }) {
    return unwrap<SavedChat>(
      await fetch(`${API_BASE}/library/chats/${encodeURIComponent(chat.id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(chat),
      }),
    );
  },
  async renameChat(id: string, title: string) {
    return unwrap<ChatSummary>(
      await fetch(`${API_BASE}/library/chats/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      }),
    );
  },
  async deleteChat(id: string) {
    return unwrap<{ deleted: string }>(
      await fetch(`${API_BASE}/library/chats/${encodeURIComponent(id)}`, { method: "DELETE" }),
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

  /** Stream the agent's NDJSON response, invoking `onEvent` per line. Pass
   * `confirm` (a previewed MutationAction) to execute a user-approved change. */
  async agentChat(
    message: string,
    history: ChatTurn[],
    onEvent: (e: AgentEvent) => void,
    opts?: { confirm?: MutationAction; section?: string | null },
  ): Promise<void> {
    const res = await fetch(`${API_BASE}/agent/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        history,
        confirm: opts?.confirm ?? null,
        section: opts?.section ?? null,
      }),
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
