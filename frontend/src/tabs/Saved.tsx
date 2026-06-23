import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { SavedItem } from "../api/types";
import { useApp } from "../store";
import { VegaChart, type ChartView } from "../components/VegaChart";
import { Button, Card, ErrorBox, PageTitle, Spinner } from "../components/ui";
import { BookmarkIcon, ChevronRight, DownloadIcon, TrashIcon } from "../components/icons";

// child folder paths directly under `path` (one level down)
function childFolders(folders: string[], path: string): string[] {
  const prefix = path ? path + "/" : "";
  const out = new Set<string>();
  for (const f of folders) {
    if (!f.startsWith(prefix)) continue;
    const rest = f.slice(prefix.length);
    if (rest && !rest.includes("/")) out.add(f);
  }
  return [...out].sort();
}

export function Saved() {
  const { openInVisualize } = useApp();
  const [items, setItems] = useState<SavedItem[] | null>(null);
  const [folders, setFolders] = useState<string[]>([]);
  const [path, setPath] = useState(""); // current folder ("" = root)
  const [error, setError] = useState<string | null>(null);

  function load() {
    Promise.all([api.listItems(), api.listFolders()])
      .then(([its, fs]) => {
        setItems(its);
        setFolders(fs);
      })
      .catch((e) => setError(String(e.message)));
  }
  useEffect(load, []);

  const here = useMemo(() => (items ?? []).filter((i) => i.folder === path), [items, path]);
  const subfolders = useMemo(() => childFolders(folders, path), [folders, path]);
  const crumbs = path ? path.split("/") : [];

  async function removeItem(id: string) {
    await api.deleteItem(id).catch(() => {});
    setItems((xs) => (xs ?? []).filter((i) => i.id !== id));
  }
  async function newFolder() {
    const name = window.prompt("New folder name");
    if (!name?.trim()) return;
    const full = path ? `${path}/${name.trim()}` : name.trim();
    await api.createFolder(full).catch((e) => setError(String(e.message)));
    load();
  }
  async function removeFolder(full: string) {
    if (!window.confirm(`Delete folder "${full}"? Items inside move to the root.`)) return;
    await api.deleteFolder(full).catch((e) => setError(String(e.message)));
    load();
  }

  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle
        title="Saved"
        subtitle="Your gallery of saved charts and figures. Organize them into folders and download any as a PNG."
      />
      {error && <ErrorBox message={error} />}

      {/* Breadcrumb + new folder */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-1 text-sm">
          <button
            onClick={() => setPath("")}
            className={path ? "text-indigo-600 hover:underline" : "font-medium text-slate-700"}
          >
            All saved
          </button>
          {crumbs.map((c, i) => {
            const sub = crumbs.slice(0, i + 1).join("/");
            const last = i === crumbs.length - 1;
            return (
              <span key={sub} className="flex items-center gap-1">
                <ChevronRight className="h-3.5 w-3.5 text-slate-300" />
                <button
                  onClick={() => setPath(sub)}
                  className={last ? "font-medium text-slate-700" : "text-indigo-600 hover:underline"}
                >
                  {c}
                </button>
              </span>
            );
          })}
        </div>
        <Button variant="secondary" size="sm" onClick={newFolder}>
          + New folder
        </Button>
      </div>

      {items === null ? (
        <Spinner label="Loading your library…" />
      ) : (
        <>
          {/* Folders */}
          {subfolders.length > 0 && (
            <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {subfolders.map((f) => {
                const name = f.split("/").pop()!;
                const count = (items ?? []).filter((i) => i.folder === f).length;
                return (
                  <div
                    key={f}
                    className="group flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 transition hover:border-indigo-300 hover:bg-slate-50"
                  >
                    <button onClick={() => setPath(f)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                      <FolderGlyph />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-slate-700">{name}</span>
                        <span className="text-[11px] text-slate-400">{count} item{count === 1 ? "" : "s"}</span>
                      </span>
                    </button>
                    <button
                      onClick={() => removeFolder(f)}
                      title="Delete folder"
                      className="shrink-0 rounded p-1 text-slate-300 opacity-0 transition hover:text-red-500 group-hover:opacity-100"
                    >
                      <TrashIcon className="h-4 w-4" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {/* Items in this folder */}
          {here.length === 0 && subfolders.length === 0 ? (
            <Card>
              <p className="text-sm text-slate-500">
                {path ? "This folder is empty." : "Nothing saved yet."} In{" "}
                <span className="font-medium text-slate-700">Visualize</span> or from a chart/figure
                the analyst makes, click <span className="font-medium">Save</span> to keep it here.
              </p>
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {here.map((it) => (
                <SavedCard key={it.id} item={it} onOpen={openInVisualize} onDelete={removeItem} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function FolderGlyph() {
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-500">
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8}>
        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
      </svg>
    </span>
  );
}

function SavedCard({
  item,
  onOpen,
  onDelete,
}: {
  item: SavedItem;
  onOpen: (req: NonNullable<SavedItem["chart_request"]>) => void;
  onDelete: (id: string) => void;
}) {
  const [view, setView] = useState<ChartView | null>(null);

  async function downloadPng() {
    let url: string;
    if (item.kind === "figure" && item.image) {
      url = item.image;
    } else if (view) {
      url = await view.toImageURL("png", 2);
    } else {
      return;
    }
    const a = document.createElement("a");
    a.href = url;
    a.download = `${item.title || "saved"}.png`;
    a.click();
  }

  return (
    <Card>
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <BookmarkIcon className="h-3.5 w-3.5 shrink-0 text-slate-300" />
            <span className="truncate text-sm font-semibold text-slate-800">{item.title}</span>
          </div>
          <div className="text-[11px] text-slate-400">
            {item.kind} · {new Date(item.created).toLocaleString()}
          </div>
        </div>
        <div className="flex shrink-0 gap-1.5">
          <Button
            variant="secondary"
            size="sm"
            onClick={downloadPng}
            disabled={item.kind === "chart" && !view}
          >
            <DownloadIcon className="h-4 w-4" /> PNG
          </Button>
          {item.kind === "chart" && item.chart_request && (
            <Button variant="secondary" size="sm" onClick={() => onOpen(item.chart_request!)}>
              Open
            </Button>
          )}
          <button
            onClick={() => onDelete(item.id)}
            title="Delete"
            className="rounded-lg border border-slate-200 p-1.5 text-slate-400 transition hover:border-red-200 hover:bg-red-50 hover:text-red-500"
          >
            <TrashIcon className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="overflow-x-auto rounded-xl border border-slate-100 bg-slate-50/50 p-3">
        {item.kind === "figure" && item.image ? (
          <img src={item.image} alt={item.title} className="mx-auto max-h-80 rounded" />
        ) : item.spec ? (
          <VegaChart spec={item.spec} onView={setView} />
        ) : (
          <p className="text-sm text-slate-400">Nothing to render.</p>
        )}
      </div>
    </Card>
  );
}
