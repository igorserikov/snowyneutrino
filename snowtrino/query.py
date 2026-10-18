import json
from snowtrino.config import settings


def execute(endpoint: str, sql: str) -> tuple[list[str], list[list[object]]]:
    try:
        import trino
    except ImportError as exc:
        raise RuntimeError("trino-python-client is not installed") from exc
    host = endpoint.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(endpoint.rsplit(":", 1)[1].split("/")[0]) if ":" in endpoint.rsplit("/", 1)[-1] else 8080
    conn = trino.dbapi.connect(host=host, port=port, user="snowtrino", http_scheme="http",
                               request_timeout=settings.trino_query_timeout_seconds)
    cur = conn.cursor()
    cur.execute(sql)
    columns = [item[0] for item in (cur.description or [])]
    rows = cur.fetchmany(settings.trino_max_result_rows)
    return columns, [list(row) for row in rows]


def encode_result(columns: list[str], rows: list[list[object]]) -> str:
    return json.dumps({"columns": columns, "rows": rows}, default=str)
