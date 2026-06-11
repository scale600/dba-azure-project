"""
Azure Functions v2 — DBA Azure Project REST API
All HTTP triggers in a single file (Python programming model v2).

Endpoints:
  GET /api/hospitals                       list + filter + pagination
  GET /api/hospitals/{facility_id}         single hospital detail
  GET /api/hospitals/{facility_id}/metrics metrics history
  GET /api/states/summary                  aggregate per state
  GET /api/metrics/top                     ranked hospitals by score
"""

import json
import logging
import sys
import os

import azure.functions as func

sys.path.insert(0, os.path.dirname(__file__))
from api.db import query

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(data, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=status,
        mimetype="application/json",
    )


def _err(code: str, message: str, status: int) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"error": code, "message": message, "status": status}),
        status_code=status,
        mimetype="application/json",
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
    state     = req.params.get("state", "").upper().strip() or None
    emergency = req.params.get("emergency", "").upper().strip() or None
    rating    = req.params.get("rating")
    limit     = _int(req.params.get("limit"), 20, 1, 100)
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
        SELECT FacilityID, FacilityName, City, RTRIM(State) AS State,
               RTRIM(EmergencyServices) AS EmergencyServices, OverallRating,
               HospitalType
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
        return _err("INTERNAL_ERROR", str(exc), 500)

    return _ok({"total": total, "limit": limit, "offset": offset, "data": rows})


# ---------------------------------------------------------------------------
# GET /api/hospitals/{facility_id}
# ---------------------------------------------------------------------------

@app.route(route="hospitals/{facility_id}", methods=["GET"])
def get_hospital_detail(req: func.HttpRequest) -> func.HttpResponse:
    fid = req.route_params.get("facility_id", "").strip()
    if not fid:
        return _err("INVALID_PARAM", "facility_id is required", 400)

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
        return _err("INTERNAL_ERROR", str(exc), 500)

    if not rows:
        return _err("NOT_FOUND", f"Hospital '{fid}' not found.", 404)

    return _ok(rows[0])


# ---------------------------------------------------------------------------
# GET /api/hospitals/{facility_id}/metrics
# ---------------------------------------------------------------------------

@app.route(route="hospitals/{facility_id}/metrics", methods=["GET"])
def get_hospital_metrics(req: func.HttpRequest) -> func.HttpResponse:
    fid        = req.route_params.get("facility_id", "").strip()
    measure_id = req.params.get("measure_id", "").strip() or None
    limit      = _int(req.params.get("limit"), 10, 1, 200)

    if not fid:
        return _err("INVALID_PARAM", "facility_id is required", 400)

    # Verify hospital exists
    try:
        exists = query("SELECT 1 FROM dbo.Hospital WHERE FacilityID = ?", (fid,))
    except Exception as exc:
        log.exception("metrics: hospital lookup failed")
        return _err("INTERNAL_ERROR", str(exc), 500)

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
        return _err("INTERNAL_ERROR", str(exc), 500)

    return _ok({"facility_id": fid, "count": len(rows), "metrics": rows})


# ---------------------------------------------------------------------------
# GET /api/states/summary
# ---------------------------------------------------------------------------

@app.route(route="states/summary", methods=["GET"])
def get_states_summary(req: func.HttpRequest) -> func.HttpResponse:
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
        return _err("INTERNAL_ERROR", str(exc), 500)

    return _ok({"count": len(rows), "data": rows})


# ---------------------------------------------------------------------------
# GET /api/metrics/top
# ---------------------------------------------------------------------------

@app.route(route="metrics/top", methods=["GET"])
def get_metrics_top(req: func.HttpRequest) -> func.HttpResponse:
    measure_id = req.params.get("measure_id", "").strip()
    state      = req.params.get("state", "").upper().strip() or None
    limit      = _int(req.params.get("limit"), 10, 1, 100)

    if not measure_id:
        return _err("INVALID_PARAM", "'measure_id' query parameter is required", 400)

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
        return _err("INTERNAL_ERROR", str(exc), 500)

    return _ok({
        "measure_id": measure_id,
        "state_filter": state,
        "count": len(rows),
        "data": rows,
    })
