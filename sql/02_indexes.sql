-- =============================================================
-- 02_indexes.sql  —  DBA Azure Project : HospitalDB
-- Run after: 01_schema.sql
-- =============================================================

USE HospitalDB;
GO

-- -------------------------------------------------------------
-- Hospital indexes
-- -------------------------------------------------------------

-- State-level aggregation (REST API /states/summary + Power BI)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Hospital_State' AND object_id = OBJECT_ID('dbo.Hospital'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_Hospital_State
        ON dbo.Hospital (State)
        INCLUDE (FacilityName, City, EmergencyServices, OverallRating);
    PRINT 'Created: IX_Hospital_State';
END
GO

-- Full-text style name search
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Hospital_Name' AND object_id = OBJECT_ID('dbo.Hospital'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_Hospital_Name
        ON dbo.Hospital (FacilityName)
        INCLUDE (State, City, HospitalType, OverallRating);
    PRINT 'Created: IX_Hospital_Name';
END
GO

-- -------------------------------------------------------------
-- HospitalVisitMetrics indexes
-- -------------------------------------------------------------

-- Per-hospital metric lookup (REST API /hospitals/{id}/metrics + Power BI DirectQuery)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_VisitMetrics_FacilityID_MeasureID' AND object_id = OBJECT_ID('dbo.HospitalVisitMetrics'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_VisitMetrics_FacilityID_MeasureID
        ON dbo.HospitalVisitMetrics (FacilityID, MeasureID, CollectedAt DESC)
        INCLUDE (Score, ComparedToNational, PeriodStart, PeriodEnd);
    PRINT 'Created: IX_VisitMetrics_FacilityID_MeasureID';
END
GO

-- Date-range queries (trend analysis + ETL deduplication)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_VisitMetrics_CollectedAt' AND object_id = OBJECT_ID('dbo.HospitalVisitMetrics'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_VisitMetrics_CollectedAt
        ON dbo.HospitalVisitMetrics (CollectedAt DESC)
        INCLUDE (FacilityID, MeasureID, Score);
    PRINT 'Created: IX_VisitMetrics_CollectedAt';
END
GO

-- National comparison filter (Power BI slicer + top-performers API)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_VisitMetrics_ComparedToNational' AND object_id = OBJECT_ID('dbo.HospitalVisitMetrics'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_VisitMetrics_ComparedToNational
        ON dbo.HospitalVisitMetrics (ComparedToNational, MeasureID)
        INCLUDE (FacilityID, Score, CollectedAt);
    PRINT 'Created: IX_VisitMetrics_ComparedToNational';
END
GO

-- -------------------------------------------------------------
-- ETL_Log index
-- -------------------------------------------------------------

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_ETLLog_RunStart' AND object_id = OBJECT_ID('dbo.ETL_Log'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_ETLLog_RunStart
        ON dbo.ETL_Log (RunStart DESC)
        INCLUDE (Status, HospitalsLoaded, MetricsLoaded);
    PRINT 'Created: IX_ETLLog_RunStart';
END
GO

-- Measure + Score lookup (REST API /api/metrics/top) — DMV-recommended 2026-06-11
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_VisitMetrics_MeasureID_Score' AND object_id = OBJECT_ID('dbo.HospitalVisitMetrics'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_VisitMetrics_MeasureID_Score
        ON dbo.HospitalVisitMetrics (MeasureID, Score)
        INCLUDE (FacilityID, ComparedToNational, PeriodEnd);
    PRINT 'Created: IX_VisitMetrics_MeasureID_Score';
END
GO

-- -------------------------------------------------------------
-- Verify
-- -------------------------------------------------------------
SELECT
    t.name AS TableName,
    i.name AS IndexName,
    i.type_desc AS IndexType,
    i.is_unique AS IsUnique
FROM sys.indexes i
JOIN sys.tables t ON i.object_id = t.object_id
WHERE t.schema_id = SCHEMA_ID('dbo')
  AND i.type > 0   -- exclude heaps
ORDER BY t.name, i.name;
GO
