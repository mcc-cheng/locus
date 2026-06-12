import { useEffect, useState } from "react";
import type { Result } from "vega-embed";
import { api } from "../api/client";
import type {
  Aggregate,
  ChartRequest,
  ChartType,
  DatasetSummary,
  SectionManifest,
  VisualizationResult,
} from "../api/types";
import { useApp } from "../store";
import { VegaChart } from "../components/VegaChart";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  PageTitle,
  Select,
  Spinner,
} from "../components/ui";
import { ChartIcon, DownloadIcon } from "../components/icons";

type Role = "x" | "y" | "color" | "row" | "col" | "value";

const CHARTS: { id: ChartType; label: string; roles: Role[]; optional: Role[] }[] = [
  { id: "histogram", label: "Histogram", roles: ["x"], optional: [] },
  { id: "bar", label: "Bar", roles: ["x", "y"], optional: ["y"] },
  { id: "heatmap", label: "Heatmap", roles: ["row", "col", "value"], optional: [] },
  { id: "dose_response", label: "Dose-Response", roles: ["x", "y", "color"], optional: ["color"] },
  { id: "scatter", label: "Scatter", roles: ["x", "y", "color"], optional: ["color"] },
];

const ROLE_LABEL: Record<Role, string> = {
  x: "X axis",
  y: "Y axis",
  color: "Color / series",
  row: "Row",
  col: "Column",
  value: "Value",
};

export function Visualize() {
  const { selectedSection, consumeVizHandoff, schemaVersion } = useApp();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [section, setSection] = useState<string | null>(selectedSection);
  const [manifest, setManifest] = useState<SectionManifest | null>(null);
  const [table, setTable] = useState("raw");
  const [chartType, setChartType] = useState<ChartType>("histogram");
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [aggregate, setAggregate] = useState<Aggregate>("count");
  const [out, setOut] = useState<VisualizationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showSpec, setShowSpec] = useState(false);
  const [view, setView] = useState<Result | null>(null);

  useEffect(() => {
    api.schema().then((s) => setDatasets(s.datasets)).catch((e) => setError(String(e.message)));
  }, [schemaVersion]);

  useEffect(() => {
    const h = consumeVizHandoff();
    if (h) {
      setSection(h.section);
      setTable(h.table);
      setChartType(h.type);
      if (h.aggregate) setAggregate(h.aggregate);
      const r: Record<string, string> = {};
      (["x", "y", "color", "row", "col", "value"] as Role[]).forEach((k) => {
        if (h[k]) r[k] = h[k] as string;
      });
      setRoles(r);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!section) return;
    api.schemaSection(section).then(setManifest).catch((e) => setError(String(e.message)));
  }, [section]);

  const columns = manifest?.tables.find((t) => t.name === table)?.columns ?? [];
  const chart = CHARTS.find((c) => c.id === chartType)!;
  const missing = chart.roles.filter((r) => !chart.optional.includes(r) && !roles[r]);
  const canGenerate = !!section && missing.length === 0;

  async function generate() {
    if (!section) return;
    setBusy(true);
    setError(null);
    setOut(null);
    // Only send roles that were actually selected (no empty strings).
    const req: ChartRequest = { type: chartType, section, table };
    for (const r of chart.roles) if (roles[r]) (req as unknown as Record<string, unknown>)[r] = roles[r];
    if (chartType === "bar") req.aggregate = aggregate;
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
        : await view.view.toImageURL("png", 2);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chart.${format}`;
    a.click();
  }

  return (
    <div>
      <PageTitle
        title="Visualize"
        subtitle="Charts are aggregated on the server — your full table never leaves the engine."
      />

      <Card className="mb-5">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Dataset">
            <Select
              value={section ?? ""}
              onChange={(v) => {
                setSection(v);
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
            </Select>
          </Field>
          {manifest && (
            <Field label="Table">
              <Select
                value={table}
                onChange={(v) => {
                  setTable(v);
                  setOut(null);
                }}
              >
                {manifest.tables.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {CHARTS.map((c) => (
            <button
              key={c.id}
              onClick={() => {
                setChartType(c.id);
                setRoles({});
                setOut(null);
              }}
              className={`rounded-lg px-3.5 py-1.5 text-sm font-medium transition ${
                chartType === c.id
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "border border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>

        {section && (
          <div className="mt-5 flex flex-wrap items-end gap-3">
            {chart.roles.map((role) => (
              <Field key={role} label={ROLE_LABEL[role] + (chart.optional.includes(role) ? " (optional)" : "")}>
                <Select value={roles[role] ?? ""} onChange={(v) => setRoles((r) => ({ ...r, [role]: v }))}>
                  <option value="">—</option>
                  {columns.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
            ))}
            {chartType === "bar" && (
              <Field label="Aggregate">
                <Select value={aggregate} onChange={(v) => setAggregate(v as Aggregate)}>
                  {(["count", "sum", "avg", "min", "max"] as Aggregate[]).map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <Button onClick={generate} disabled={!canGenerate || busy}>
              {busy ? "Generating…" : "Generate chart"}
            </Button>
          </div>
        )}
        {section && missing.length > 0 && (
          <p className="mt-2 text-xs text-slate-400">
            Pick a column for: {missing.map((r) => ROLE_LABEL[r]).join(", ")}
          </p>
        )}
      </Card>

      {error && <ErrorBox message={error} />}
      {busy && (
        <div className="py-10">
          <Spinner label="Aggregating on the server…" />
        </div>
      )}

      {!out && !busy && !error && (
        <EmptyState
          icon={<ChartIcon className="h-10 w-10" />}
          title="No chart yet"
          body="Choose a dataset, a chart type, and the columns to plot, then press Generate."
        />
      )}

      {out && (
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Badge tone="indigo">{out.row_count.toLocaleString()} points</Badge>
              {out.truncated && <Badge tone="amber">capped at 10k</Badge>}
              <span className="tabular">{out.execution_ms.toFixed(0)} ms</span>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={() => save("png")}>
                <DownloadIcon className="h-4 w-4" /> PNG
              </Button>
              <Button variant="secondary" size="sm" onClick={() => save("svg")}>
                <DownloadIcon className="h-4 w-4" /> SVG
              </Button>
            </div>
          </div>
          <div className="overflow-x-auto rounded-xl border border-slate-100 bg-slate-50/50 p-4">
            <VegaChart spec={out.spec} onView={setView} />
          </div>
          <button
            onClick={() => setShowSpec((s) => !s)}
            className="mt-3 text-xs font-medium text-indigo-600 hover:underline"
          >
            {showSpec ? "Hide chart spec" : "View chart spec"}
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
