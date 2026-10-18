import pytest
from pydantic import ValidationError

from snowtrino.schemas import ClusterCreate, QueryRequest, ScaleRequest


def test_cluster_schema_accepts_valid_name_and_limits_workers():
    value = ClusterCreate(name="demo-cluster", worker_count=3)
    assert value.worker_count == 3
    with pytest.raises(ValidationError):
        ClusterCreate(name="Bad Name")
    with pytest.raises(ValidationError):
        ScaleRequest(worker_count=0)


def test_query_must_not_be_blank():
    assert QueryRequest(sql="SELECT 1").sql == "SELECT 1"
    with pytest.raises(ValidationError):
        QueryRequest(sql="  ")
