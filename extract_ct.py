#!/usr/bin/env python3
"""
Extract Cycle Time Data to CSV
Queries cycle_times table from PostgreSQL and exports to CSV for Excel analysis.

Usage:
    python3.12 extract_ct.py --sequences 50 51 --time 8h
    python3.12 extract_ct.py --sequences 50 51 --from "2026-02-10 06:00" --to "2026-02-10 14:00"
    python3.12 extract_ct.py --sequences 50 51 --time 24h --output my_data.csv
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta

import psycopg2


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config", "collector_config.json")
DEFAULT_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "reports")


def load_db_config() -> dict:
    """Load database credentials from collector_config.json."""
    if not os.path.exists(CONFIG_PATH):
        print(f"ERROR: Config file not found: {CONFIG_PATH}")
        print("Make sure you're running from the DataCapture/ directory.")
        sys.exit(1)

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    db = config.get("database", {})
    return {
        "host": db.get("host", "localhost"),
        "port": db.get("port", 5432),
        "database": db.get("database", "production"),
        "user": db.get("user", "collector"),
        "password": db.get("password", ""),
    }


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

TIME_PATTERN = re.compile(r"^(\d+)\s*(m|h|d)$", re.IGNORECASE)


def parse_lookback(value: str) -> timedelta:
    """Parse a lookback string like '8h', '30m', '2d' into a timedelta."""
    match = TIME_PATTERN.match(value.strip())
    if not match:
        print(f"ERROR: Invalid time format '{value}'. Use e.g. 30m, 8h, 2d")
        sys.exit(1)

    amount = int(match.group(1))
    unit = match.group(2).lower()

    if unit == "m":
        return timedelta(minutes=amount)
    elif unit == "h":
        return timedelta(hours=amount)
    elif unit == "d":
        return timedelta(days=amount)


def parse_datetime(value: str) -> datetime:
    """Parse a datetime string in common formats."""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    print(f"ERROR: Cannot parse datetime '{value}'.")
    print("Accepted formats: '2026-02-10 06:00:00', '2026-02-10 06:00', '2026-02-10'")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Query & export
# ---------------------------------------------------------------------------

def extract_cycle_times(
    sequences: list[int],
    time_from: datetime,
    time_to: datetime,
    output_path: str,
) -> int:
    """Query cycle_times and write results to CSV. Returns row count."""

    db_config = load_db_config()

    query = """
        WITH ranked AS (
            SELECT
                ct.time,
                ct.sequence_id,
                s.sequence_name,
                ct.cycle_time_seconds,
                ct.desired_cycle_time_seconds,
                ct.deviation_seconds,
                ct.deviation_percent,
                LAG(ct.cycle_time_seconds) OVER (
                    PARTITION BY ct.sequence_id ORDER BY ct.time
                ) AS prev_cycle_time
            FROM cycle_times ct
            LEFT JOIN sequences s ON ct.sequence_id = s.sequence_id
            WHERE ct.sequence_id = ANY(%s)
              AND ct.time >= %s
              AND ct.time <= %s
        )
        SELECT
            time,
            sequence_id,
            sequence_name,
            cycle_time_seconds,
            desired_cycle_time_seconds,
            deviation_seconds,
            deviation_percent
        FROM ranked
        WHERE prev_cycle_time IS NULL
           OR cycle_time_seconds != prev_cycle_time
        ORDER BY time ASC, sequence_id ASC;
    """

    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        cur.execute(query, (sequences, time_from, time_to))
        rows = cur.fetchall()
    except psycopg2.OperationalError as e:
        print(f"ERROR: Database connection failed:\n  {e}")
        sys.exit(1)
    finally:
        if "cur" in locals():
            cur.close()
        if "conn" in locals():
            conn.close()

    if not rows:
        print("No data found for the given sequences and time range.")
        return 0

    # Write CSV
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    headers = [
        "time",
        "sequence_id",
        "sequence_name",
        "cycle_time_seconds",
        "desired_cycle_time_seconds",
        "deviation_seconds",
        "deviation_percent",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)

    return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_output_filename(sequences: list[int], time_label: str) -> str:
    """Generate a default output filename."""
    seq_str = "_".join(str(s) for s in sequences)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"cycle_times_seq{seq_str}_{time_label}_{timestamp}.csv"


def main():
    parser = argparse.ArgumentParser(
        description="Extract cycle time data from PostgreSQL to CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3.12 extract_ct.py --sequences 50 51 --time 8h
  python3.12 extract_ct.py --sequences 50 51 --from "2026-02-10 06:00" --to "2026-02-10 14:00"
  python3.12 extract_ct.py --sequences 50 51 --time 24h --output my_data.csv
        """,
    )
    parser.add_argument(
        "--sequences", "-s",
        nargs="+",
        type=int,
        required=True,
        help="Sequence IDs to extract (e.g. 50 51 52)",
    )
    parser.add_argument(
        "--time", "-t",
        type=str,
        default=None,
        help="Lookback period from now (e.g. 30m, 8h, 2d)",
    )
    parser.add_argument(
        "--from",
        dest="time_from",
        type=str,
        default=None,
        help="Start datetime (e.g. '2026-02-10 06:00')",
    )
    parser.add_argument(
        "--to",
        dest="time_to",
        type=str,
        default=None,
        help="End datetime (e.g. '2026-02-10 14:00')",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output CSV file path (default: reports/cycle_times_seq...csv)",
    )

    args = parser.parse_args()

    # --- Resolve time range ---
    now = datetime.now()

    if args.time and (args.time_from or args.time_to):
        print("ERROR: Use either --time OR --from/--to, not both.")
        sys.exit(1)

    if args.time:
        delta = parse_lookback(args.time)
        time_from = now - delta
        time_to = now
        time_label = args.time.strip()
    elif args.time_from and args.time_to:
        time_from = parse_datetime(args.time_from)
        time_to = parse_datetime(args.time_to)
        time_label = "custom"
    elif args.time_from or args.time_to:
        print("ERROR: --from and --to must be used together.")
        sys.exit(1)
    else:
        print("ERROR: Provide either --time or --from/--to.")
        sys.exit(1)

    # --- Resolve output path ---
    if args.output:
        output_path = args.output
        # If just a filename (no directory), put it in reports/
        if not os.path.dirname(output_path):
            output_path = os.path.join(DEFAULT_OUTPUT_DIR, output_path)
    else:
        filename = build_output_filename(args.sequences, time_label)
        output_path = os.path.join(DEFAULT_OUTPUT_DIR, filename)

    # --- Run ---
    print(f"Extracting cycle times...")
    print(f"  Sequences : {args.sequences}")
    print(f"  From      : {time_from.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  To        : {time_to.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Output    : {output_path}")
    print()

    row_count = extract_cycle_times(args.sequences, time_from, time_to, output_path)

    if row_count > 0:
        print(f"✔ Exported {row_count:,} rows to {output_path}")
    else:
        print("No CSV file created (no data).")


if __name__ == "__main__":
    main()
