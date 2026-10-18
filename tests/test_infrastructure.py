from snowtrino.infrastructure import MockProvider
from snowtrino.models import Cluster


def test_mock_provider_has_predictable_endpoint_without_cloud_access():
    cluster = Cluster(name="test-cluster")
    assert MockProvider().apply(cluster) == "http://test-cluster.localhost:8080"
