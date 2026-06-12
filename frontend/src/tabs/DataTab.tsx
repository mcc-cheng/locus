import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { DataRow, DatasetSummary } from "../api/types";
import { useApp } from "../store";
import { Badge, Button, ErrorBox, Select, Spinner } from "../components/ui";
import { PlusIcon, TrashIcon } from "../components/icons";

const PAGE = 100;

export function DataTab() {
  const { selectedSection, setSelectedSection, refreshSchema, schemaVersion } = useApp();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [section, setSection] = useState<string | null>(selectedSection);
  const [columns, setColumns] = useState<string[]>([]);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [rows, setRows] = useState<DataRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ rid: number; ci: number } | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.schema().then((s) => setDatasets(s.datasets)).catch((e) => setError(String(e.message)));
  }, [schemaVersion]);

  // sync local section with the global selection (e.g. "Open" from Home)
  useEffect(() => {
    if (selectedSection) setSection(selectedSection);
  }, [selectedSection]);

  const load = useCallback(
    async (sec: string, reset: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const offset = reset ? 0 : rows.length;
        const page = await api.readRows(sec, offset, PAGE);
        setColumns(page.columns);
        setTotal(page.total);
        setRows((prev) => (reset ? page.rows : [...prev, ...page.rows]));
      } catch (e) {
        setError(String((e as Error).message ?? e));
      } finally {
        setLoading(false);
      }
    },
    [rows.length],
  );

  // when the dataset changes: reset and load the first page + column types
  useEffect(() => {
    if (!section) return;
    setRows([]);
    setColumns([]);
    setTotal(0);
    load(section, true);
    api
      .schemaSection(section)
      .then((m) => {
        const raw = m.tables.find((t) => t.name === "raw");
        setTypes(Object.fromEntries((raw?.columns ?? []).map((c) => [c.name, c.stored_type])));
      })
      .catch(() => setTypes({}));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el || loading || rows.length >= total) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 320) load(section!, false);
  }

  function beginEdit(rid: number, ci: number, current: string | null) {
    setEditing({ rid, ci });
    setEditValue(current ?? "");
  }

  async function commitEdit() {
    if (!editing || !section) return;
    const { rid, ci } = editing;
    const col = columns[ci];
    const row = rows.find((r) => r.rid === rid);
    const before = row?.cells[ci] ?? "";
    setEditing(null);
    if ((before ?? "") === editValue) return;
    // optimistic update
    setRows((rs) => rs.map((r) => (r.rid === rid ? { ...r, cells: r.cells.map((c, i) => (i === ci ? editValue : c)) } : r)));
    try {
      await api.patchCell(section, rid, col, editValue);
    } catch (e) {
      setError(String((e as Error).message ?? e));
      load(section, true);
    }
  }

  async function addRow() {
    if (!section) return;
    setSaving(true);
    try {
      const { rid } = await api.addRow(section);
      setRows((rs) => [...rs, { rid, cells: columns.map(() => null) }]);
      setTotal((t) => t + 1);
      requestAnimationFrame(() => {
        scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
        beginEdit(rid, 0, "");
      });
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  }

  async function removeRow(rid: number) {
    if (!section) return;
    setRows((rs) => rs.filter((r) => r.rid !== rid));
    setTotal((t) => Math.max(0, t - 1));
    try {
      await api.deleteRow(section, rid);
    } catch (e) {
      setError(String((e as Error).message ?? e));
      load(section, true);
    }
  }

  function exportCsv() {
    const esc = (v: unknown) => {
      const s = String(v ?? "");
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [columns.map(esc).join(","), ...rows.map((r) => r.cells.map(esc).join(","))];
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${section}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function deleteDataset() {
    if (!section) return;
    const ds = datasets.find((d) => d.name === section);
    if (!window.confirm(`Delete "${ds?.source_filename ?? section}"? This permanently removes the dataset and its preserved source copy.`))
      return;
    try {
      await api.deleteDataset(section);
      setSelectedSection(null);
      setSection(null);
      setRows([]);
      setColumns([]);
      refreshSchema();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-[26px] font-semibold tracking-tight text-slate-900">Data</h1>
        <Select
          value={section ?? ""}
          onChange={(v) => {
            setSection(v);
            setSelectedSection(v);
          }}
          className="ml-1"
        >
          <option value="">Select dataset…</option>
          {datasets.map((d) => (
            <option key={d.name} value={d.name}>
              {d.source_filename}
            </option>
          ))}
        </Select>
        {section && (
          <>
            <Badge>{total.toLocaleString()} rows</Badge>
            <div className="ml-auto flex items-center gap-2">
              <Button variant="primary" size="sm" onClick={addRow} disabled={saving}>
                <PlusIcon className="h-4 w-4" /> Add row
              </Button>
              <Button variant="secondary" size="sm" onClick={exportCsv}>
                Export CSV
              </Button>
              <Button variant="danger" size="sm" onClick={deleteDataset}>
                Delete dataset
              </Button>
            </div>
          </>
        )}
      </div>

      {error && <ErrorBox message={error} />}
      {!section && <p className="text-sm text-slate-500">Select a dataset to view and edit it.</p>}

      {/* Spreadsheet */}
      {section && (
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="min-h-0 flex-1 overflow-auto rounded-lg border border-slate-200 bg-white"
        >
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 z-10">
              <tr>
                <th className="sticky left-0 z-20 w-10 border-b border-r border-slate-200 bg-slate-50" />
                {columns.map((c) => (
                  <th
                    key={c}
                    className="border-b border-r border-slate-200 bg-slate-50 px-3 py-2 text-left align-top"
                  >
                    <div className="font-semibold text-slate-700">{c}</div>
                    <div className="font-normal text-slate-400">{types[c] ?? ""}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.rid} className="group hover:bg-indigo-50/30">
                  <td className="sticky left-0 z-10 border-b border-r border-slate-100 bg-white text-center group-hover:bg-indigo-50/30">
                    <button
                      onClick={() => removeRow(r.rid)}
                      title="Delete row"
                      className="text-slate-300 opacity-0 transition hover:text-red-500 group-hover:opacity-100"
                    >
                      <TrashIcon className="h-4 w-4" />
                    </button>
                  </td>
                  {r.cells.map((cell, ci) => {
                    const isEditing = editing?.rid === r.rid && editing?.ci === ci;
                    return (
                      <td
                        key={ci}
                        onClick={() => !isEditing && beginEdit(r.rid, ci, cell)}
                        className="border-b border-r border-slate-100 px-0 py-0"
                      >
                        {isEditing ? (
                          <input
                            autoFocus
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onBlur={commitEdit}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") commitEdit();
                              if (e.key === "Escape") setEditing(null);
                            }}
                            className="w-full bg-white px-3 py-1.5 text-xs outline-none ring-2 ring-inset ring-indigo-400"
                          />
                        ) : (
                          <div className="min-h-[28px] cursor-text px-3 py-1.5 text-slate-700">
                            {cell === null ? (
                              <span className="text-slate-300">—</span>
                            ) : (
                              cell
                            )}
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {loading && (
            <div className="px-3 py-3">
              <Spinner label={rows.length ? "Loading more…" : "Loading…"} />
            </div>
          )}
          {!loading && rows.length >= total && total > 0 && (
            <div className="px-3 py-3 text-center text-xs text-slate-400">
              {total.toLocaleString()} rows · end of data
            </div>
          )}
        </div>
      )}
    </div>
  );
}
