"""Measure warm, in-process Flask requests against disposable SQLite fixtures."""
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
from ui_audit_browser import fixture_pages
from test_workflows import Workflows


def main():
    Workflows.setUpClass()
    fixture = Workflows()
    fixture.setUp()
    try:
        sessions, pages = fixture_pages(fixture, Path(fixture.directory.name))
        wizard = next(path for path in pages["client"] if path.startswith("/client/briefs/") and path.endswith("/adaptive"))
        cases = [
            ("public", "/"), ("client", "/dashboard/client"), ("client", "/briefs"),
            ("client", wizard), ("client", wizard + "/save-state"), ("client", wizard + "/review"),
            ("client", "/notifications"), ("provider", "/dashboard/provider"),
            ("provider", pages["provider"][-1]), ("admin", "/admin/users"),
        ]
        original_connect = database.sqlite3.connect
        statements = []

        def connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(database.sqlite3, "connect", connect):
            print("role,path,requests,p50_ms,p95_ms,selects,account_selects")
            for role, path in cases:
                client = sessions[role]
                for _ in range(3):
                    with client.get(path) as response:
                        assert response.status_code == 200, (path, response.status_code)
                timings = []
                select_counts = []
                account_counts = []
                for _ in range(25):
                    statements.clear()
                    start = perf_counter()
                    with client.get(path) as response:
                        assert response.status_code == 200, (path, response.status_code)
                    timings.append((perf_counter() - start) * 1000)
                    select_counts.append(sum(sql.lstrip().upper().startswith("SELECT") for sql in statements))
                    account_counts.append(sum(sql.lstrip().startswith("SELECT id, full_name, email, role, status") for sql in statements))
                print(f"{role},{path},25,{median(timings):.2f},{sorted(timings)[23]:.2f},"
                      f"{median(select_counts):g},{median(account_counts):g}")
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
