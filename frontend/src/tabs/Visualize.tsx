import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  Aggregate,
  ChartRequest,
  ChartSuggestion,
  ChartType,
  DatasetSummary,
  SectionManifest,
  VisualizationResult,
} from "../api/types";
import { useApp } from "../store";
import { VegaChart, type ChartView } from "../components/VegaChart";
import { Badge, Button, Card, ErrorBox, Field, PageTitle, Select, Spinner } from "../components/ui";
import { BookmarkIcon, DownloadIcon } from "../components/icons";
import { SaveToLibraryDialog } from "../components/SaveToLibraryDialog";

type Role = "x" | "y" | "color" | "row" | "col" | "value";

const CHARTS: { id: ChartType; label: string; roles: Role[]; optional: Role[] }[] = [
  { id: "histogram", label: "Histogram", roles: ["x"], optional: [] },
  { id: "bar", label: "Bar", roles: ["x", "y"], optional: ["y"] },
  { id: "heatmap", label: "Heatmap", roles: ["row", "col", "value"], optional: [] },
  { id: "dose_response", label: "Dose-Response", roles: ["x", "y", "color"], optional: ["color"] },
  { id: "scatter", label: "Scatter", roles: ["x", "y", "color"], optional: ["color"] },
  { id: "box", label: "Box plot", roles: ["x", "y"], optional: [] },
  { id: "line", label: "Line", roles: ["x", "y", "color"], optional: ["color"] },
  { id: "grouped_bar", label: "Grouped bar", roles: ["x", "color", "y"], optional: ["y"] },
  { id: "correlation_matrix", label: "Correlations", roles: [], optional: [] },
];
const ROLE_LABEL: Record<Role, string> = {
  x: "X axis", y: "Y axis", color: "Color / series", row: "Row", col: "Column", value: "Value",
};
const CHART_GLYPH: Record<ChartType, string> = {
  histogram: "▤", bar: "▦", heatmap: "▩", dose_response: "↗", scatter: "⁛",
  box: "❑", line: "📈", grouped_bar: "▥", correlation_matrix: "▦",
};

export function Visualize() {
  const { selectedSection, consumeVizHandoff, schemaVersion } = useApp();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [section, setSection] = useState<string | null>(selectedSection);
  const [manifest, setManifest] = useState<SectionManifest | null>(null);
  const [table, setTable] = useState("raw");
  const [suggestions, setSuggestions] = useState<ChartSuggestion[]>([]);
  const [loadingSug, setLoadingSug] = useState(false);

  const [chartType, setChartType] = useState<ChartType>("histogram");
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [aggregate, setAggregate] = useState<Aggregate>("count");
  const [showCustom, setShowCustom] = useState(false);

  const [out, setOut] = useState<VisualizationResult | null>(null);
  const [activeTitle, setActiveTitle] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showSpec, setShowSpec] = useState(false);
  const [view, setView] = useState<ChartView | null>(null);
  const [lastReq, setLastReq] = useState<ChartRequest | null>(null);
  const [saved, setSaved] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);

  useEffect(() => {
    api.schema().then((s) => setDatasets(s.datasets)).catch((e) => setError(String(e.message)));
  }, [schemaVersion]);

  useEffect(() => {
    const h = consumeVizHandoff();
    if (h) {
      setSection(h.section);
      setTable(h.table);
      runRequest(h, "Chart from analyst");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!section) return;
    api.schemaSection(section).then(setManifest).catch((e) => setError(String(e.message)));
    setLoadingSug(true);
    setSuggestions([]);
    api
      .chartSuggestions(section, table)
      .then(setSuggestions)
      .catch(() => setSuggestions([]))
      .finally(() => setLoadingSug(false));
  }, [section, table]);

  const columns = manifest?.tables.find((t) => t.name === table)?.columns ?? [];
  const chart = CHARTS.find((c) => c.id === chartType)!;
  const missing = chart.roles.filter((r) => !chart.optional.includes(r) && !roles[r]);

  async function runRequest(req: ChartRequest, title: string) {
    setBusy(true);
    setError(null);
    setOut(null);
    setActiveTitle(title);
    setLastReq(req);
    setSaved(false);
    try {
      setOut(await api.visualize(req));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  function applySuggestion(s: ChartSuggestion) {
    const r = s.request;
    // sync the custom builder so the user can tweak it
    setChartType(r.type);
    setAggregate(r.aggregate ?? "count");
    const rr: Record<string, string> = {};
    (["x", "y", "color", "row", "col", "value"] as Role[]).forEach((k) => {
      if (r[k]) rr[k] = r[k] as string;
    });
    setRoles(rr);
    runRequest(r, s.title);
  }

  function generateCustom() {
    if (!section) return;
    const req: ChartRequest = { type: chartType, section, table };
    for (const r of chart.roles) if (roles[r]) (req as unknown as Record<string, unknown>)[r] = roles[r];
    if (chartType === "bar") req.aggregate = aggregate;
    runRequest(req, "Custom chart");
  }

  async function save(format: "png" | "svg") {
    if (!view) return;
    const url =
      format === "svg"
        ? "data:image/svg+xml;charset=utf-8," + encodeURIComponent(await view.toSVG())
        : await view.toImageURL("png", 2);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chart.${format}`;
    a.click();
  }

  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle
        title="Visualize"
        subtitle="Suggested charts based on your data. Charts are aggregated on the server."
      />

      <Card className="mb-5">
        <div className="grid max-w-xl grid-cols-2 gap-3">
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

        {/* Suggested charts */}
        {section && (
          <div className="mt-5">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Suggested charts
            </div>
            {loadingSug ? (
              <Spinner label="Analyzing your columns…" />
            ) : suggestions.length === 0 ? (
              <p className="text-sm text-slate-400">No suggestions for this table.</p>
            ) : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                {suggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => applySuggestion(s)}
                    className={`group rounded-xl border p-3 text-left transition ${
                      activeTitle === s.title
                        ? "border-indigo-400 bg-indigo-50"
                        : "border-slate-200 hover:border-indigo-300 hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-lg leading-none text-indigo-500">
                        {CHART_GLYPH[s.request.type]}
                      </span>
                      <span className="text-[10px] uppercase tracking-wide text-slate-400">
                        {s.description}
                      </span>
                    </div>
                    <div className="mt-1.5 text-sm font-medium text-slate-700">{s.title}</div>
                    {s.rationale && (
                      <div className="mt-1 text-xs leading-snug text-slate-500">{s.rationale}</div>
                    )}
                  </button>
                ))}
              </div>
            )}

            <button
              onClick={() => setShowCustom((s) => !s)}
              className="mt-4 text-xs font-medium text-indigo-600 hover:underline"
            >
              {showCustom ? "Hide custom builder" : "Build a custom chart →"}
            </button>
          </div>
        )}

        {/* Custom builder */}
        {section && showCustom && (
          <div className="mt-4 rounded-xl border border-slate-100 bg-slate-50/60 p-4">
            <div className="flex flex-wrap gap-2">
              {CHARTS.map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    setChartType(c.id);
                    setRoles({});
                  }}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    chartType === c.id
                      ? "bg-indigo-600 text-white"
                      : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {c.label}
                </button>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              {chart.roles.map((role) => (
                <Field
                  key={role}
                  label={ROLE_LABEL[role] + (chart.optional.includes(role) ? " (opt.)" : "")}
                >
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
              {(chartType === "bar" || chartType === "grouped_bar") && (
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
              <Button onClick={generateCustom} disabled={!!missing.length || busy}>
                Generate
              </Button>
            </div>
            {missing.length > 0 && (
              <p className="mt-2 text-xs text-slate-400">
                Pick: {missing.map((r) => ROLE_LABEL[r]).join(", ")}
              </p>
            )}
          </div>
        )}
      </Card>

      {error && <ErrorBox message={error} />}
      {busy && (
        <div className="py-10">
          <Spinner label="Aggregating on the server…" />
        </div>
      )}

      {!out && !busy && !error && section && (
        <p className="px-1 text-sm text-slate-400">Pick a suggested chart above to get started.</p>
      )}

      {out && (
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              {activeTitle && <span className="font-medium text-slate-700">{activeTitle}</span>}
              <Badge tone="indigo">{out.row_count.toLocaleString()} points</Badge>
              {out.truncated && <Badge tone="amber">capped at 10k</Badge>}
              <span className="tabular">{out.execution_ms.toFixed(0)} ms</span>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setSaveOpen(true)}
                disabled={saved}
              >
                <BookmarkIcon className="h-4 w-4" /> {saved ? "Saved" : "Save"}
              </Button>
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

      {saveOpen && out && (
        <SaveToLibraryDialog
          draft={{ kind: "chart", section, spec: out.spec, chart_request: lastReq }}
          defaultTitle={activeTitle || "Chart"}
          onClose={() => setSaveOpen(false)}
          onSaved={() => setSaved(true)}
        />
      )}
    </div>
  );
}
