from __future__ import annotations

from types import SimpleNamespace

import pytest

from ingest import (
    AgenticIngestor,
    ModelProposal,
    OllamaClient,
    OllamaUnavailableError,
    ProposedDimension,
    read_contract,
)
from ingest.errors import ProposalError

ORDERS = (
    "order_id,product_id,product_name,category,qty\n"
    "1,P1,Widget,Tools,3\n"
    "2,P2,Gadget,Tools,1\n"
    "3,P1,Widget,Tools,5\n"
    "4,P3,Gizmo,Gadgets,2\n"
)


class FakeProposer:
    """A deterministic stand-in for the Ollama proposer."""

    def __init__(self, proposal=None, *, available=True, propose_exc=None):
        self.config = SimpleNamespace(model="fake-model")
        self._proposal = proposal or ModelProposal()
        self._available = available
        self._propose_exc = propose_exc

    def ensure_available(self):
        if not self._available:
            raise OllamaUnavailableError("ollama down (test)")

    def propose(self, profile):
        if self._propose_exc is not None:
            raise self._propose_exc
        return self._proposal


def _ingest(warehouse, write_csv, ts, proposer, name="orders.csv", content=ORDERS):
    return AgenticIngestor(warehouse, proposer).ingest(write_csv(name, content), ts)


def _dim_by_key(contract, key):
    for t in contract.tables:
        if t.role == "dimension" and t.primary_key == (key,):
            return t
    return None


def test_agentic_uses_valid_model_proposal(warehouse, write_csv, ts):
    proposal = ModelProposal(
        grain="one row per order line",
        primary_key="order_id",
        dimensions=[
            ProposedDimension(
                key="product_id", attributes=["product_name", "category"], name="product"
            )
        ],
    )
    res = _ingest(warehouse, write_csv, ts, FakeProposer(proposal))
    assert res.qc.passed
    assert res.contract.engine == "agentic"
    assert res.contract.grain == "one row per order line"
    assert res.contract.table("fact").primary_key == ("order_id",)
    dim = _dim_by_key(res.contract, "product_id")
    assert dim is not None and set(dim.columns) == {"product_id", "product_name", "category"}


def test_blocks_when_ollama_unavailable_before_touching_data(warehouse, write_csv, ts):
    with pytest.raises(OllamaUnavailableError):
        _ingest(warehouse, write_csv, ts, FakeProposer(available=False))
    # Nothing was landed — blocked before any section was created.
    assert warehouse.list_sections() == []
    assert list(warehouse.source_dir.glob("orders__*")) == []


def test_dimension_with_false_fd_is_dropped(warehouse, write_csv, ts):
    # category repeats but does NOT determine product_name (Tools -> Widget AND
    # Gadget), so the dimension must be dropped.
    proposal = ModelProposal(
        primary_key="order_id",
        dimensions=[ProposedDimension(key="category", attributes=["product_name"])],
    )
    res = _ingest(warehouse, write_csv, ts, FakeProposer(proposal))
    assert res.qc.passed
    assert _dim_by_key(res.contract, "category") is None
    # product_name stayed in the fact; nothing lost.
    assert "product_name" in res.contract.table("fact").columns


def test_hallucinated_column_is_ignored(warehouse, write_csv, ts):
    proposal = ModelProposal(
        primary_key="order_id",
        dimensions=[ProposedDimension(key="nonexistent_col", attributes=["also_fake"])],
    )
    res = _ingest(warehouse, write_csv, ts, FakeProposer(proposal))
    assert res.qc.passed
    assert {t.name for t in res.contract.tables} == {"fact"}  # no dimension built


def test_non_unique_model_pk_is_ignored(warehouse, write_csv, ts):
    proposal = ModelProposal(primary_key="product_id")  # repeats -> not a valid PK
    res = _ingest(warehouse, write_csv, ts, FakeProposer(proposal))
    # Falls back to a derived PK (order_id is unique).
    assert res.contract.table("fact").primary_key == ("order_id",)


def test_degrades_to_deterministic_on_proposal_error(warehouse, write_csv, ts):
    proposer = FakeProposer(propose_exc=ProposalError("garbage json"))
    res = _ingest(warehouse, write_csv, ts, proposer)
    assert res.qc.passed
    assert res.contract.engine == "agentic"
    # Deterministic structure recovered the product dimension.
    assert _dim_by_key(res.contract, "product_id") is not None
    audit_text = res.audit_path.read_text()
    assert "deterministic structure" in audit_text


def test_audit_records_model_and_notes(warehouse, write_csv, ts):
    proposal = ModelProposal(
        primary_key="order_id",
        dimensions=[ProposedDimension(key="category", attributes=["product_name"])],
    )
    res = _ingest(warehouse, write_csv, ts, FakeProposer(proposal))
    contract_again = read_contract(res.contract_path)
    assert contract_again == res.contract
    audit_text = res.audit_path.read_text()
    assert "fake-model" in audit_text
    assert "FD fails" in audit_text  # the dropped-dimension note


# ---- real Ollama end-to-end (skipped if the model isn't available) ----------


def _ollama_ready() -> bool:
    try:
        OllamaClient().ensure_available()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_ready(), reason="qwen2.5:7b-instruct not available")
def test_real_ollama_ingest_is_lossless(warehouse, write_csv, ts):
    res = AgenticIngestor(warehouse).ingest(write_csv("orders.csv", ORDERS), ts)
    # Regardless of what schema the model proposes, the result must be lossless.
    assert res.qc.passed
    assert res.contract.engine == "agentic"
    n = warehouse.con.execute(f'SELECT COUNT(*) FROM "{res.section}".fact').fetchone()[0]
    assert n == 4
