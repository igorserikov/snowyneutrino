"""Snowflake-inspired SQL commands implemented by SnowTrino around Trino."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from snowtrino.config import settings
from snowtrino.models import Stage, StageLoad
from snowtrino.query import execute, execute_update


class SqlLayerError(ValueError):
    """An error in one of SnowTrino's custom SQL statements."""


_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_$]*"


def _statement(sql: str) -> str:
    return sql.strip().removesuffix(";").strip()


def _s3_client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is required for stage commands; install the project dependencies"
        ) from exc
    return boto3.client(
        "s3",
        endpoint_url=settings.stage_s3_endpoint,
        region_name=settings.stage_s3_region,
        aws_access_key_id=settings.stage_s3_access_key,
        aws_secret_access_key=settings.stage_s3_secret_key,
        config=Config(s3={"addressing_style": "path"}),
    )


def _stage_url(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "s3" or not parsed.netloc or parsed.query or parsed.fragment:
        raise SqlLayerError(
            "Only S3-compatible stage URLs are supported, for example s3://warehouse/incoming/"
        )
    if ":" in parsed.netloc or "@" in parsed.netloc:
        raise SqlLayerError("Stage URL must use the form s3://bucket/optional/path/")
    prefix = parsed.path.lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    normalized = f"s3://{parsed.netloc}/{prefix}"
    return parsed.netloc, prefix, normalized


def _stage(db: Session, cluster_id: str, name: str) -> Stage:
    stage = db.scalar(
        select(Stage).where(Stage.cluster_id == cluster_id, Stage.name == name.lower())
    )
    if not stage:
        raise SqlLayerError(f"Stage @{name} does not exist")
    return stage


def _stage_objects(stage: Stage, path: str = "") -> list[dict]:
    bucket, base_prefix, _ = _stage_url(stage.url)
    prefix = base_prefix + path.strip("/")
    paginator = _s3_client().get_paginator("list_objects_v2")
    objects: list[dict] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            relative = key[len(base_prefix):] if key.startswith(base_prefix) else key
            objects.append({
                "key": key,
                "name": relative,
                "size": item["Size"],
                "etag": str(item.get("ETag", "")).strip('"') or None,
                "last_modified": item.get("LastModified"),
            })
    return objects


def _result(columns: list[str], rows: list[list[object]]):
    return columns, rows


def _create_stage(sql: str, db: Session, cluster_id: str):
    match = re.fullmatch(
        rf"CREATE\s+STAGE\s+(?P<if_not_exists>IF\s+NOT\s+EXISTS\s+)?(?P<name>{_IDENTIFIER})\s+"
        r"URL\s*=\s*'(?P<url>[^']+)'",
        _statement(sql), re.IGNORECASE,
    )
    if not match:
        raise SqlLayerError(
            "Supported syntax: CREATE STAGE [IF NOT EXISTS] name URL = 's3://bucket/prefix/'"
        )
    name = match.group("name").lower()
    _, _, url = _stage_url(match.group("url"))
    existing = db.scalar(select(Stage).where(Stage.cluster_id == cluster_id, Stage.name == name))
    if existing:
        if match.group("if_not_exists"):
            return _result(["stage", "url", "status"], [[name, existing.url, "EXISTS"]])
        raise SqlLayerError(f"Stage @{name} already exists")
    stage = Stage(cluster_id=cluster_id, name=name, url=url)
    db.add(stage)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SqlLayerError(f"Stage @{name} already exists") from exc
    return _result(["stage", "url", "status"], [[name, url, "CREATED"]])


def _list_stage(sql: str, db: Session, cluster_id: str):
    match = re.fullmatch(
        rf"(?:LIST|LS)\s+@(?P<name>{_IDENTIFIER})(?:/(?P<path>[^\s]+))?"
        r"(?:\s+PATTERN\s*=\s*'(?P<pattern>(?:''|[^'])*)')?",
        _statement(sql), re.IGNORECASE,
    )
    if not match:
        raise SqlLayerError("Supported syntax: LIST @stage[/path] [PATTERN = 'regex']")
    stage = _stage(db, cluster_id, match.group("name"))
    pattern = match.group("pattern")
    try:
        regex = re.compile(pattern.replace("''", "'")) if pattern else None
    except re.error as exc:
        raise SqlLayerError(f"Invalid LIST pattern: {exc}") from exc
    objects = _stage_objects(stage, match.group("path") or "")
    if regex:
        objects = [item for item in objects if regex.search(item["name"])]
    rows = [[item["name"], item["size"], item["etag"], None,
             item["last_modified"].isoformat() if item["last_modified"] else None]
            for item in objects]
    return _result(["name", "size", "md5", "sha1", "last_modified"], rows)


def _show_stages(sql: str, db: Session, cluster_id: str):
    match = re.fullmatch(
        r"SHOW\s+STAGES(?:\s+LIKE\s+'((?:''|[^'])*)')?",
        _statement(sql), re.IGNORECASE,
    )
    if not match:
        raise SqlLayerError("Supported syntax: SHOW STAGES [LIKE 'pattern']")
    stages = db.scalars(
        select(Stage).where(Stage.cluster_id == cluster_id).order_by(Stage.name)
    ).all()
    pattern = match.group(1)
    if pattern is not None:
        like_regex = "".join(
            ".*" if char == "%" else "." if char == "_" else re.escape(char)
            for char in pattern.replace("''", "'")
        )
        stages = [stage for stage in stages if re.fullmatch(like_regex, stage.name, re.IGNORECASE)]
    columns = [
        "created_on", "name", "database_name", "schema_name", "url", "has_credentials",
        "has_encryption_key", "owner", "comment", "region", "type", "cloud",
        "notification_channel", "storage_integration", "endpoint", "owner_role_type",
        "directory_enabled",
    ]
    rows = [[stage.created_at, stage.name, None, None, stage.url, "Y", "N", None,
             None, settings.stage_s3_region, "EXTERNAL", None, None, None,
             settings.stage_s3_endpoint, None, "N"] for stage in stages]
    return _result(columns, rows)


def _parse_copy(sql: str):
    match = re.match(
        rf"COPY\s+INTO\s+(?P<target>(?:{_IDENTIFIER}\.)?{_IDENTIFIER}(?:\.{_IDENTIFIER})?)\s+"
        rf"FROM\s+@(?P<stage>{_IDENTIFIER})(?:/(?P<path>[^\s;]+))?(?P<options>.*)$",
        _statement(sql), re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise SqlLayerError(
            "Supported syntax: COPY INTO hive.schema.table FROM @stage[/path] "
            "[FILES = ('name.csv', ...)] [PATTERN = 'regex'] [FILE_FORMAT = (TYPE = CSV)]"
        )
    options = match.group("options")
    tokens = list(re.finditer(
        r"FILES\s*=\s*\((?P<files>[^)]*)\)|"
        r"PATTERN\s*=\s*'(?P<pattern>(?:''|[^'])*)'|"
        r"FILE_FORMAT\s*=\s*\(\s*TYPE\s*=\s*'?(?P<format>[A-Za-z]+)'?\s*\)",
        options, re.IGNORECASE,
    ))
    residue = options
    for token in reversed(tokens):
        residue = residue[:token.start()] + residue[token.end():]
    if residue.strip(" \t\r\n,"):
        raise SqlLayerError(f"Unsupported COPY INTO option: {residue.strip()}")
    values: dict[str, object] = {}
    for token in tokens:
        key = "files" if token.group("files") is not None else (
            "pattern" if token.group("pattern") is not None else "format"
        )
        if key in values:
            raise SqlLayerError(f"COPY INTO specifies {key.upper()} more than once")
        if key == "files":
            files = re.findall(r"'((?:''|[^'])*)'", token.group("files"))
            remainder = re.sub(
                r"'(?:(?:'')|[^'])*'\s*(?:,\s*)?", "", token.group("files")
            ).strip()
            if not files or remainder:
                raise SqlLayerError("FILES must be a comma-separated list of quoted file names")
            values[key] = [file.replace("''", "'") for file in files]
        elif key == "pattern":
            values[key] = token.group("pattern").replace("''", "'")
        else:
            values[key] = token.group("format").upper()
    file_format = str(values.get("format", "CSV"))
    if file_format not in {"CSV", "JSON", "PARQUET", "ORC"}:
        raise SqlLayerError("COPY INTO supports CSV, JSON, PARQUET, or ORC files")
    pattern = values.get("pattern")
    try:
        regex = re.compile(str(pattern)) if pattern else None
    except re.error as exc:
        raise SqlLayerError(f"Invalid COPY pattern: {exc}") from exc
    target = match.group("target").lower()
    target_parts = target.split(".")
    if len(target_parts) == 1:
        raise SqlLayerError("Use a schema-qualified target such as hive.demo.events")
    if len(target_parts) == 3 and target_parts[0] != "hive":
        raise SqlLayerError("COPY INTO currently writes only to the hive catalog")
    if len(target_parts) == 2:
        target = "hive." + target
    return (
        target, match.group("stage").lower(), match.group("path") or "",
        values, regex, file_format,
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _datetime_key(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _copy_into(sql: str, db: Session, cluster_id: str, endpoint: str):
    target, stage_name, path, options, regex, file_format = _parse_copy(sql)
    stage = _stage(db, cluster_id, stage_name)
    bucket, _, _ = _stage_url(stage.url)
    objects = _stage_objects(stage, path)
    if "files" in options:
        requested = set(options["files"])
        objects = [item for item in objects if item["name"] in requested]
        missing = requested - {item["name"] for item in objects}
        if missing:
            raise SqlLayerError("Files not found in stage: " + ", ".join(sorted(missing)))
    if regex:
        objects = [item for item in objects if regex.search(item["name"])]

    table_result, table_rows = execute(endpoint, f"SHOW COLUMNS FROM {target}")
    del table_result
    columns = [str(row[0]) for row in table_rows]
    if not columns:
        raise SqlLayerError(f"Target table {target} has no readable columns")
    definitions = ", ".join(f"{_quote_identifier(str(row[0]))} {row[1]}" for row in table_rows)
    previous = db.scalars(select(StageLoad).where(StageLoad.stage_id == stage.id,
                                                    StageLoad.target_table == target)).all()
    loaded = {item.object_key: item for item in previous}
    pending = [item for item in objects
               if item["key"] not in loaded or loaded[item["key"]].etag != item["etag"]
               or _datetime_key(loaded[item["key"]].last_modified)
               != _datetime_key(item["last_modified"])]
    if not pending:
        return _result(
            ["target", "status", "files_loaded", "rows_loaded"],
            [[target, "SKIPPED", 0, 0]],
        )

    _, stage_prefix, stage_base = _stage_url(stage.url)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in pending:
        parent = item["key"].rsplit("/", 1)[0] + "/"
        grouped[parent].append(item)
    rows_loaded = 0
    total_loaded = 0
    try:
        for parent, group in grouped.items():
            temp_name = "__snowtrino_copy_" + uuid4().hex[:16]
            target_schema = target.split(".")[1]
            temp_table = f"hive.{target_schema}.{temp_name}"
            location = f"s3://{bucket}/{parent}"
            execute(endpoint, f"CREATE TABLE {temp_table} ({definitions}) WITH "
                    f"(format = '{file_format}', external_location = {_sql_literal(location)})")
            try:
                object_urls = [stage_base + item["key"][len(stage_prefix):]
                               for item in group]
                where = ", ".join(_sql_literal(url) for url in object_urls)
                insert_sql = (f"INSERT INTO {target} SELECT "
                              f"{', '.join(_quote_identifier(column) for column in columns)} "
                              f"FROM {temp_table} WHERE \"$path\" IN ({where})")
                rows_loaded += execute_update(endpoint, insert_sql)
                total_loaded += len(group)
            finally:
                execute(endpoint, f"DROP TABLE IF EXISTS {temp_table}")

        for item in pending:
            record = loaded.get(item["key"])
            if record:
                record.etag = item["etag"]
                record.last_modified = item["last_modified"]
                record.loaded_at = datetime.now(timezone.utc)
            else:
                db.add(StageLoad(stage_id=stage.id, target_table=target, object_key=item["key"],
                                 etag=item["etag"], last_modified=item["last_modified"]))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _result(["target", "status", "files_loaded", "rows_loaded"],
                   [[target, "LOADED", total_loaded, rows_loaded]])


def execute_custom_sql(sql: str, db: Session, cluster_id: str, endpoint: str):
    """Run a supported SnowTrino command, or return None for regular Trino SQL."""
    statement = _statement(sql)
    if re.match(r"CREATE\s+STAGE\b", statement, re.IGNORECASE):
        return _create_stage(statement, db, cluster_id)
    if re.match(r"(?:LIST|LS)\b", statement, re.IGNORECASE):
        return _list_stage(statement, db, cluster_id)
    if re.match(r"SHOW\s+STAGES\b", statement, re.IGNORECASE):
        return _show_stages(statement, db, cluster_id)
    if re.match(r"COPY\s+INTO\b", statement, re.IGNORECASE):
        return _copy_into(statement, db, cluster_id, endpoint)
    return None
