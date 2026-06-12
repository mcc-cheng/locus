import { useEffect, useState } from "react";
import type { Result } from "vega-embed";
import { api } from "../api/client";
import type {
  ChartRequest,
  ChartType,
  DatasetSummary,
  SectionManifest,
  VisualizationResult,
} from "../api/types";
import { useApp } from "../store";
import { VegaChart } from "../components/VegaChart";
import { Badge, Button, Card, ErrorBox, PageTitle, Spinner } from "../components/ui";

const CHART_TYPES: { id: ChartType; label: string; roles: string[] }[] = [
  { id: "histogram", label: "Histogram", roles: ["x"] },
  { id: "bar", label: "Bar", roles: ["x", "y"] },
  { id: "heatmap", label: "Heatmap", roles: ["row", "col", "value"] },
  { id: "dose_response", label: "Dose-Response", roles: ["x", "y", "color"] },
  { id: "scatter", label: "Scatter", roles: ["x", "y", "color"] },
];

const OPTIONAL: Record<ChartType, string[]> = {
  histogram: [],
  bar: ["y"],
  heatmap: [],
  dose_response: ["color"],
  scatter: ["color"],
};

export function Visualize() {
  const { selectedSection, consumeVizHandoff, schemaVersion } = useApp();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [section, setSection] = useState<string | null>(selectedSection);
  const [manifest, setManifest] = useState<SectionManifest | null>(null);
  const [table, setTable] = useState("raw");
  const [chartType, setChartType] = useState<ChartType>("histogram");
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [out, setOut] = useState<VisualizationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showSpec, setShowSpec] = useState(false);
  const [view, setView] = useState<Result | null>(null);

  useEffect(() => {
    api.schema().then((s) => setDatasets(s.datasets)).catch((e) => setError(String(e.message)));
  }, [schemaVersion]);

  // Preload from an agent hand-off.
  useEffect(() => {
    const h = consumeVizHandoff();
    if (h) {
      setSection(h.section);
      setTable(h.table);
      setChartType(h.type);
      const r: Record<string, string> = {};
      for (const k of ["x", "y", "color", "row", "col", "value"] as const) {
        const v = h[k];
        if (v) r[k] = v;
      }
      setRoles(r);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!section) return;
    api.schemaSection(section).then(setManifest).catch((e) => setError(String(e.message)));
  }, [section]);

  const columns = manifest?.tables.find((t) => t.name === table)?.columns ?? [];
  const spec = CHART_TYPES.find((c) => c.id === chartType)!;

  async function generate() {
    if (!section) return;
    setBusy(true);
    setError(null);
    setOut(null);
    const req: ChartRequest = { type: chartType, section, table, ...roles };
    try {
      setOut(await api.visualize(req));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function save(format: "png" | "svg") {
    if (!view) return;
    const url =
      format === "svg"
        ? "data:image/svg+xml;charset=utf-8," + encodeURIComponent(await view.view.toSVG())
        : await view.view.toImageURL("png");
    const a = document.createElement("a");
    a.href = url;
    a.download = `chart.${format}`;
    a.click();
  }

  return (
    <div>
      <PageTitle title="Visualize" subtitle="Charts are aggregated on the server — never the full table." />

      <Card className="mb-5">
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
            value={section ?? ""}
            onChange={(e) => {
              setSection(e.target.value);
              setTable("raw");
              setOut(null);
            }}
          >
            <option value="">Select dataset…</option>
            {datasets.map((d) => (
              <option key={d.name} value={d.name}>
                {d.source_filename}
              </option>
            ))}
          </select>
          {manifest && (
            <select
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              value={table}
              onChange={(e) => {
                setTable(e.target.value);
                setOut(null);
              }}
            >
              {manifest.tables.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {CHART_TYPES.map((c) => (
            <button
              key={c.id}
              onClick={() => {
                setChartType(c.id);
                setRoles({});
                setOut(null);
              }}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                chartType === c.id
                  ? "bg-indigo-600 text-white"
                  : "border border-slate-300 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>

        {/* Column role selectors */}
        <div className="mt-4 flex flex-wrap gap-3">
          {spec.roles.map((role) => (
            <label key={role} className="text-xs text-slate-600">
              <span className="mr-1 capitalize">
                {role}
                {OPTIONAL[chartType].includes(role) ? " (optional)" : ""}
              </span>
              <select
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                value={roles[role] ?? ""}
                onChange={(e) => setRoles((r) => ({ ...r, [role]: e.target.value }))}
              >
                <option value="">—</option>
                {columns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {chartType === "bar" && (
            <label className="text-xs text-slate-600">
              <span className="mr-1">aggregate</span>
              <select
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                value={roles.aggregate ?? "count"}
                onChange={(e) => setRoles((r) => ({ ...r, aggregate: e.target.value }))}
              >
                {["count", "sum", "avg", "min", "max"].map((a) => (
                  <option key={a}>{a}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        <div className="mt-4">
          <Button onClick={generate} disabled={!section || busy}>
            {busy ? "Generating…" : "Generate"}
          </Button>
        </div>
      </Card>

      {error && <ErrorBox message={error} />}
      {busy && <Spinner label="Aggregating…" />}

      {out && (
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Badge tone="indigo">{out.row_count} points</Badge>
              {out.truncated && <Badge tone="amber">truncated to 10k</Badge>}
              <span>{out.execution_ms.toFixed(0)} ms</span>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => save("png")}>
                Save PNG
              </Button>
              <Button variant="secondary" onClick={() => save("svg")}>
                Save SVG
              </Button>
            </div>
          </div>
          <VegaChart spec={out.spec} onView={setView} />
          <button
            onClick={() => setShowSpec((s) => !s)}
            className="mt-3 text-xs font-medium text-indigo-600 hover:underline"
          >
            {showSpec ? "Hide spec" : "View spec"}
          </button>
          {showSpec && (
            <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
              {JSON.stringify(out.spec, null, 2)}
            </pre>
          )}
        </Card>
      )}
    </div>
  );
}
