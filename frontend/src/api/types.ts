// TypeScript mirrors of the backend's response models (the API contract).

export interface Envelope<T> {
  ok: boolean;
  data: T | null;
  error: string | null;
}

export interface ColumnInfo {
  name: string;
  ordinal: number;
  stored_type: string;
}

export interface TableInfo {
  name: string;
  row_count: number;
  columns: ColumnInfo[];
}

export interface SectionManifest {
  name: string;
  source_filename: string;
  upload_timestamp: string;
  tables: TableInfo[];
  sha256: string | null;
}

export interface DatasetSummary {
  name: string;
  source_filename: string;
  upload_timestamp: string;
  engine: string;
  row_count: number;
  table_count: number;
  source_bytes: number;
  sha256: string | null;
  status: string;
}

export interface WarehouseSummary {
  dataset_count: number;
  total_rows: number;
  total_source_bytes: number;
  datasets: DatasetSummary[];
}

export interface QueryResult {
  columns: string[];
  rows: unknown[][];
  page: number;
  page_size: number;
  has_more: boolean;
  execution_ms: number;
}

export type ChartType = "histogram" | "bar" | "heatmap" | "dose_response" | "scatter";
export type Aggregate = "count" | "sum" | "avg" | "min" | "max";

export interface ChartRequest {
  type: ChartType;
  section: string;
  table: string;
  x?: string | null;
  y?: string | null;
  color?: string | null;
  row?: string | null;
  col?: string | null;
  value?: string | null;
  aggregate?: Aggregate;
  bins?: number;
}

export interface VisualizationResult {
  spec: Record<string, unknown>;
  data: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  execution_ms: number;
}

export interface ChartSuggestion {
  title: string;
  description: string;
  request: ChartRequest;
}

export interface IngestResult {
  section: string;
  engine: string;
  qc_passed: boolean;
  grain: string;
  tables: { name: string; role: string; columns: string[] }[];
  foreign_keys: number;
  row_count: number;
}

export interface DataRow {
  rid: number;
  cells: (string | null)[];
}
export interface RowPage {
  columns: string[];
  rows: DataRow[];
  total: number;
  offset: number;
}

export interface SandboxRunResult {
  sandbox_id: string;
  run_id: string;
  kind: "script" | "notebook";
  ok: boolean;
  exit_code: number;
  timed_out: boolean;
  execution_ms: number;
  stdout: string;
  stderr: string;
  artifacts: string[];
}

export interface DepsHealth {
  ollama: { status: "ready" | "unavailable"; detail?: string };
}

// Streaming agent events (NDJSON).
export type AgentEvent =
  | { type: "step"; tool: "run_sql" | "make_chart" | "run_stat"; thought?: string; sql?: string; summary?: string }
  | { type: "chart"; spec: Record<string, unknown>; chart_request: ChartRequest | null }
  | { type: "figure"; image: string; caption?: string }
  | { type: "token"; text: string }
  | { type: "final"; response: string }
  | { type: "error"; error: string };

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}
