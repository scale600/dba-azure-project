"""
ETL Runner — CMS Hospital data → Azure SQL HospitalDB

Usage (local):
    python3.11 etl/etl_runner.py

Azure Function entry point: see function_app.py (Phase 5)

Secrets: DB_CONNECTION_STRING from environment (.env locally, Key Vault in prod)
"""

import os
import sys
import time
import logging

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# App Insights telemetry (optional — skipped if key not set)
try:
    from applicationinsights import TelemetryClient
    _ai_key = os.getenv("APPINSIGHTS_INSTRUMENTATIONKEY", "")
    _tc: TelemetryClient | None = TelemetryClient(_ai_key) if _ai_key else None
except ImportError:
    _tc = None

log = logging.getLogger(__name__)

def _track_event(name: str, props: dict):
    if _tc:
        _tc.track_event(name, props)
        _tc.flush()

from etl.cms_client import fetch_hospitals, fetch_visit_metrics
from etl.db_client import (
    get_connection, upsert_hospitals, upsert_metrics,
    log_start, log_end
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _get_conn_str() -> str:
    conn_str = os.getenv("DB_CONNECTION_STRING")
    if conn_str:
        return conn_str

    kv_url = os.getenv("AZURE_KEY_VAULT_URL")
    if kv_url:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
        client = SecretClient(vault_url=kv_url, credential=DefaultAzureCredential())
        return client.get_secret("DB-CONNECTION-STRING").value

    raise EnvironmentError("Set DB_CONNECTION_STRING or AZURE_KEY_VAULT_URL")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_etl():
    # Load .env for local dev
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    conn_str = _get_conn_str()
    conn = get_connection(conn_str)
    log_id = log_start(conn)
    print(f"ETL started  (LogID={log_id})")

    hospitals_loaded = 0
    metrics_loaded   = 0

    try:
        # ---- Phase 1: Hospital table ----
        raw_hospitals = fetch_hospitals()
        print(f"CMS returned {len(raw_hospitals)} hospital records")

        cursor = conn.cursor()
        t0 = time.time()
        hospitals_loaded = upsert_hospitals(cursor, raw_hospitals)
        conn.commit()
        print(f"Hospitals upserted: {hospitals_loaded}  ({time.time()-t0:.1f}s)")
        cursor.close()

        # ---- Phase 2: HospitalVisitMetrics table ----
        raw_metrics = fetch_visit_metrics()
        print(f"CMS returned {len(raw_metrics)} visit metric records")

        cursor = conn.cursor()
        t0 = time.time()
        metrics_loaded = upsert_metrics(cursor, raw_metrics)
        conn.commit()
        print(f"Metrics upserted:   {metrics_loaded}  ({time.time()-t0:.1f}s)")
        cursor.close()

        log_end(conn, log_id, hospitals_loaded, metrics_loaded, "SUCCESS")
        print(f"\nETL complete — hospitals:{hospitals_loaded}  metrics:{metrics_loaded}")
        _track_event("ETL_Success", {
            "log_id": str(log_id),
            "hospitals_loaded": str(hospitals_loaded),
            "metrics_loaded": str(metrics_loaded),
        })

    except Exception as exc:
        conn.rollback()
        log_end(conn, log_id, hospitals_loaded, metrics_loaded, "FAILED", str(exc)[:4000])
        print(f"\nETL FAILED: {exc}", file=sys.stderr)
        _track_event("ETL_Failed", {
            "log_id": str(log_id),
            "error": str(exc)[:500],
        })
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run_etl()
