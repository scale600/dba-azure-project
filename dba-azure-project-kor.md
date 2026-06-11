# DBA Azure 프로젝트

> **TechCloudUp DBA Lab** — CMS Public API → Azure Function App → Azure SQL Database → 커스텀 REST API + Power BI, Azure Key Vault 보안, Application Insights & Azure Monitor 모니터링.

CMS 공공 API에서 미국 병원 데이터를 수집하여 Azure SQL Database에 저장하고, 커스텀 REST API와 Power BI 대시보드까지 구축하는 엔드-투-엔드 포트폴리오 프로젝트. DBA 역량(스키마 설계, 인덱스 튜닝, ETL 자동화, 백업/복구)과 API 개발 및 BI 분석 능력을 동시에 실증합니다.

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [아키텍처](#2-아키텍처)
3. [데이터 모델](#3-데이터-모델)
4. [CMS API 명세 및 필드 매핑](#4-cms-api-명세-및-필드-매핑)
5. [ETL 파이프라인 설계](#5-etl-파이프라인-설계)
6. [REST API 설계](#6-rest-api-설계)
7. [BI 대시보드 설계](#7-bi-대시보드-설계)
8. [Azure 배포 가이드](#8-azure-배포-가이드)
9. [배포 리소스 현황](#9-배포-리소스-현황)
10. [테스트 계획](#10-테스트-계획)
11. [파일 구조](#11-파일-구조)
12. [진행 체크리스트](#12-진행-체크리스트)

---

## 1. 프로젝트 개요

### 목표

| 레이어 | 목표 |
|--------|------|
| **DBA** | 스키마 설계, 인덱스 튜닝, ETL 자동화, 백업/복구 검증 |
| **API** | DB 위에 커스텀 REST API 구축 (Azure Functions HTTP Trigger) |
| **BI** | Power BI 대시보드로 데이터 인사이트 시각화 |

### 데이터 소스

| API | 제공기관 | 인증 | 업데이트 주기 | 역할 |
|-----|---------|------|-------------|------|
| Hospital General Information | CMS | 불필요 | 분기 | 병원 기본정보 마스터 |
| Unplanned Hospital Visits | CMS | 불필요 | 분기 | 품질 지표 스냅샷 |

### 범위

| 항목 | 포함 여부 |
|------|-----------|
| Python 기반 ETL 파이프라인 | ✅ |
| Azure SQL Database | ✅ |
| Azure Function App — Timer Trigger (ETL 스케줄러) | ✅ |
| Azure Function App — HTTP Trigger (REST API) | ✅ |
| Power BI 대시보드 | ✅ |
| Azure Key Vault (시크릿 관리) | ✅ |
| 웹 프론트엔드 | ❌ (API + Power BI로 검증) |

### 성공 기준

1. 매일 UTC 00:00, 12:00 두 차례 자동 데이터 수집
2. 인덱스 적용 후 병원별 지표 쿼리 응답시간 **500ms 미만**
3. REST API `GET /api/hospitals` 응답시간 **300ms 미만** (p95)
4. Power BI DirectQuery로 대시보드 새로고침 성공 (**30초 이내**)
5. Point-in-Time Restore 데이터 무결성 확인 및 복구 시간 실측 기록
6. 모든 코드 GitHub 공개, README에 실행 방법 명시

### HIPAA 고려사항

> 본 프로젝트에서 사용하는 CMS 데이터셋은 Safe Harbor 방식(45 CFR §164.514(b))에 따라 **완전히 비식별화된 공개 데이터**로, PHI(보호 건강 정보)를 포함하지 않습니다. 따라서 이 프로젝트에 HIPAA 의무는 적용되지 않습니다.
>
> 다만 본 아키텍처는 HIPAA 준비성(HIPAA-readiness)을 염두에 두고 설계되었습니다. 향후 PHI를 다루는 시스템으로 확장될 경우, 아래 통제 항목들은 현재 구조에서 최소한의 변경으로 적용 가능합니다.

| 통제 항목 | Azure 서비스 / 적용 방법 | 비고 |
|-----------|------------------------|------|
| 저장 암호화 | Azure SQL TDE (기본 활성화) | AES-256; GP 티어에서 추가 설정 불필요 |
| 전송 암호화 | TLS 1.2 강제 적용 | Bicep에서 `minimalTlsVersion: '1.2'` 설정 |
| 접근 제어 | Azure RBAC + Managed Identity | 코드 내 비밀번호 없음; `DefaultAzureCredential` 패턴 적용 완료 |
| 감사 로깅 | Azure SQL Auditing → Log Analytics | PHI 환경에서는 Bicep `auditingSettings` 활성화 필요 |
| 비밀 관리 | Azure Key Vault | 연결 문자열이 코드·설정 파일에 노출되지 않음 |
| 네트워크 격리 | Private Endpoint + VNet 통합 | PHI 환경 권장 추가 항목; 현 데모에서는 미적용 |
| 침해 탐지 | Azure Defender for SQL | 이상 행위 알림을 위한 위협 탐지 정책 활성화 |
| 사업 협력 계약 | Microsoft BAA | Azure 표준 OST 하에서 제공 가능 |

이 설계 패턴은 HIPAA 기술적 보호 조치(§164.312)에 대한 이해를 바탕으로 하며, 구조적 변경을 최소화하여 규정 준수 아키텍처로 확장 가능합니다.

---

## 2. 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                       데이터 소스                            │
│   CMS Hospital General Info    CMS Unplanned Hospital Visits│
└──────────────┬──────────────────────────┬───────────────────┘
               │ HTTP GET (인증 불필요)     │ HTTP GET (인증 불필요)
               ▼                          ▼
┌─────────────────────────────────────────────────────────────┐
│           Azure Function App  (Python 3.11)                 │
│  ┌────────────────────────┐  ┌──────────────────────────┐   │
│  │ Timer Trigger (ETL)    │  │ HTTP Trigger (REST API)  │   │
│  │ CRON: 0 0 0,12 * * *   │  │ GET /api/hospitals       │   │
│  │ • 수집 → 변환           │  │ GET /api/hospitals/{id}  │   │
│  │ • MERGE + INSERT       │  │ GET /api/hospitals/{id}  │   │
│  │ • ETL_Log 기록          │  │   /metrics               │   │
│  └──────────┬─────────────┘  │ GET /api/states/summary  │   │
│             │                │ GET /api/metrics/top     │   │
└─────────────┼────────────────┴──────────┬───────────────────┘
              │                           │
              ▼                           │
┌─────────────────────────┐               │
│   Azure SQL Database    │◄──────────────┘
│   (Serverless 티어)      │
│   • dbo.Hospital        │
│   • dbo.HospitalVisit   │◄──────────── Power BI Service
│     Metrics             │              (DirectQuery)
│   • dbo.ETL_Log         │
└─────────────────────────┘
        ▲
        │ 시크릿 참조
┌───────────────┐     ┌────────────────────┐
│ Azure Key     │     │ Application        │
│ Vault         │     │ Insights + Monitor │
└───────────────┘     └────────────────────┘
```

---

## 3. 데이터 모델

### 핵심 테이블 DDL

```sql
-- 미국 병원 기본정보 마스터
CREATE TABLE dbo.Hospital (
    FacilityID        NVARCHAR(10)  NOT NULL PRIMARY KEY,
    FacilityName      NVARCHAR(200) NOT NULL,
    Address           NVARCHAR(200),
    City              NVARCHAR(100),
    State             NCHAR(2),
    ZipCode           NVARCHAR(10),
    Phone             NVARCHAR(20),
    HospitalType      NVARCHAR(100),
    EmergencyServices NCHAR(1),     -- 'Y' 또는 'N'
    OverallRating     TINYINT,      -- 1~5, 미평가 시 NULL
    UpdatedAt         DATETIME2     DEFAULT GETDATE()
);

-- 주기적 품질 지표 스냅샷
CREATE TABLE dbo.HospitalVisitMetrics (
    MetricID           INT           IDENTITY PRIMARY KEY,
    FacilityID         NVARCHAR(10)  NOT NULL REFERENCES dbo.Hospital(FacilityID),
    CollectedAt        DATETIME2     NOT NULL DEFAULT GETDATE(),
    MeasureID          NVARCHAR(20)  NOT NULL,
    MeasureName        NVARCHAR(300),
    Score              DECIMAL(8,2),
    NumberOfPatients   INT,
    NumberReturned     INT,
    ComparedToNational NVARCHAR(10), -- 'Better', 'Same', 'Worse'
    PeriodStart        DATE,
    PeriodEnd          DATE
);

-- ETL 실행 감사 로그
CREATE TABLE dbo.ETL_Log (
    LogID           INT           IDENTITY PRIMARY KEY,
    RunStart        DATETIME2     DEFAULT GETDATE(),
    RunEnd          DATETIME2,
    RecordsInserted INT,
    Status          NVARCHAR(20), -- 'SUCCESS', 'FAILED'
    ErrorMessage    NVARCHAR(MAX)
);
```

### 인덱스 전략

```sql
CREATE INDEX IX_VisitMetrics_CollectedAt
    ON dbo.HospitalVisitMetrics (CollectedAt DESC)
    INCLUDE (FacilityID, MeasureID, Score);

CREATE INDEX IX_VisitMetrics_FacilityID_MeasureID
    ON dbo.HospitalVisitMetrics (FacilityID, MeasureID, CollectedAt DESC);

CREATE INDEX IX_Hospital_State
    ON dbo.Hospital (State)
    INCLUDE (FacilityName, EmergencyServices, OverallRating);

CREATE INDEX IX_ETLLog_RunStart
    ON dbo.ETL_Log (RunStart DESC);
```

---

## 4. CMS API 명세 및 필드 매핑

### 엔드포인트 (인증 불필요)

```
병원 기본정보:
  GET https://data.cms.gov/provider-data/api/1/datastore/query/xubh-q36u/0
  Params: limit=5000, offset=0

비계획 방문 지표:
  GET https://data.cms.gov/provider-data/api/1/datastore/query/632h-zaca/0
  Params: limit=10000, offset=0
```

### 필드 매핑 — Hospital General Information → `dbo.Hospital`

| API 필드명 | 타입 | 대상 컬럼 | 변환 규칙 |
|-----------|------|-----------|-----------|
| `facility_id` | string | `FacilityID` | 그대로 사용 (PK) |
| `facility_name` | string | `FacilityName` | `str.strip().title()` |
| `address` | string | `Address` | `str.strip()` |
| `citytown` | string | `City` | `str.strip().title()` |
| `state` | string | `State` | 그대로 사용 |
| `zip_code` | string | `ZipCode` | 그대로 사용 |
| `telephone_number` | string | `Phone` | `(XXX) XXX-XXXX` 형식 정규화 |
| `hospital_type` | string | `HospitalType` | `str.strip()` |
| `emergency_services` | string | `EmergencyServices` | `'Yes'→'Y'`, `'No'→'N'` |
| `hospital_overall_rating` | string | `OverallRating` | `int()`, `'Not Available'→NULL` |

### 필드 매핑 — Unplanned Hospital Visits → `dbo.HospitalVisitMetrics`

| API 필드명 | 타입 | 대상 컬럼 | 변환 규칙 |
|-----------|------|-----------|-----------|
| `facility_id` | string | `FacilityID` | 그대로 사용 (FK) |
| `measure_id` | string | `MeasureID` | 그대로 사용 |
| `measure_name` | string | `MeasureName` | `str.strip()` |
| `score` | string | `Score` | `float()`, `'Not Available'→NULL` |
| `number_of_patients` | string | `NumberOfPatients` | `int()`, 결측→NULL |
| `number_of_patients_returned` | string | `NumberReturned` | `int()`, 결측→NULL |
| `compared_to_national` | string | `ComparedToNational` | `'Better...'→'Better'`, `'No Different...'→'Same'`, `'Worse...'→'Worse'` |
| `start_date` | string | `PeriodStart` | `datetime.strptime('%m/%d/%Y')` |
| `end_date` | string | `PeriodEnd` | `datetime.strptime('%m/%d/%Y')` |

---

## 5. ETL 파이프라인 설계

### 실행 주기

- **트리거**: Azure Function App Timer Trigger
- **CRON**: `0 0 0,12 * * *` (UTC 00:00, 12:00)

### 데이터 흐름

```
[CMS data.cms.gov]
    ↓  HTTP GET (인증 불필요)
[Python Function — Timer Trigger]
    ↓  JSON 파싱 → 필드 매핑 → 타입 변환
[dbo.Hospital]             ← MERGE (FacilityID 기준 upsert)
[dbo.HospitalVisitMetrics] ← INSERT 스냅샷 (매 실행마다 누적)
[dbo.ETL_Log]              ← 성공/실패 기록
```

### 에러 처리 정책

| 에러 유형 | 처리 방식 |
|----------|-----------|
| HTTP 429 | 지수 백오프 재시도 (최대 3회, 2^n초 대기) |
| 네트워크 타임아웃 | 재시도 후 FAILED 기록 |
| 데이터 파싱 오류 | 레코드 스킵, 오류 로그 |
| DB 연결 실패 | 즉시 실패 + Application Insights 알림 |

---

## 6. REST API 설계

**Azure Functions HTTP Trigger** 기반 — 추가 인프라 불필요.

### Base URL

```
https://www.dba-azure.techcloudup.com/api
```

### 엔드포인트

| Method | Endpoint | 설명 |
|--------|---------|------|
| GET | `/api/hospitals` | 병원 목록 (state, emergency, rating 필터, 페이지네이션) |
| GET | `/api/hospitals/{id}` | 병원 상세 정보 |
| GET | `/api/hospitals/{id}/metrics` | 병원별 품질 지표 이력 |
| GET | `/api/states/summary` | 주(State)별 통계 집계 |
| GET | `/api/metrics/top` | 특정 지표 기준 상위 병원 랭킹 |

### 표준 에러 응답 형식

```json
{
  "error": "NOT_FOUND",
  "message": "Hospital with facility_id '999999' not found.",
  "status": 404
}
```

| 코드 | 의미 |
|------|------|
| 200 | 성공 |
| 400 | 잘못된 요청 파라미터 |
| 404 | 리소스 없음 |
| 500 | 내부 서버 오류 (Application Insights 기록) |

---

## 7. BI 대시보드 설계

**도구**: Power BI Service (Azure SQL Database DirectQuery 연결)

### 리포트 페이지 구성

#### Page 1 — National Overview (전국 현황)
| 시각화 | 종류 | 내용 |
|--------|------|------|
| 주별 병원 수 | 채워진 지도 | 색상 농도 = 병원 수 |
| 주별 평균 등급 | 가로 막대 차트 | 내림차순 정렬 |
| 응급 서비스 비율 | 도넛 차트 | Y vs N |
| 등급 분포 | 히스토그램 | 1~5점 |
| KPI 카드 | 카드 | 전체 병원 수 / 평균 등급 / 응급 서비스 보유율 |

#### Page 2 — State Drill-Down (주별 상세)
| 시각화 | 종류 | 내용 |
|--------|------|------|
| 주 슬라이서 | 슬라이서 | 전체 시각화 필터 |
| 병원 목록 | 테이블 | 이름, 도시, 유형, 등급, 응급 여부 |
| 등급 변화 추이 | 꺾은선 차트 | ETL 실행별 등급 변화 |
| 병원 유형 분포 | 파이 차트 | Acute Care vs Critical Access 등 |

#### Page 3 — Quality Metrics (품질 지표)
| 시각화 | 종류 | 내용 |
|--------|------|------|
| 지표 슬라이서 | 슬라이서 | MeasureID 선택 |
| 점수 분포 | 박스 플롯 | 전국 분포 |
| Better/Same/Worse | 누적 막대 차트 | 주별 비교 |
| 상위 10개 병원 | 가로 막대 차트 | 선택 지표 기준 |
| 점수 시계열 | 꺾은선 차트 | 병원별, 지표별 추이 |

#### Page 4 — ETL Operations (DBA 운영 뷰)
| 시각화 | 종류 | 내용 |
|--------|------|------|
| ETL 실행 이력 | 테이블 | RunStart, RunEnd, 건수, 상태 |
| 성공/실패 비율 | 도넛 차트 | 최근 30일 |
| 수집 건수 추이 | 꺾은선 차트 | 데이터 볼륨 변화 |
| 평균 ETL 소요 시간 | KPI 카드 | 초 단위 |

### 핵심 DAX 측정값

```dax
Total Hospitals = COUNTROWS(Hospital)

Avg Rating = AVERAGE(Hospital[OverallRating])

Emergency Coverage % =
DIVIDE(
    COUNTROWS(FILTER(Hospital, Hospital[EmergencyServices] = "Y")),
    COUNTROWS(Hospital)
) * 100

ETL Success Rate % =
DIVIDE(
    COUNTROWS(FILTER(ETL_Log, ETL_Log[Status] = "SUCCESS")),
    COUNTROWS(ETL_Log)
) * 100
```

---

## 8. Azure 배포 가이드

### 리소스 생성 순서

1. Resource Group ✅
2. Azure Key Vault
3. Azure SQL Server + Database (서버리스 티어)
4. Azure Function App (Python 3.11) — ETL Timer + REST API HTTP Trigger 공용
5. 방화벽 규칙 / Managed Identity 권한 설정
6. Power BI 워크스페이스 연결

### Bicep 템플릿 (핵심)

```bicep
resource sqlDB 'Microsoft.Sql/servers/databases@2021-11-01' = {
  parent: sqlServer
  name: 'HospitalDB'
  location: location
  sku: {
    name: 'GP_S_Gen5_1'
    tier: 'GeneralPurpose'
    family: 'Gen5'
    capacity: 1
  }
  properties: {
    autoPauseDelay: 60
    minCapacity: json('0.5')
  }
}
```

---

## 9. 배포 리소스 현황

| 리소스 | 이름 | 위치 | 상태 |
|--------|------|------|------|
| Resource Group | `rg-dba-project` | East US | ✅ 활성 |
| Azure DNS Zone | `dba-azure.techcloudup.com` | 글로벌 | ✅ 활성 |
| Azure Static Web Apps | `swa-dba-project` | East US 2 | ✅ 활성 |
| 커스텀 도메인 | `www.dba-azure.techcloudup.com` | — | ✅ Ready (SSL) |
| Azure Key Vault | `kv-dba-xvel6ncdvw` | East US | ✅ 활성 |
| Azure SQL Server | `sql-dba-xvel6ncdvwsre` | West US 3 | ✅ 활성 |
| Azure SQL Database | `HospitalDB` | West US 3 | ✅ 활성 (Serverless GP_S_Gen5_1) |
| Azure Function App (ETL + API) | — | — | ⬜ 대기 중 (VM 쿼타) |
| Application Insights | `appi-dba-project` | East US | ✅ 활성 |
| Power BI 워크스페이스 | — | — | ⬜ 미생성 |

**라이브 URL:** https://www.dba-azure.techcloudup.com

---

## 10. 테스트 계획

| ID | 시나리오 | 예상 결과 | 확인 방법 |
|----|---------|-----------|-----------|
| TC-01 | CMS API 응답 지연 10초 | 재시도 후 ETL_Log에 FAILED | `SELECT * FROM ETL_Log WHERE Status='FAILED'` |
| TC-02 | 인덱스 없이 날짜 범위 쿼리 | Table Scan | `SET STATISTICS IO ON` + 실행 계획 |
| TC-03 | 인덱스 적용 후 동일 쿼리 | Index Seek, 500ms 미만 | 실행 계획 + elapsed time |
| TC-04 | Point-in-Time Restore | 복원 시점 이후 레코드 없음 | COUNT(*) 전후 비교 |
| TC-05 | 동일 데이터 재수집 | MERGE가 미변경 레코드 스킵 | RecordsInserted vs UPDATE 건수 |
| TC-06 | `GET /api/hospitals?state=CA` | 200, 페이지네이션 정상, 300ms 미만 | 응답 시간 + JSON 스키마 검증 |
| TC-07 | `GET /api/hospitals/invalid_id` | 404 + 표준 에러 JSON | `{"error":"NOT_FOUND","status":404}` |
| TC-08 | Power BI 대시보드 새로고침 | 30초 이내 완료 | Power BI Service 새로고침 로그 |

---

## 11. 파일 구조

```
dba-azure-project/
├── dba-azure-project.md          # 영문 원본
├── dba-azure-project-kor.md      # 이 문서 — 국문 클론
├── site/
│   ├── index.html
│   └── dba-azure-project.md
├── infra/
│   ├── main.bicep
│   └── parameters.json
├── sql/
│   ├── 01_schema.sql
│   ├── 02_indexes.sql
│   └── 03_queries.sql
├── etl/
│   └── function_app/
│       ├── timer_trigger/
│       │   └── __init__.py       # ETL Timer Trigger
│       ├── etl.py                # 수집/변환/로드 로직
│       └── requirements.txt
├── api/
│   └── function_app/
│       ├── hospitals/
│       │   └── __init__.py       # GET /api/hospitals
│       ├── hospital_detail/
│       │   └── __init__.py       # GET /api/hospitals/{id}
│       ├── hospital_metrics/
│       │   └── __init__.py       # GET /api/hospitals/{id}/metrics
│       ├── states_summary/
│       │   └── __init__.py       # GET /api/states/summary
│       ├── metrics_top/
│       │   └── __init__.py       # GET /api/metrics/top
│       └── shared/
│           └── db.py             # 공용 DB 연결 헬퍼
├── bi/
│   └── hospital_quality.pbix     # Power BI 리포트 파일
├── monitoring/
│   └── dashboard.json
├── .env.example
└── README.md
```

---

## 12. 진행 체크리스트

### Phase 1 — 사전 준비

- [ ] ~~API 키 발급~~ → CMS API 인증 불필요
- [x] Azure 계정 활성 (`scale600@outlook.com`)
- [x] Azure CLI + `az login` 완료
- [x] Python 3.11 + `pyodbc`, `azure-functions`, `azure-identity`, `requests` 설치
- [x] GitHub 레포 생성 (`dba-azure-project`) + `.gitignore` (`.env`, `*.pbix` 포함) + `.env.example`

### Phase 2 — Azure 인프라

- [x] Resource Group (`rg-dba-project`, `eastus`)
- [x] Azure DNS Zone + Cloudflare NS 위임 완료
- [x] Azure Static Web Apps + `www.dba-azure.techcloudup.com` 라이브
- [x] Azure Key Vault (`kv-dba-xvel6ncdvw`, `eastus`) — `DB-CONNECTION-STRING` 등록 완료
- [x] `main.bicep` 배포 — SQL Server (`sql-dba-xvel6ncdvwsre`, `westus3`) + `HospitalDB` + Log Analytics + App Insights
- [x] SQL 방화벽 (로컬 IP `108.94.142.34`) + `pyodbc` 연결 테스트 통과
- [ ] Function App (`func.bicep`) — VM 쿼타 또는 리전 가용성 확인 후 배포 예정
- [ ] Function App Managed Identity → Key Vault 권한

### Phase 3 — DB 스키마

- [x] `sql/01_schema.sql` 실행 (Hospital, HospitalVisitMetrics, ETL_Log)
- [x] `sql/02_indexes.sql` 실행 (Non-clustered 인덱스 6개)
- [x] 스키마 확인 + 샘플 데이터 검증

### Phase 4 — ETL 코드 개발

- [x] `etl/cms_client.py` — CMS API 페이지네이션 수집 (Hospital 5,433건 / Metrics 67,088건)
- [x] `etl/db_client.py` — MERGE upsert (Hospital, HospitalVisitMetrics) + ETL_Log 기록
- [x] `etl/etl_runner.py` — 로컬 실행 및 전체 데이터 로드 완료
- [ ] Timer Trigger `__init__.py` + `function.json` CRON 설정 — Function App 배포 후 진행
- [ ] 로컬 `func start` 테스트 후 Azure 배포

### Phase 5 — REST API 개발

- [x] `api/db.py` — 연결 헬퍼 (env var + Key Vault 자동 전환)
- [x] 5개 엔드포인트 구현 (hospitals, detail, metrics, states/summary, metrics/top)
- [x] 에러 핸들링 — 표준 JSON 에러 형식 (`{"error", "message", "status"}`)
- [ ] Azure Function App 배포 (VM quota 해결 후)
- [ ] TC-06, TC-07 검증

### Phase 6 — 성능 튜닝

- [x] 인덱스 전후 실행 계획 비교 (4개 쿼리, 5회 평균)
  - 병원메트릭 조회: 35.6 ms → 16.5 ms (-54%)
  - National비교 필터: 36.9 ms → 15.7 ms (-57%)
  - 이름 검색: 18.4 ms → 15.9 ms (-14%)
- [x] DMV missing index 분석 → IX_VisitMetrics_MeasureID_Score 추가 (impact 63.9)
- [x] `sql/03_queries.sql` 작성 (벤치마크 + DMV + ETL 품질 쿼리)

### Phase 7 — 백업 및 복구 검증

- [x] Azure SQL 자동 백업 확인 — 보존 7일, 차등 12시간 간격, Local 중복성
- [x] Point-in-Time Restore 테스트 (canary row 기반 무결성 검증)
  - Hospital: 5,434 → 5,433 ✅ (복구 시점 이후 삽입된 행 없음)
  - Metrics: 67,088 → 67,088 ✅
- [x] 복구 소요 시간: **16분** (GP_S_Gen5_1 Serverless, westus3)

### Phase 8 — BI 대시보드 (Power BI)

- [x] Power BI DirectQuery용 SQL 뷰 4개 생성
  - `vw_HospitalNationalOverview`, `vw_StateSummary`
  - `vw_MetricsQuality`, `vw_ETLOperations`
- [x] DAX 측정값 22개 작성 → `bi/dax_measures.dax`
- [x] Power BI 연결 가이드 → `bi/powerbi_setup.md`
- [ ] Windows에서 Power BI Desktop으로 .pbix 빌드 + Service 게시
- [ ] TC-08 검증 (30초 이내)

### Phase 9 — 모니터링

- [ ] Application Insights 연결 (ETL + API)
- [ ] Azure Monitor 경보 (ETL 실패, API 오류율 >5%, CPU >80%)
- [ ] 대시보드 구성 + `monitoring/dashboard.json` 저장

### Phase 10 — 마무리

- [ ] `README.md` (아키텍처 다이어그램, 실행 방법, API 문서, BI 스크린샷)
- [ ] GitHub Actions CI (SQL lint)
- [ ] TC-01 ~ TC-08 전체 실행 및 결과 기록
- [ ] 시크릿 노출 최종 확인
- [ ] GitHub 레포 Public 전환
