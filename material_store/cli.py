"""Explicit migration/inspection commands; no production source writes."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["register", "inspect"])
    parser.add_argument("--dsn", default="dbname=pudu_materials")
    parser.add_argument("--schema", type=Path)
    args = parser.parse_args()
    import psycopg
    with psycopg.connect(args.dsn, autocommit=True) as conn:
        if args.command == "register":
            from .schema import register_schema
            if not args.schema:
                parser.error("register requires --schema")
            result = register_schema(conn, json.loads(args.schema.read_text(encoding="utf-8-sig")))
        else:
            result = {"tables": conn.execute("SELECT count(*) FROM material_meta.tables").fetchone()[0],
                      "fields": conn.execute("SELECT count(*) FROM material_meta.fields").fetchone()[0],
                      "projection_columns": conn.execute("""SELECT count(*) FROM information_schema.columns
                          WHERE table_schema='material_data' AND column_name LIKE 'f\\_%' ESCAPE '\\'""").fetchone()[0]}
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
