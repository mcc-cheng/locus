import { useEffect, useState } from "react";
import type { Result } from "vega-embed";
import { api } from "../api/client";
import type { SavedChart } from "../api/types";
import { useApp } from "../store";
import { VegaChart } from "../components/VegaChart";
import { Button, Card, ErrorBox, PageTitle, Spinner } from "../components/ui";
import { DownloadIcon, TrashIcon } from "../components/icons";

export function Saved() {
  const { openInVisualize } = useApp();
  const [charts, setCharts] = useState<SavedChart[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    api
      .listCharts()
      .then(setCharts)
      .catch((e) => setError(String(e.message)));
  }
  useEffect(load, []);

  async function remove(id: string) {
    await api.deleteChart(id);
    setCharts((cs) => (cs ?? []).filter((c) => c.id !== id));
  }

  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle
        title="Saved"
        subtitle="Charts you've saved while exploring. Download any as a PNG for your report."
      />
      {error && <ErrorBox message={error} />}
      {charts === null ? (
        <Spinner label="Loading your saved charts…" />
      ) : charts.length === 0 ? (
        <Card>
          <p className="text-sm text-slate-500">
            Nothing saved yet. In <span className="font-medium text-slate-700">Visualize</span> (or
            from a chart the analyst makes), click <span className="font-medium">Save</span> to keep
            a chart here.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {charts.map((c) => (
            <SavedCard key={c.id} chart={c} onOpen={openInVisualize} onDelete={remove} />
          ))}
        </div>
      )}
    </div>
  );
}

function SavedCard({
  chart,
  onOpen,
  onDelete,
}: {
  chart: SavedChart;
  onOpen: (req: NonNullable<SavedChart["chart_request"]>) => void;
  onDelete: (id: string) => void;
}) {
  const [view, setView] = useState<Result | null>(null);

  async function downloadPng() {
    if (!view) return;
    const url = await view.view.toImageURL("png", 2);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${chart.title || "chart"}.png`;
    a.click();
  }

  return (
    <Card>
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-800">{chart.title}</div>
          <div className="text-[11px] text-slate-400">{new Date(chart.created).toLocaleString()}</div>
        </div>
        <div className="flex shrink-0 gap-1.5">
          <Button variant="secondary" size="sm" onClick={downloadPng} disabled={!view}>
            <DownloadIcon className="h-4 w-4" /> PNG
          </Button>
          {chart.chart_request && (
            <Button variant="secondary" size="sm" onClick={() => onOpen(chart.chart_request!)}>
              Open
            </Button>
          )}
          <button
            onClick={() => onDelete(chart.id)}
            title="Delete"
            className="rounded-lg border border-slate-200 p-1.5 text-slate-400 transition hover:border-red-200 hover:bg-red-50 hover:text-red-500"
          >
            <TrashIcon className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="overflow-x-auto rounded-xl border border-slate-100 bg-slate-50/50 p-3">
        <VegaChart spec={chart.spec} onView={setView} />
      </div>
    </Card>
  );
}
