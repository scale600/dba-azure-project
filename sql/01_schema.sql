-- =============================================================
-- 01_schema.sql  —  DBA Azure Project : HospitalDB
-- Run order: 01_schema.sql → 02_indexes.sql
-- =============================================================

USE HospitalDB;
GO

-- -------------------------------------------------------------
-- Hospital  (CMS Hospital General Information)
-- -------------------------------------------------------------
IF OBJECT_ID('dbo.Hospital', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Hospital (
        FacilityID        NVARCHAR(10)   NOT NULL,
        FacilityName      NVARCHAR(200)  NOT NULL,
        Address           NVARCHAR(200)  NULL,
        City              NVARCHAR(100)  NULL,
        State             NCHAR(2)       NULL,
        ZipCode           NVARCHAR(10)   NULL,
        Phone             NVARCHAR(20)   NULL,
        HospitalType      NVARCHAR(100)  NULL,
        EmergencyServices NCHAR(1)       NULL,   -- 'Y' or 'N'
        OverallRating     TINYINT        NULL,   -- 1–5, NULL if not rated
        Latitude          DECIMAL(9,6)   NULL,
        Longitude         DECIMAL(9,6)   NULL,
        UpdatedAt         DATETIME2      NOT NULL DEFAULT GETDATE(),

        CONSTRAINT PK_Hospital PRIMARY KEY CLUSTERED (FacilityID),
        CONSTRAINT CK_Hospital_Emergency CHECK (EmergencyServices IN ('Y','N') OR EmergencyServices IS NULL),
        CONSTRAINT CK_Hospital_Rating    CHECK (OverallRating BETWEEN 1 AND 5 OR OverallRating IS NULL)
    );
    PRINT 'Created: dbo.Hospital';
END
ELSE
    PRINT 'Exists:  dbo.Hospital';
GO

-- -------------------------------------------------------------
-- HospitalVisitMetrics  (CMS Unplanned Hospital Visits)
-- -------------------------------------------------------------
IF OBJECT_ID('dbo.HospitalVisitMetrics', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.HospitalVisitMetrics (
        MetricID           INT            NOT NULL IDENTITY(1,1),
        FacilityID         NVARCHAR(10)   NOT NULL,
        CollectedAt        DATETIME2      NOT NULL DEFAULT GETDATE(),
        MeasureID          NVARCHAR(50)   NOT NULL,   -- e.g. 'EDAC_30_AMI'
        MeasureName        NVARCHAR(300)  NULL,
        Score              DECIMAL(8,2)   NULL,
        NumberOfPatients   INT            NULL,
        NumberReturned     INT            NULL,
        ComparedToNational NVARCHAR(20)   NULL,       -- 'Better','Same','Worse','Not Available'
        PeriodStart        DATE           NULL,
        PeriodEnd          DATE           NULL,

        CONSTRAINT PK_HospitalVisitMetrics PRIMARY KEY CLUSTERED (MetricID),
        CONSTRAINT FK_Metrics_Hospital FOREIGN KEY (FacilityID)
            REFERENCES dbo.Hospital (FacilityID),
        CONSTRAINT CK_Metrics_Compared CHECK (
            ComparedToNational IN ('Better','Same','Worse','Not Available') OR ComparedToNational IS NULL
        )
    );
    PRINT 'Created: dbo.HospitalVisitMetrics';
END
ELSE
    PRINT 'Exists:  dbo.HospitalVisitMetrics';
GO

-- -------------------------------------------------------------
-- ETL_Log  (ETL execution audit)
-- -------------------------------------------------------------
IF OBJECT_ID('dbo.ETL_Log', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.ETL_Log (
        LogID           INT            NOT NULL IDENTITY(1,1),
        RunStart        DATETIME2      NOT NULL DEFAULT GETDATE(),
        RunEnd          DATETIME2      NULL,
        HospitalsLoaded INT            NULL,
        MetricsLoaded   INT            NULL,
        Status          NVARCHAR(20)   NOT NULL,   -- 'SUCCESS', 'FAILED', 'RUNNING'
        ErrorMessage    NVARCHAR(MAX)  NULL,

        CONSTRAINT PK_ETL_Log PRIMARY KEY CLUSTERED (LogID),
        CONSTRAINT CK_ETLLog_Status CHECK (Status IN ('SUCCESS','FAILED','RUNNING'))
    );
    PRINT 'Created: dbo.ETL_Log';
END
ELSE
    PRINT 'Exists:  dbo.ETL_Log';
GO

-- -------------------------------------------------------------
-- Verify
-- -------------------------------------------------------------
SELECT
    TABLE_NAME,
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS c
     WHERE c.TABLE_NAME = t.TABLE_NAME AND c.TABLE_SCHEMA = 'dbo') AS ColumnCount
FROM INFORMATION_SCHEMA.TABLES t
WHERE TABLE_SCHEMA = 'dbo'
ORDER BY TABLE_NAME;
GO
