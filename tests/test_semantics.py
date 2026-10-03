from bi_analyst.contracts import DataPolicy
from bi_analyst.data import load_csv_bytes
from bi_analyst.semantics import propose_semantics


def test_proposal_references_evidence_without_confirming(dataset):
    proposal = propose_semantics(dataset)
    assert proposal["confirmed"] is False
    assert proposal["mappings"] == {
        "date_column": "OrderDate",
        "date_format": "%Y-%m-%d",
        "row_key_columns": ["LineID"],
        "metric_column": "Revenue",
        "dimension_columns": ["Region", "Product"],
    }
    assert set(proposal["evidence_ids"]).issubset(
        {c["evidence_id"] for c in proposal["profile"]["columns"]}
    )
    assert "CustomerID" not in proposal["mappings"]["dimension_columns"]
    assert "C001" not in str(proposal)


def test_ambiguous_dates_and_duplicate_line_key_stay_unknown():
    data = load_csv_bytes(
        b"LineID,OrderDate,Revenue\n01,02/03/2026,10\n01,03/04/2026,20\n", DataPolicy()
    )
    proposal = propose_semantics(data)
    assert proposal["mappings"]["date_format"] is None
    assert proposal["mappings"]["row_key_columns"] == []
    assert len(proposal["unknowns"]) >= 6


def test_numeric_customer_id_not_proposed_as_revenue():
    data = load_csv_bytes(b"CustomerID,Anything\n0001,10\n0002,20\n", DataPolicy())
    assert propose_semantics(data)["mappings"]["metric_column"] is None
