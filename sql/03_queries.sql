-- =============================================================
-- 03_queries.sql  —  DBA Azure Project : Performance Tuning
-- Run after: 01_schema.sql, 02_indexes.sql
-- Recorded: 2026-06-11
-- =============================================================

USE HospitalDB;
GO

-- =============================================================
-- SECTION 1: Benchmark Queries — Before vs After Index
-- =============================================================
-- Results (min of 5 runs each, Serverless GP_S_Gen5_1, westus3)
--
-- State집계   PK_Scan (before)          21.9 ms
-- State집계   IX_Hospital_State (after) 20.7 ms   (-6%)
--
-- 이름검색    PK_Scan (before)          18.4 ms
-- 이름검색    IX_Hospital_Name (after)  15.9 ms   (-14%)
--
-- 병원메트릭  PK_Scan (before)          35.6 ms
-- 병원메트릭  IX_FacilityID_MeasureID   16.5 ms   (-54%)
--
-- National비교 PK_Scan (before)         36.9 ms
-- National비교 IX_ComparedToNational     15.7 ms   (-57%)
-- =============================================================

-- Q1: State-level hospital summary (REST API + Power BI)
-- Uses: IX_Hospital_State
SELECT
    RTRIM(State)                                                    AS State,
    COUNT(*)                                                        AS TotalHospitals,
    SUM(CASE WHEN RTRIM(EmergencyServices) = 'Y' THEN 1 ELSE 0 END) AS WithEmergency,
    CAST(AVG(CAST(OverallRating AS FLOAT)) AS DECIMAL(4,2))         AS AvgRating,
    SUM(CASE WHEN OverallRating = 5 THEN 1 ELSE 0 END)             AS TopRatedCount
FROM dbo.Hospital
WHERE State IS NOT NULL
GROUP BY RTRIM(State)
ORDER BY TotalHospitals DESC;
GO

-- Q2: Hospital name search with pagination (REST API /api/hospitals)
-- Uses: IX_Hospital_Name
DECLARE @Name   NVARCHAR(200) = 'CEDAR%';
DECLARE @Limit  INT = 20;
DECLARE @Offset INT = 0;

SELECT
    FacilityID, FacilityName, City,
    RTRIM(State) AS State,
    RTRIM(EmergencyServices) AS EmergencyServices,
    OverallRating, HospitalType
FROM dbo.Hospital
WHERE FacilityName LIKE @Name
ORDER BY FacilityName
OFFSET @Offset ROWS FETCH NEXT @Limit ROWS ONLY;
GO

-- Q3: Per-hospital metric history (REST API /api/hospitals/{id}/metrics)
-- Uses: IX_VisitMetrics_FacilityID_MeasureID
DECLARE @FacilityID NVARCHAR(10) = '050455';

SELECT TOP 20
    MeasureID, MeasureName, Score,
    NumberOfPatients, NumberReturned,
    ComparedToNational, PeriodStart, PeriodEnd,
    CollectedAt
FROM dbo.HospitalVisitMetrics
WHERE FacilityID = @FacilityID
ORDER BY CollectedAt DESC;
GO

-- Q4: National comparison filter (REST API /api/metrics/top + Power BI slicer)
-- Uses: IX_VisitMetrics_ComparedToNational
DECLARE @Compared  NVARCHAR(20) = 'Better';
DECLARE @MeasureID NVARCHAR(50) = 'EDAC_30_AMI';

SELECT TOP 50
    h.FacilityID, h.FacilityName,
    RTRIM(h.State) AS State, h.City,
    m.Score, m.ComparedToNational,
    m.NumberOfPatients, m.PeriodEnd
FROM dbo.HospitalVisitMetrics m
JOIN dbo.Hospital h ON h.FacilityID = m.FacilityID
WHERE m.ComparedToNational = @Compared
  AND m.MeasureID = @MeasureID
ORDER BY m.Score ASC;
GO

-- Q5: Date-range trend analysis
-- Uses: IX_VisitMetrics_CollectedAt
SELECT
    RTRIM(h.State) AS State,
    m.MeasureID,
    AVG(m.Score) AS AvgScore,
    COUNT(*) AS RecordCount
FROM dbo.HospitalVisitMetrics m
JOIN dbo.Hospital h ON h.FacilityID = m.FacilityID
WHERE m.CollectedAt >= DATEADD(DAY, -365, GETDATE())
  AND m.Score IS NOT NULL
GROUP BY RTRIM(h.State), m.MeasureID
ORDER BY RTRIM(h.State), m.MeasureID;
GO

-- Q6: Top hospitals by measure score (REST API /api/metrics/top)
-- Uses: IX_VisitMetrics_MeasureID_Score  ← DMV-recommended (added 2026-06-11)
DECLARE @Measure NVARCHAR(50) = 'EDAC_30_AMI';

SELECT TOP 10
    h.FacilityID, h.FacilityName,
    RTRIM(h.State) AS State, h.City,
    m.Score, m.ComparedToNational,
    m.NumberOfPatients, m.PeriodEnd
FROM dbo.HospitalVisitMetrics m
JOIN dbo.Hospital h ON h.FacilityID = m.FacilityID
WHERE m.MeasureID = @Measure
  AND m.Score IS NOT NULL
ORDER BY m.Score ASC;
GO

-- =============================================================
-- SECTION 2: DMV Analysis
-- =============================================================

-- Active indexes with usage stats
SELECT
    t.name  AS TableName,
    i.name  AS IndexName,
    i.type_desc,
    ius.user_seeks,
    ius.user_scans,
    ius.user_lookups,
    ius.user_updates
FROM sys.indexes i
JOIN sys.tables t ON i.object_id = t.object_id
LEFT JOIN sys.dm_db_index_usage_stats ius
    ON ius.object_id = i.object_id
   AND ius.index_id  = i.index_id
   AND ius.database_id = DB_ID()
WHERE t.schema_id = SCHEMA_ID('dbo')
  AND i.type > 0
ORDER BY t.name, i.name;
GO

-- Missing index suggestions (run after workload)
SELECT TOP 10
    mid.statement AS [Table],
    migs.avg_total_user_cost * migs.avg_user_impact
        * (migs.user_seeks + migs.user_scans)           AS ImprovementMeasure,
    migs.avg_user_impact                                AS AvgImpactPct,
    mid.equality_columns,
    mid.inequality_columns,
    mid.included_columns
FROM sys.dm_db_missing_index_groups mig
JOIN sys.dm_db_missing_index_group_stats migs
    ON migs.group_handle = mig.index_group_handle
JOIN sys.dm_db_missing_index_details mid
    ON mig.index_handle = mid.index_handle
WHERE mid.database_id = DB_ID()
ORDER BY ImprovementMeasure DESC;
GO

-- Top expensive queries by logical reads
SELECT TOP 10
    qs.execution_count,
    qs.total_logical_reads / qs.execution_count AS avg_logical_reads,
    qs.total_elapsed_time / qs.execution_count / 1000 AS avg_elapsed_ms,
    SUBSTRING(qt.text,
        (qs.statement_start_offset / 2) + 1,
        ((CASE qs.statement_end_offset
            WHEN -1 THEN DATALENGTH(qt.text)
            ELSE qs.statement_end_offset END
          - qs.statement_start_offset) / 2) + 1
    ) AS query_text
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) qt
WHERE qt.dbid = DB_ID()
ORDER BY avg_logical_reads DESC;
GO

-- =============================================================
-- SECTION 3: Additional Index (DMV-recommended, 2026-06-11)
-- =============================================================
-- DMV Impact: 63.9 — supports /api/metrics/top endpoint

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_VisitMetrics_MeasureID_Score'
      AND object_id = OBJECT_ID('dbo.HospitalVisitMetrics')
)
    CREATE NONCLUSTERED INDEX IX_VisitMetrics_MeasureID_Score
        ON dbo.HospitalVisitMetrics (MeasureID, Score)
        INCLUDE (FacilityID, ComparedToNational, PeriodEnd);
GO

-- =============================================================
-- SECTION 4: ETL & Data Quality Checks
-- =============================================================

-- ETL run history
SELECT
    LogID, RunStart, RunEnd,
    DATEDIFF(SECOND, RunStart, RunEnd) AS DurationSec,
    HospitalsLoaded, MetricsLoaded, Status
FROM dbo.ETL_Log
ORDER BY RunStart DESC;
GO

-- Data completeness
SELECT
    COUNT(*)                                                         AS TotalHospitals,
    SUM(CASE WHEN City          IS NULL THEN 1 ELSE 0 END)          AS NullCity,
    SUM(CASE WHEN OverallRating IS NULL THEN 1 ELSE 0 END)          AS NullRating,
    SUM(CASE WHEN Latitude      IS NULL THEN 1 ELSE 0 END)          AS NullLatitude,
    SUM(CASE WHEN Phone         IS NULL THEN 1 ELSE 0 END)          AS NullPhone
FROM dbo.Hospital;
GO
