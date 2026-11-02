#!/usr/bin/env python3
"""Read-only SQL Server helper for AR QA. SELECT/WITH only. Never writes."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|EXEC|EXECUTE|"
    r"GRANT|REVOKE|BACKUP|RESTORE|OPENROWSET|BULK|xp_|sp_)\b|"
    r"\bINTO\s+\w+|DBCC\b",
    re.I,
)


def assert_readonly(sql: str) -> str:
    s = sql.strip().rstrip(";")
    if not s:
        raise SystemExit("empty SQL")
    if FORBIDDEN.search(s):
        raise SystemExit(f"Rejected non-readonly SQL: {s[:120]}")
    head = s.lstrip().split(None, 1)[0].upper()
    if head not in ("SELECT", "WITH"):
        raise SystemExit("Only SELECT or WITH…SELECT allowed")
    return s


def load_profile(args: argparse.Namespace) -> Dict[str, Any]:
    secrets = Path(r"C:\WORK\QA_studio\data\local_secrets.json")
    disk: Dict[str, Any] = {}
    if secrets.is_file():
        try:
            disk = json.loads(secrets.read_text(encoding="utf-8")).get("db") or {}
        except Exception:
            disk = {}
    host = args.host or os.environ.get("QA_DB_HOST") or disk.get("host") or "10.98.54.17"
    database = args.database or os.environ.get("QA_DB_NAME") or disk.get("database") or ""
    user = args.user or os.environ.get("QA_DB_USER") or disk.get("username") or "AR_USER_18_OWNER"
    password = (
        args.password
        or os.environ.get("QA_DB_PASSWORD")
        or disk.get("password")
        or user  # team convention unless overridden
    )
    port = args.port or os.environ.get("QA_DB_PORT") or disk.get("port")
    if not database:
        database = user  # common owner DB name pattern
    return {
        "host": host,
        "port": port,
        "database": database,
        "username": user,
        "password": password,
    }


def conn_str(p: Dict[str, Any]) -> str:
    server = f"{p['host']},{p['port']}" if p.get("port") else p["host"]
    return (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={p['database']};"
        f"UID={p['username']};"
        f"PWD={p['password']};"
        "TrustServerCertificate=yes;"
        "Encrypt=no;"
        "ApplicationIntent=ReadOnly;"
    )


def connect(p: Dict[str, Any]):
    import pyodbc

    return pyodbc.connect(conn_str(p), timeout=20, autocommit=True)


def rows_to_dicts(cur) -> List[Dict[str, Any]]:
    cols = [c[0] for c in cur.description] if cur.description else []
    out = []
    for row in cur.fetchall():
        d = {}
        for i, c in enumerate(cols):
            v = row[i]
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            elif isinstance(v, bytes):
                v = v.decode("utf-8", errors="replace")
            d[c] = v
        out.append(d)
    return out


def cmd_ping(p: Dict[str, Any]) -> None:
    cn = connect(p)
    try:
        cur = cn.cursor()
        cur.execute("SELECT DB_NAME() AS db_name, SUSER_SNAME() AS login_name, 1 AS ok")
        print(json.dumps({"ok": True, "profile": {k: v for k, v in p.items() if k != "password"}, "row": rows_to_dicts(cur)[0]}, indent=2))
    finally:
        cn.close()


def cmd_catalog(p: Dict[str, Any], like: str, limit: int) -> None:
    cn = connect(p)
    try:
        cur = cn.cursor()
        cur.execute(
            """
            SELECT TOP (?) TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE IN ('BASE TABLE','VIEW')
              AND (TABLE_NAME LIKE ? OR ? = '%')
            ORDER BY TABLE_SCHEMA, TABLE_NAME
            """,
            limit,
            like,
            like,
        )
        tables = rows_to_dicts(cur)
        print(json.dumps({"ok": True, "count": len(tables), "tables": tables}, indent=2))
    finally:
        cn.close()


def cmd_columns(p: Dict[str, Any], table: str) -> None:
    schema, name = ("dbo", table)
    if "." in table:
        schema, name = table.split(".", 1)
    cn = connect(p)
    try:
        cur = cn.cursor()
        cur.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
            """,
            schema,
            name,
        )
        print(json.dumps({"ok": True, "table": f"{schema}.{name}", "columns": rows_to_dicts(cur)}, indent=2))
    finally:
        cn.close()


def write_excel(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from openpyxl import Workbook
    except ImportError as e:
        raise SystemExit("openpyxl required for Excel export: pip install openpyxl") from e
    wb = Workbook()
    ws = wb.active
    ws.title = "query"
    if not rows:
        ws.append(["(no rows)"])
    else:
        headers = list(rows[0].keys())
        ws.append(headers)
        for r in rows:
            ws.append([r.get(h) for h in headers])
    wb.save(path)


def cmd_sql(
    p: Dict[str, Any],
    sql: str,
    out: Optional[Path],
    excel: Optional[Path],
    limit: int,
) -> None:
    sql = assert_readonly(sql)
    cn = connect(p)
    try:
        cur = cn.cursor()
        cur.execute(sql)
        data = rows_to_dicts(cur)
        if limit and len(data) > limit:
            data = data[:limit]
        payload = {"ok": True, "row_count": len(data), "sql": sql, "rows": data}
        wrote: Dict[str, Any] = {"ok": True, "row_count": payload["row_count"]}
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            wrote["json"] = str(out)
        if excel:
            write_excel(excel, data)
            wrote["excel"] = str(excel)
        if out or excel:
            print(json.dumps(wrote, indent=2))
        else:
            print(json.dumps(payload, indent=2, default=str))
    finally:
        cn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="AR QA read-only SQL helper")
    ap.add_argument("--host")
    ap.add_argument("--database")
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--port")
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--catalog", action="store_true")
    ap.add_argument("--like", default="%")
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--columns", metavar="SCHEMA.TABLE_OR_TABLE")
    ap.add_argument("--sql")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--excel", type=Path, help="Write result rows to .xlsx")
    args = ap.parse_args()
    p = load_profile(args)
    if args.ping:
        cmd_ping(p)
    elif args.catalog:
        cmd_catalog(p, args.like, args.limit)
    elif args.columns:
        cmd_columns(p, args.columns)
    elif args.sql:
        cmd_sql(p, args.sql, args.out, args.excel, args.limit)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
