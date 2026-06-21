"""The semantic layer — a compact, curated "schema card" per dataset.

This is how the model *understands* the database. Instead of dumping raw rows or
a bare column list, we give the model a compact card that states, for each table:
its purpose, every column's meaning/units/type with a few real example values and
quick stats, the relationships between tables, curated metric definitions
(e.g. "active = logged in within 30 days"), and known gotchas.

The card has two layers:
  * an **auto-built** layer profiled from the actual data (types, ranges,
    categories, nulls, examples, detected gotchas, relationships), and
  * a **curation overlay** (purpose, column meanings/units, metric definitions,
    extra gotchas) persisted under ``library/semantic.json`` that the user or the
    agent writes via tools — so the card gets smarter over time.

For more than a handful of datasets, render only an index plus the relevant
card(s) (schema linking) rather than every card.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from services import QueryService
from warehouse import SectionManifest

_SEMANTIC_FILE = "semantic.json"
_EXAMPLES = 3


# ---- curation overlay (persisted, agent/user-writable) ----------------------


def _semantic_path(root: str | Path) -> Path:
    d = Path(root) / "library"
    d.mkdir(parents=True, exist_ok=True)
    return d / _SEMANTIC_FILE


def _load_all(root: str | Path) -> dict[str, Any]:
    p = _semantic_path(root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(root: str | Path, data: dict) -> None:
    p = _semantic_path(root)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def load_curation(root: str | Path, section: str) -> dict:
    cur = _load_all(root).get(section, {})
    cur.setdefault("purpose", "")
    cur.setdefault("columns", {})  # col -> {meaning, units}
    cur.setdefault("metrics", [])  # [{name, definition, sql}]
    cur.setdefault("gotchas", [])
    return cur


def define(
    root: str | Path,
    section: str,
    *,
    target: str,
    name: str = "",
    meaning: str = "",
    units: str = "",
    sql: str = "",
) -> str:
    """Persist a curated definition (the semantic-memory write path). ``target`` is
    'dataset' (purpose), 'column' (meaning/units of ``name``), or 'metric'
    (a named definition, optionally with the SQL that computes it)."""
    data = _load_all(root)
    cur = data.get(section) or load_curation(root, section)
    if target == "dataset":
        cur["purpose"] = meaning.strip()
        out = f'Recorded the purpose of "{section}".'
    elif target == "column":
        if not name:
            return "ERROR: a column name is required."
        col = cur["columns"].get(name, {})
        if meaning:
            col["meaning"] = meaning.strip()
        if units:
            col["units"] = units.strip()
        cur["columns"][name] = col
        out = f'Recorded the meaning of column "{name}".'
    elif target == "metric":
        if not name:
            return "ERROR: a metric name is required."
        cur["metrics"] = [m for m in cur["metrics"] if m.get("name") != name]
        cur["metrics"].append(
            {"name": name, "definition": meaning.strip(), "sql": sql.strip()}
        )
        out = f'Recorded the metric "{name}".'
    else:
        return f"ERROR: unknown define target {target!r}."
    data[section] = cur
    _save_all(root, data)
    return out


# ---- auto-built card --------------------------------------------------------


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _profile(qs: QueryService, section: str, table: str, cols: list[str]) -> dict[str, dict]:
    """One aggregate pass: classify and summarize every column."""
    raw = f'{_q(section)}.{_q(table)}'
    parts = ["COUNT(*) AS n"]
    for i, c in enumerate(cols):
        qc = _q(c)
        parts += [
            f"COUNT(DISTINCT {qc}) AS d{i}",
            f"COUNT({qc}) AS nn{i}",
            f"COUNT(TRY_CAST({qc} AS DOUBLE)) AS num{i}",
            f"MIN(TRY_CAST({qc} AS DOUBLE)) AS lo{i}",
            f"MAX(TRY_CAST({qc} AS DOUBLE)) AS hi{i}",
            f"AVG(TRY_CAST({qc} AS DOUBLE)) AS av{i}",
        ]
    out: dict[str, dict] = {}
    try:
        res = qs.run(f"SELECT {', '.join(parts)} FROM {raw}", page_size=1)
        row = dict(zip(res.columns, res.rows[0]))
    except Exception:
        return {c: {"kind": "text"} for c in cols}
    n = int(row.get("n") or 0)
    # one cheap pass for example values
    try:
        ex = qs.run(f"SELECT * FROM {raw} LIMIT 5", page_size=5)
        ex_cols = list(ex.columns)
        ex_rows = ex.rows
    except Exception:
        ex_cols, ex_rows = [], []
    for i, c in enumerate(cols):
        distinct = int(row.get(f"d{i}") or 0)
        nn = int(row.get(f"nn{i}") or 0)
        num = int(row.get(f"num{i}") or 0)
        nulls = (n - nn) if n else 0
        numeric = nn > 0 and num / nn >= 0.8
        mixed = nn > 0 and 0 < num < nn and num / nn >= 0.5  # mostly-but-not-all numeric
        examples: list[str] = []
        if c in ex_cols:
            ci = ex_cols.index(c)
            for r in ex_rows:
                v = r[ci]
                if v is not None and str(v) not in examples:
                    examples.append(str(v))
                if len(examples) >= _EXAMPLES:
                    break
        info = {
            "nulls": nulls,
            "distinct": distinct,
            "examples": examples,
            "mixed_numeric": mixed,
        }
        near_unique = bool(n) and distinct >= 0.9 * n
        name_id = c.lower() == "id" or c.lower().endswith("_id") or c.lower().endswith("id")
        if name_id and near_unique:
            info["kind"] = "id"  # an identifier, even if its values are numeric
        elif numeric:
            info["kind"] = "numeric"
            info["min"], info["max"], info["mean"] = (
                row.get(f"lo{i}"), row.get(f"hi{i}"), row.get(f"av{i}")
            )
        elif near_unique:
            info["kind"] = "id"
        elif distinct <= 25:
            info["kind"] = "categorical"
        else:
            info["kind"] = "text"
        out[c] = info
    return out


def _categories(qs: QueryService, section: str, table: str, col: str) -> list[str]:
    try:
        res = qs.run(
            f"SELECT DISTINCT {_q(col)} FROM {_q(section)}.{_q(table)} "
            f"WHERE {_q(col)} IS NOT NULL LIMIT 12",
            page_size=12,
        )
        return [str(r[0]) for r in res.rows]
    except Exception:
        return []


def build_card(qs: QueryService, manifest: SectionManifest, curation: dict) -> dict:
    """Assemble the schema card for one dataset from live profiling + curation."""
    raw = next((t for t in manifest.tables if t.name == "raw"), manifest.tables[0])
    other_tables = [t for t in manifest.tables if t.name != raw.name]
    cols = [c.name for c in raw.columns]
    prof = _profile(qs, manifest.name, raw.name, cols)

    columns: list[dict] = []
    gotchas: list[str] = list(curation.get("gotchas", []))
    cur_cols = curation.get("columns", {})
    for c in cols:
        p = prof.get(c, {"kind": "text"})
        entry = {
            "name": c,
            "kind": p.get("kind", "text"),
            "nulls": p.get("nulls", 0),
            "distinct": p.get("distinct"),
            "examples": p.get("examples", []),
            "meaning": cur_cols.get(c, {}).get("meaning", ""),
            "units": cur_cols.get(c, {}).get("units", ""),
        }
        if p.get("kind") == "numeric":
            entry["min"], entry["max"], entry["mean"] = p.get("min"), p.get("max"), p.get("mean")
        elif p.get("kind") == "categorical":
            entry["categories"] = _categories(qs, manifest.name, raw.name, c)
        columns.append(entry)
        # auto-detected gotchas
        if p.get("nulls"):
            gotchas.append(f'"{c}" has {p["nulls"]} missing value(s) — filter or handle them.')
        if p.get("mixed_numeric"):
            gotchas.append(
                f'"{c}" mixes numbers and text (e.g. {", ".join(p.get("examples", [])[:2])}) '
                "— TRY_CAST drops the non-numeric ones."
            )

    # relationships: only key-like shared columns (a join key, not any shared
    # value column) — otherwise a denormalized fact table looks "related" on
    # every column. Keep it to id-style keys.
    def _key_like(name: str) -> bool:
        n = name.lower()
        return n == "id" or n.endswith("_id") or n.endswith("id")

    relationships = []
    for t in other_tables:
        shared = sorted({c.name for c in t.columns} & set(cols))
        for k in shared:
            if _key_like(k):
                relationships.append(f'join "{raw.name}"."{k}" → "{t.name}"."{k}"')

    return {
        "section": manifest.name,
        "file": manifest.source_filename,
        "rows": raw.row_count,
        "table": raw.name,
        "other_tables": [t.name for t in other_tables],
        "purpose": curation.get("purpose", ""),
        "columns": columns,
        "relationships": relationships,
        "metrics": curation.get("metrics", []),
        "gotchas": gotchas,
    }


# ---- rendering (compact, for the model's context) ---------------------------


def _fmt_num(v) -> str:
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def render_card(card: dict) -> str:
    lines: list[str] = []
    head = f'Dataset "{card["file"]}"  (section {card["section"]}, {card["rows"]} rows).'
    if card.get("purpose"):
        head += f' Purpose: {card["purpose"]}'
    lines.append(head)
    lines.append('Columns of "raw" (all stored as TEXT — cast numerics with TRY_CAST):')
    for c in card["columns"]:
        bits = [f'  • "{c["name"]}" [{c["kind"]}'
                + (f', {c["units"]}' if c.get("units") else "") + "]"]
        if c.get("meaning"):
            bits.append(f'— {c["meaning"]}')
        if c["kind"] == "numeric" and c.get("min") is not None:
            bits.append(f'range {_fmt_num(c["min"])}–{_fmt_num(c["max"])}, mean {_fmt_num(c["mean"])}')
        elif c.get("categories"):
            bits.append(f'{c["distinct"]} values: {", ".join(c["categories"])}')
        elif c["examples"]:
            bits.append("e.g. " + ", ".join(c["examples"]))
        if c.get("nulls"):
            bits.append(f'({c["nulls"]} null)')
        lines.append(" ".join(bits))
    if card.get("metrics"):
        lines.append("Metric definitions:")
        for m in card["metrics"]:
            extra = f'  [sql: {m["sql"]}]' if m.get("sql") else ""
            lines.append(f'  • {m["name"]}: {m.get("definition", "")}{extra}')
    if card.get("relationships"):
        lines.append("Relationships: " + "; ".join(card["relationships"]))
    if card.get("gotchas"):
        lines.append("Watch out:")
        for g in card["gotchas"]:
            lines.append(f"  • {g}")
    return "\n".join(lines)


def render_index(cards: list[dict]) -> str:
    """One compact line per dataset — used for schema linking across many datasets."""
    lines = ["Datasets available (ask about one at a time):"]
    for c in cards:
        col_names = ", ".join(col["name"] for col in c["columns"][:10])
        more = "…" if len(c["columns"]) > 10 else ""
        purpose = f' — {c["purpose"]}' if c.get("purpose") else ""
        lines.append(
            f'  • section "{c["section"]}" (file {c["file"]}, {c["rows"]} rows){purpose}: '
            f"{col_names}{more}"
        )
    return "\n".join(lines)
