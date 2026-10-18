from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snowtrino import main
from snowtrino.config import settings
from snowtrino.db import Base


def test_mock_mode_allows_only_one_non_deleted_cluster(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        with test_session() as db:
            yield db

    monkeypatch.setattr(settings, "infrastructure_mode", "mock")
    main.app.dependency_overrides[main.get_db] = override_get_db
    try:
        client = TestClient(main.app)
        first = client.post("/api/v1/clusters", json={"name": "first-cluster"})
        second = client.post("/api/v1/clusters", json={"name": "second-cluster"})

        assert first.status_code == 202
        assert second.status_code == 409
        assert "one cluster at a time" in second.json()["detail"]
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
        engine.dispose()
