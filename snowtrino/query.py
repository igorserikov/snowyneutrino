import json
from urllib.parse import urlsplit
from snowtrino.config import settings


def _connect(endpoint: str, timeout_seconds: int):
    try:
        from trino.dbapi import connect
    except ImportError as exc:
        raise RuntimeError("trino-python-client is not installed") from exc
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Trino endpoint must be an HTTP or HTTPS URL")
    return connect(host=parsed.hostname, port=parsed.port or 8080, user="snowtrino",
                   http_scheme=parsed.scheme, request_timeout=timeout_seconds)


def check_ready(endpoint: str) -> bool:
    conn = _connect(endpoint, settings.trino_connect_timeout_seconds)
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1")
        return cur.fetchone() == (1,)
    finally:
        cur.close()
        conn.close()


def execute(endpoint: str, sql: str) -> tuple[list[str], list[list[object]]]:
    conn = _connect(endpoint, settings.trino_query_timeout_seconds)
    cur = conn.cursor()
    try:
        cur.execute(sql)
        columns = [item[0] for item in (cur.description or [])]
        rows = cur.fetchmany(settings.trino_max_result_rows)
        return columns, [list(row) for row in rows]
    finally:
        cur.close()
        conn.close()


def encode_result(columns: list[str], rows: list[list[object]]) -> str:
    return json.dumps({"columns": columns, "rows": rows}, default=str)
