from pathlib import Path

import pytest

from bi_analyst.contracts import AnalysisRequest, BusinessContract, DataPolicy
from bi_analyst.data import load_csv

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def contract():
    return BusinessContract.model_validate_json((EXAMPLES / "business_config.json").read_text())


@pytest.fixture
def policy():
    return DataPolicy()


@pytest.fixture
def dataset(policy):
    return load_csv(EXAMPLES / "sales.csv", policy)


@pytest.fixture
def request_spec():
    return AnalysisRequest.model_validate_json((EXAMPLES / "question.json").read_text())
