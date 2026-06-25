"""
Azure Functions v2 — DBA Azure Project
Triggers:
  Timer  — ETL (CRON 0 0 0,12 * * *  UTC, twice daily)
  HTTP   — REST API (5 endpoints)
"""

import json
import logging
import re
import sys
import os
import time
from collections import defaultdict

import azure.functions as func

sys.path.insert(0, os.path.dirname(__file__))
from api.db import query

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security: Input validation
# ---------------------------------------------------------------------------

# CMS Facility IDs are 6-10 alphanumeric characters
_FACILITY_ID_RE = re.compile(r"^[A-Z0-9]{6,10}$")
_MEASURE_ID_RE   = re.compile(r"^[A-Za-z0-9_]{1,50}$")

# Valid US state/territory abbreviations (CMS dataset)
_VALID_STATES = frozenset({
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL",
    "GA", "GU", "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA",
    "MA", "MD", "ME", "MI", "MN", "MO", "MP", "MS", "MT", "NC",
    "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR",
    "PA", "PR", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VI",
    "VT", "WA", "WI", "WV", "WY",
})


# ---------------------------------------------------------------------------
# Security: Rate limiting (in-memory, best-effort for single-instance Functions)
# ---------------------------------------------------------------------------

_RATE_LIMIT_WINDOW = 60      # seconds
_RATE_LIMIT_MAX     = 60     # requests per window per IP
_rate_buckets: defaultdict[str, list[float]] = defaultdict(list)


def _check_rate_limit(req: func.HttpRequest) -> bool:
    """Return True if the request is within rate limits."""
    ip = req.headers.get("X-Forwarded-For", "").split(",")[0].strip() or "unknown"
    now = time.monotonic()
    bucket = _rate_buckets[ip]

    # Purge expired entries
    cutoff = now - _RATE_LIMIT_WINDOW
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)

    if len(bucket) >= _RATE_LIMIT_MAX:
        return False

    bucket.append(now)
    return True


# ---------------------------------------------------------------------------
# Security: Response helpers with security headers
# ---------------------------------------------------------------------------

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-RateLimit-Limit": str(_RATE_LIMIT_MAX),
    "X-RateLimit-Remaining": "0",  # overridden in _ok / _err after check
    "Cache-Control": "no-store",
}

def _security_response(body: str, status: int) -> func.HttpResponse:
    return func.HttpResponse(
        body,
        status_code=status,
        mimetype="application/json",
        headers=dict(_SECURITY_HEADERS),
    )

def _internal_error(exc: Exception) -> func.HttpResponse:
    """Log the real error; return a sanitized response to the client."""
    log.exception("Internal error")
    return func.HttpResponse(
        json.dumps({"error": "INTERNAL_ERROR", "message": "An unexpected error occurred.", "status": 500}),
        status_code=500,
        mimetype="application/json",
        headers=dict(_SECURITY_HEADERS),
    )


# ---------------------------------------------------------------------------
# Security: Input validators
# ---------------------------------------------------------------------------

def _validate_facility_id(fid: str) -> str | None:
    """Return sanitized facility_id or None if invalid."""
    fid = fid.strip()
    if not _FACILITY_ID_RE.match(fid):
        return None
    return fid


def _validate_measure_id(mid: str) -> str | None:
    """Return sanitized measure_id or None if invalid."""
    mid = mid.strip()
    if not _MEASURE_ID_RE.match(mid):
        return None
    return mid


def _validate_state(s: str) -> str | None:
    """Return sanitized 2-letter state code or None if invalid."""
    s = s.strip().upper()
    if s not in _VALID_STATES:
        return None
    return s


# ---------------------------------------------------------------------------
# Timer Trigger — ETL (00:00 and 12:00 UTC daily)
# ---------------------------------------------------------------------------

@app.timer_trigger(schedule="0 0 0,12 * * *", arg_name="timer", run_on_startup=False)
def etl_timer(timer: func.TimerRequest) -> None:
    log.info("ETL timer trigger fired. past_due=%s", timer.past_due)
    from etl.etl_runner import run_etl
    run_etl()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(data, status: int = 200) -> func.HttpResponse:
    return _security_response(json.dumps(data, default=str), status)


def _err(code: str, message: str, status: int) -> func.HttpResponse:
    return _security_response(
        json.dumps({"error": code, "message": message, "status": status}),
        status,
    )


def _int(val, default: int, min_v: int = 1, max_v: int = 10_000) -> int:
    try:
        return max(min_v, min(int(val), max_v))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# GET /api/hospitals
# ---------------------------------------------------------------------------

@app.route(route="hospitals", methods=["GET"])
def get_hospitals(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_rate_limit(req):
        return _err("RATE_LIMITED", "Too many requests. Try again later.", 429)

    state     = _validate_state(req.params.get("state", "")) if req.params.get("state") else None
    emergency = req.params.get("emergency", "").upper().strip() or None
    rating    = req.params.get("rating")
    limit     = _int(req.params.get("limit"), 20, 1, 500)
    offset    = _int(req.params.get("offset"), 0, 0, 1_000_000)

    where_clauses = []
    params: list = []

    if state:
        where_clauses.append("RTRIM(State) = ?")
        params.append(state[:2])
    if emergency in ("Y", "N"):
        where_clauses.append("RTRIM(EmergencyServices) = ?")
        params.append(emergency)
    if rating is not None:
        try:
            where_clauses.append("OverallRating >= ?")
            params.append(int(rating))
        except ValueError:
            return _err("INVALID_PARAM", "'rating' must be an integer 1-5", 400)

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    count_sql = f"SELECT COUNT(*) AS total FROM dbo.Hospital {where}"
    data_sql = f"""
        SELECT FacilityID, FacilityName, Address, City, RTRIM(State) AS State,
               ZipCode, Phone, HospitalType,
               RTRIM(EmergencyServices) AS EmergencyServices, OverallRating,
               Latitude, Longitude
        FROM dbo.Hospital
        {where}
        ORDER BY FacilityName
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
    """

    try:
        total = query(count_sql, tuple(params))[0]["total"]
        rows  = query(data_sql, tuple(params) + (offset, limit))
    except Exception as exc:
        log.exception("get_hospitals failed")
        return _internal_error(exc)

    return _ok({"total": total, "limit": limit, "offset": offset, "data": rows})


# ---------------------------------------------------------------------------
# GET /api/hospitals/{facility_id}
# ---------------------------------------------------------------------------

@app.route(route="hospitals/{facility_id}", methods=["GET"])
def get_hospital_detail(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_rate_limit(req):
        return _err("RATE_LIMITED", "Too many requests. Try again later.", 429)

    fid = _validate_facility_id(req.route_params.get("facility_id", ""))
    if not fid:
        return _err("INVALID_PARAM", "facility_id must be 6-10 alphanumeric characters", 400)

    sql = """
        SELECT FacilityID, FacilityName, Address, City,
               RTRIM(State) AS State, ZipCode, Phone, HospitalType,
               RTRIM(EmergencyServices) AS EmergencyServices,
               OverallRating, Latitude, Longitude, UpdatedAt
        FROM dbo.Hospital
        WHERE FacilityID = ?
    """
    try:
        rows = query(sql, (fid,))
    except Exception as exc:
        log.exception("get_hospital_detail failed")
        return _internal_error(exc)

    if not rows:
        return _err("NOT_FOUND", f"Hospital '{fid}' not found.", 404)

    return _ok(rows[0])


# ---------------------------------------------------------------------------
# GET /api/hospitals/{facility_id}/metrics
# ---------------------------------------------------------------------------

@app.route(route="hospitals/{facility_id}/metrics", methods=["GET"])
def get_hospital_metrics(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_rate_limit(req):
        return _err("RATE_LIMITED", "Too many requests. Try again later.", 429)

    fid = _validate_facility_id(req.route_params.get("facility_id", ""))
    if not fid:
        return _err("INVALID_PARAM", "facility_id must be 6-10 alphanumeric characters", 400)

    raw_mid = req.params.get("measure_id", "").strip()
    measure_id = _validate_measure_id(raw_mid) if raw_mid else None
    if raw_mid and not measure_id:
        return _err("INVALID_PARAM", "measure_id must be 1-50 alphanumeric/underscore characters", 400)

    limit = _int(req.params.get("limit"), 10, 1, 200)

    # Verify hospital exists
    try:
        exists = query("SELECT 1 FROM dbo.Hospital WHERE FacilityID = ?", (fid,))
    except Exception as exc:
        log.exception("metrics: hospital lookup failed")
        return _internal_error(exc)

    if not exists:
        return _err("NOT_FOUND", f"Hospital '{fid}' not found.", 404)

    where = "WHERE m.FacilityID = ?"
    params: list = [fid]
    if measure_id:
        where += " AND m.MeasureID = ?"
        params.append(measure_id)

    sql = f"""
        SELECT TOP (?)
            m.MeasureID, m.MeasureName, m.Score,
            m.NumberOfPatients, m.NumberReturned,
            m.ComparedToNational, m.PeriodStart, m.PeriodEnd,
            m.CollectedAt
        FROM dbo.HospitalVisitMetrics m
        {where}
        ORDER BY m.CollectedAt DESC
    """
    try:
        rows = query(sql, (limit,) + tuple(params))
    except Exception as exc:
        log.exception("get_hospital_metrics failed")
        return _internal_error(exc)

    return _ok({"facility_id": fid, "count": len(rows), "metrics": rows})


# ---------------------------------------------------------------------------
# GET /api/states/summary
# ---------------------------------------------------------------------------

@app.route(route="states/summary", methods=["GET"])
def get_states_summary(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_rate_limit(req):
        return _err("RATE_LIMITED", "Too many requests. Try again later.", 429)
    sql = """
        SELECT
            RTRIM(State)                                    AS state,
            COUNT(*)                                        AS total_hospitals,
            SUM(CASE WHEN RTRIM(EmergencyServices)='Y' THEN 1 ELSE 0 END)
                                                            AS with_emergency,
            CAST(AVG(CAST(OverallRating AS FLOAT)) AS DECIMAL(4,2))
                                                            AS avg_rating,
            SUM(CASE WHEN OverallRating = 5 THEN 1 ELSE 0 END)
                                                            AS top_rated_count
        FROM dbo.Hospital
        WHERE State IS NOT NULL
        GROUP BY RTRIM(State)
        ORDER BY total_hospitals DESC
    """
    try:
        rows = query(sql)
    except Exception as exc:
        log.exception("get_states_summary failed")
        return _internal_error(exc)

    return _ok({"count": len(rows), "data": rows})


# ---------------------------------------------------------------------------
# GET /api/metrics/top
# ---------------------------------------------------------------------------

@app.route(route="metrics/top", methods=["GET"])
def get_metrics_top(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_rate_limit(req):
        return _err("RATE_LIMITED", "Too many requests. Try again later.", 429)

    raw_mid = req.params.get("measure_id", "").strip()
    measure_id = _validate_measure_id(raw_mid)
    if not measure_id:
        return _err("INVALID_PARAM", "measure_id must be 1-50 alphanumeric/underscore characters", 400)

    raw_state = req.params.get("state", "").strip()
    state = _validate_state(raw_state) if raw_state else None
    if raw_state and not state:
        return _err("INVALID_PARAM", f"Invalid state code: '{raw_state[:2]}'", 400)

    limit = _int(req.params.get("limit"), 10, 1, 100)

    where = "WHERE m.MeasureID = ? AND m.Score IS NOT NULL"
    params: list = [measure_id]
    if state:
        where += " AND RTRIM(h.State) = ?"
        params.append(state[:2])

    sql = f"""
        SELECT TOP (?)
            h.FacilityID, h.FacilityName,
            RTRIM(h.State) AS State, h.City,
            m.Score, m.ComparedToNational,
            m.NumberOfPatients, m.PeriodEnd
        FROM dbo.HospitalVisitMetrics m
        JOIN dbo.Hospital h ON h.FacilityID = m.FacilityID
        {where}
        ORDER BY m.Score ASC
    """
    try:
        rows = query(sql, (limit,) + tuple(params))
    except Exception as exc:
        log.exception("get_metrics_top failed")
        return _internal_error(exc)

    return _ok({
        "measure_id": measure_id,
        "state_filter": state,
        "count": len(rows),
        "data": rows,
    })


# ---------------------------------------------------------------------------
# GET /api/metrics/export  — bulk hospital+metrics for CSV download
# ---------------------------------------------------------------------------

@app.route(route="metrics/export", methods=["GET"])
def get_metrics_export(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_rate_limit(req):
        return _err("RATE_LIMITED", "Too many requests. Try again later.", 429)

    raw_state = req.params.get("state", "").strip()
    state = _validate_state(raw_state) if raw_state else None
    if raw_state and not state:
        return _err("INVALID_PARAM", f"Invalid state code: '{raw_state[:2]}'", 400)

    limit  = _int(req.params.get("limit"), 1000, 1, 2000)
    offset = _int(req.params.get("offset"), 0, 0, 10_000_000)

    where_parts = []
    params: list = []
    if state:
        where_parts.append("RTRIM(h.State) = ?")
        params.append(state[:2])

    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    count_sql = f"""
        SELECT COUNT(*) AS total
        FROM dbo.HospitalVisitMetrics m
        JOIN dbo.Hospital h ON h.FacilityID = m.FacilityID
        {where}
    """
    data_sql = f"""
        SELECT
            h.FacilityID, h.FacilityName, RTRIM(h.State) AS State, h.City,
            h.HospitalType, RTRIM(h.EmergencyServices) AS EmergencyServices,
            h.OverallRating,
            m.MeasureID, m.MeasureName, m.Score, m.ComparedToNational,
            m.NumberOfPatients, m.PeriodStart, m.PeriodEnd
        FROM dbo.HospitalVisitMetrics m
        JOIN dbo.Hospital h ON h.FacilityID = m.FacilityID
        {where}
        ORDER BY h.FacilityName, m.MeasureID
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
    """
    try:
        total = query(count_sql, tuple(params))[0]["total"]
        rows  = query(data_sql, tuple(params) + (offset, limit))
    except Exception as exc:
        log.exception("get_metrics_export failed")
        return _internal_error(exc)

    return _ok({"total": total, "limit": limit, "offset": offset, "data": rows})
