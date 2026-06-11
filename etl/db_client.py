"""
Database operations for HospitalDB.
Uses MERGE upsert to avoid duplicates on repeated ETL runs.
"""

import pyodbc
from datetime import datetime


def get_connection(conn_str: str) -> pyodbc.Connection:
    conn = pyodbc.connect(conn_str, timeout=30)
    conn.autocommit = False
    return conn


# ---------------------------------------------------------------------------
# Hospital MERGE
# ---------------------------------------------------------------------------

def _safe_str(val, maxlen=None):
    if val is None or str(val).strip() in ("", "N/A", "Not Available"):
        return None
    s = str(val).strip()
    return s[:maxlen] if maxlen else s


def _safe_int(val):
    try:
        v = int(float(str(val).strip()))
        return v if 1 <= v <= 5 else None
    except (ValueError, TypeError):
        return None


def _safe_decimal(val):
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None


def _map_emergency(val):
    v = _safe_str(val)
    if v and v.upper().startswith("Y"):
        return "Y"
    if v and v.upper().startswith("N"):
        return "N"
    return None


HOSPITAL_MERGE = """
MERGE dbo.Hospital AS tgt
USING (VALUES (?,?,?,?,?,?,?,?,?,?,?,?)) AS src
    (FacilityID, FacilityName, Address, City, State, ZipCode,
     Phone, HospitalType, EmergencyServices, OverallRating, Latitude, Longitude)
ON tgt.FacilityID = src.FacilityID
WHEN MATCHED THEN
    UPDATE SET
        FacilityName      = src.FacilityName,
        Address           = src.Address,
        City              = src.City,
        State             = src.State,
        ZipCode           = src.ZipCode,
        Phone             = src.Phone,
        HospitalType      = src.HospitalType,
        EmergencyServices = src.EmergencyServices,
        OverallRating     = src.OverallRating,
        Latitude          = src.Latitude,
        Longitude         = src.Longitude,
        UpdatedAt         = GETDATE()
WHEN NOT MATCHED THEN
    INSERT (FacilityID, FacilityName, Address, City, State, ZipCode,
            Phone, HospitalType, EmergencyServices, OverallRating, Latitude, Longitude)
    VALUES (src.FacilityID, src.FacilityName, src.Address, src.City, src.State, src.ZipCode,
            src.Phone, src.HospitalType, src.EmergencyServices, src.OverallRating,
            src.Latitude, src.Longitude);
"""


def upsert_hospitals(cursor: pyodbc.Cursor, records: list[dict]) -> int:
    params = []
    for r in records:
        fid = _safe_str(r.get("facility_id"), 10)
        if not fid:
            continue
        params.append((
            fid,
            _safe_str(r.get("facility_name"), 200),
            _safe_str(r.get("address"), 200),
            _safe_str(r.get("city"), 100),
            _safe_str(r.get("state"), 2),
            _safe_str(r.get("zip_code"), 10),
            _safe_str(r.get("phone"), 20),
            _safe_str(r.get("hospital_type"), 100),
            _map_emergency(r.get("emergency_services")),
            _safe_int(r.get("hospital_overall_rating")),
            _safe_decimal(r.get("lat")),
            _safe_decimal(r.get("lng")),
        ))

    cursor.fast_executemany = True
    cursor.executemany(HOSPITAL_MERGE, params)
    return len(params)


# ---------------------------------------------------------------------------
# HospitalVisitMetrics MERGE
# ---------------------------------------------------------------------------

def _safe_date(val):
    if not val:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(val).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _safe_compared(val):
    if not val:
        return None
    v = str(val).strip()
    allowed = {"Better", "Same", "Worse", "Not Available"}
    return v if v in allowed else None


METRICS_MERGE = """
MERGE dbo.HospitalVisitMetrics AS tgt
USING (VALUES (?,?,?,?,?,?,?,?,?)) AS src
    (FacilityID, MeasureID, MeasureName, Score,
     NumberOfPatients, NumberReturned, ComparedToNational, PeriodStart, PeriodEnd)
ON  tgt.FacilityID = src.FacilityID
AND tgt.MeasureID  = src.MeasureID
AND tgt.PeriodEnd  = src.PeriodEnd
WHEN MATCHED THEN
    UPDATE SET
        MeasureName        = src.MeasureName,
        Score              = src.Score,
        NumberOfPatients   = src.NumberOfPatients,
        NumberReturned     = src.NumberReturned,
        ComparedToNational = src.ComparedToNational,
        PeriodStart        = src.PeriodStart,
        CollectedAt        = GETDATE()
WHEN NOT MATCHED THEN
    INSERT (FacilityID, MeasureID, MeasureName, Score,
            NumberOfPatients, NumberReturned, ComparedToNational, PeriodStart, PeriodEnd)
    VALUES (src.FacilityID, src.MeasureID, src.MeasureName, src.Score,
            src.NumberOfPatients, src.NumberReturned, src.ComparedToNational,
            src.PeriodStart, src.PeriodEnd);
"""


def upsert_metrics(cursor: pyodbc.Cursor, records: list[dict]) -> int:
    # Only process records whose FacilityID exists in Hospital
    cursor.execute("SELECT FacilityID FROM dbo.Hospital")
    valid_ids = {row[0] for row in cursor.fetchall()}

    params = []
    for r in records:
        fid = _safe_str(r.get("facility_id"), 10)
        mid = _safe_str(r.get("measure_id"), 50)
        if not fid or not mid or fid not in valid_ids:
            continue

        score_raw = r.get("score")
        try:
            score = float(str(score_raw).strip()) if score_raw not in (None, "", "N/A", "Not Available") else None
        except (ValueError, TypeError):
            score = None

        params.append((
            fid,
            mid,
            _safe_str(r.get("measure_name"), 300),
            score,
            _safe_int(r.get("number_of_patients")),
            _safe_int(r.get("number_returned")),
            _safe_compared(r.get("compared_to_national")),
            _safe_date(r.get("start_date")),
            _safe_date(r.get("end_date")),
        ))

    cursor.fast_executemany = True
    cursor.executemany(METRICS_MERGE, params)
    return len(params)


# ---------------------------------------------------------------------------
# ETL_Log helpers
# ---------------------------------------------------------------------------

def log_start(conn: pyodbc.Connection) -> int:
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO dbo.ETL_Log (Status) OUTPUT INSERTED.LogID VALUES ('RUNNING')"
    )
    log_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    return log_id


def log_end(conn: pyodbc.Connection, log_id: int, hospitals: int,
            metrics: int, status: str, error: str = None):
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE dbo.ETL_Log
        SET RunEnd = GETDATE(),
            HospitalsLoaded = ?,
            MetricsLoaded   = ?,
            Status          = ?,
            ErrorMessage    = ?
        WHERE LogID = ?
        """,
        (hospitals, metrics, status, error, log_id)
    )
    conn.commit()
    cursor.close()
