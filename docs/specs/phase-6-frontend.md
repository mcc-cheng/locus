# Phase 6 — Frontend Dashboard

**Status:** implemented
**Module:** `frontend/` (React 18 + TypeScript + Tailwind v4, built with Vite)

A clean, non-engineer-friendly desktop UI. Tailwind only — no external component
library. Charts use `vega-embed`; the sandbox editor uses Monaco. Type-checks
under `strict` and production-builds (`npm run build`).

## API client (`src/api/`)

`types.ts` mirrors the backend response models; `client.ts` is a typed wrapper
that unwraps the `{ok, data, error}` envelope and throws on `!ok`. The base URL
is configurable (`setApiBase`) for the Tauri sidecar; in dev, Vite proxies `/api`
to `http://localhost:8000`. The agent client streams NDJSON line-by-line.

## 6.1 App shell (`App.tsx`, `store.tsx`)

Left sidebar with five tabs (Home, Upload, Data, Visualize, Sandbox). The agent
chat panel is a persistent right sidebar, collapsed by default, toggled by one
button; its open/closed state persists in `localStorage` and survives tab
changes. Shared state (`AppProvider`) carries the active tab, the selected
dataset, an "open in Visualize" hand-off, and a schema-version counter that makes
tabs refetch after an upload.

## 6.2 Home

Dataset count, total rows, total stored size; a recent-uploads table (file,
date, rows, engine, status) with an **Open** button that jumps to the Data tab
filtered to that dataset. All from `GET /schema`.

## 6.3 Upload

Large drag-and-drop zone + file-picker fallback; client-side preview (first
rows); engine selector (Deterministic / Agentic) with plain-English blurbs;
**biopack toggle OFF by default** that shows the exact warning and per-column
transform pickers when enabled; a staged progress indicator during ingestion;
on success a schema summary (tables, rows, FK count) with **Open in Data**; on
failure the exact error.

## 6.4 Data

Dataset selector → table list → paginated view (50/page) with typed column
headers, row counts, a client-side filter on the current page, and **Export CSV**.
Read-only throughout (queries go through the SELECT-only `/query`).

## 6.5 Visualize

Dataset + table selectors, chart-type buttons, column-role dropdowns scoped to
the chosen chart, **Generate** → `POST /visualize`, inline Vega-Lite render, a
collapsible **View spec** panel, and **Save PNG / SVG**. Honors the agent's
"Open in Visualize" hand-off.

## 6.6 Sandbox

**Create sandbox** → `POST /sandboxes`; Monaco Python editor with a helpful
starter; **Run** → `POST /sandboxes/:id/run`; output panel for stdout, stderr,
and generated plots (served via `GET /sandboxes/:id/artifacts/...`); a clear
"working on a copy" banner; **Destroy** button.

## 6.7 Agent chat panel

Scrollable session history; each assistant message shows the response, a
collapsible "SQL used"/"Chart spec used" block, an inline chart when present, and
an **Open in Visualize** button for chart answers; multiline input with
Enter-to-send and a typing indicator while streaming. Sends the **full
conversation history each request** (no server session state) and consumes the
streamed `action` / `result` / `message` events.
