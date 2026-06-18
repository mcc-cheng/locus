"""The structured description of a data mutation the analyst proposes.

A ``MutationAction`` is produced by the agent loop (from an ``edit_data`` /
``delete_data`` / ``restructure_data`` tool step), shown to the user for explicit
confirmation, and — only if they click Confirm — round-tripped back and executed
*deterministically* by the API layer (the LLM is never re-run to perform the
change, so it cannot drift from what the user approved).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

MutationOp = Literal["update", "delete", "add_column", "drop_column", "rename_column"]


class MutationAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    op: MutationOp
    section: str
    table: str = "raw"
    # update
    set_column: str | None = None
    set_value: str | None = None
    # update / delete
    where: str | None = None
    # restructure (add/drop/rename column)
    column: str | None = None
    new_name: str | None = None

    def describe(self, affected: int | None = None) -> str:
        """A plain-English summary shown on the confirmation button/prompt."""
        n = f"{affected} " if affected is not None else ""
        rows = "row" if affected == 1 else "rows"
        if self.op == "update":
            target = "all rows" if not self.where else f"the {n}matching {rows}"
            return f'Set "{self.set_column}" = {self.set_value!r} for {target} in "{self.section}".'
        if self.op == "delete":
            target = f"all {n}{rows}" if not self.where else f"the {n}{rows} where {self.where}"
            return f'Delete {target} from "{self.section}".'
        if self.op == "add_column":
            return f'Add a new column "{self.column}" to "{self.section}".'
        if self.op == "drop_column":
            return f'Drop the column "{self.column}" from "{self.section}".'
        if self.op == "rename_column":
            return f'Rename column "{self.column}" to "{self.new_name}" in "{self.section}".'
        return f"{self.op} on {self.section}"

    def preview_sql(self) -> str:
        """The exact statement that will run (shown under the confirm prompt)."""
        raw = f'"{self.section}"."{self.table}"'
        if self.op == "update":
            w = f" WHERE {self.where}" if self.where else ""
            return f'UPDATE {raw} SET "{self.set_column}" = {self.set_value!r}{w}'
        if self.op == "delete":
            w = f" WHERE {self.where}" if self.where else ""
            return f"DELETE FROM {raw}{w}"
        if self.op == "add_column":
            return f'ALTER TABLE {raw} ADD COLUMN "{self.column}" VARCHAR'
        if self.op == "drop_column":
            return f'ALTER TABLE {raw} DROP COLUMN "{self.column}"'
        if self.op == "rename_column":
            return f'ALTER TABLE {raw} RENAME COLUMN "{self.column}" TO "{self.new_name}"'
        return ""

    def is_row_scoped(self) -> bool:
        """update/delete affect rows (need a count preview); restructure doesn't."""
        return self.op in ("update", "delete")


def apply(con, action: "MutationAction") -> dict:
    """Execute a confirmed mutation against a read-write connection and return a
    result summary. Called ONLY by the API layer after explicit user confirmation
    — never from the agent loop."""
    from warehouse import mutate

    op = action.op
    if op == "update":
        if not action.set_column:
            raise ValueError("set_column is required")
        n = mutate.update_where(
            con, action.section, action.table, action.set_column, action.set_value, action.where
        )
        return {"op": op, "rows_affected": n, "summary": f"Updated {n} row(s)."}
    if op == "delete":
        n = mutate.delete_where(con, action.section, action.table, action.where)
        return {"op": op, "rows_affected": n, "summary": f"Deleted {n} row(s)."}
    if op == "add_column":
        mutate.add_column(con, action.section, action.table, action.column or "")
        return {"op": op, "summary": f'Added column "{action.column}".'}
    if op == "drop_column":
        mutate.drop_column(con, action.section, action.table, action.column or "")
        return {"op": op, "summary": f'Dropped column "{action.column}".'}
    if op == "rename_column":
        mutate.rename_column(
            con, action.section, action.table, action.column or "", action.new_name or ""
        )
        return {"op": op, "summary": f'Renamed "{action.column}" to "{action.new_name}".'}
    raise ValueError(f"unknown mutation op: {op}")
