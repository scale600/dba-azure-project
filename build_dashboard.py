#!/usr/bin/env python3.11
"""Build site/dashboard.html by querying HospitalDB and embedding data."""

import os, sys, json
from decimal import Decimal
from datetime import date, datetime, timezone, timedelta

PST = timezone(timedelta(hours=-8))

sys.path.insert(0, os.path.dirname(__file__))

# Load .env
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

from api.db import query

def fix(obj):
    if isinstance(obj, Decimal): return float(obj)
    if isinstance(obj, (date, datetime)): return obj.isoformat()
    return obj

def q(sql): return [{k: fix(v) for k, v in r.items()} for r in query(sql)]

print("Querying HospitalDB...")

data = {
    "generated_at": datetime.now(PST).strftime("%Y-%m-%d %H:%M PST"),
    "kpi": q("""
        SELECT
            COUNT(*) AS total_hospitals,
            CAST(AVG(CAST(OverallRating AS FLOAT)) AS DECIMAL(4,2)) AS avg_rating,
            SUM(CASE WHEN RTRIM(EmergencyServices)='Y' THEN 1 ELSE 0 END) AS with_emergency,
            SUM(CASE WHEN OverallRating=5 THEN 1 ELSE 0 END) AS top_rated
        FROM dbo.Hospital WHERE State IS NOT NULL
    """)[0],
    "metrics_count": q("SELECT COUNT(*) AS cnt FROM dbo.HospitalVisitMetrics")[0]["cnt"],
    "rating_dist": q("""
        SELECT OverallRating AS rating, COUNT(*) AS count
        FROM dbo.Hospital WHERE OverallRating IS NOT NULL
        GROUP BY OverallRating ORDER BY OverallRating
    """),
    "emergency_dist": q("""
        SELECT RTRIM(EmergencyServices) AS emergency, COUNT(*) AS count
        FROM dbo.Hospital WHERE EmergencyServices IS NOT NULL
        GROUP BY RTRIM(EmergencyServices)
    """),
    "top_states": q("""
        SELECT TOP 20 RTRIM(State) AS state, COUNT(*) AS hospitals,
            CAST(AVG(CAST(OverallRating AS FLOAT)) AS DECIMAL(4,2)) AS avg_rating
        FROM dbo.Hospital WHERE State IS NOT NULL
        GROUP BY RTRIM(State) ORDER BY hospitals DESC
    """),
    "hospital_types": q("""
        SELECT HospitalType AS type, COUNT(*) AS count
        FROM dbo.Hospital WHERE HospitalType IS NOT NULL
        GROUP BY HospitalType ORDER BY count DESC
    """),
    "national_comparison": q("""
        SELECT ComparedToNational AS result, COUNT(*) AS count
        FROM dbo.HospitalVisitMetrics WHERE ComparedToNational IS NOT NULL
        GROUP BY ComparedToNational ORDER BY count DESC
    """),
    "etl_log": q("""
        SELECT TOP 8
            LogID           AS log_id,
            Status          AS status,
            HospitalsLoaded AS hospitals_loaded,
            MetricsLoaded   AS metrics_loaded,
            DATEDIFF(SECOND, RunStart, RunEnd) AS duration_sec,
            CONVERT(VARCHAR(16), DATEADD(HOUR, -8, RunStart), 120) AS run_start
        FROM dbo.ETL_Log ORDER BY RunStart DESC
    """),
}

data_js = f"const DB_DATA = {json.dumps(data, indent=2)};"

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Live Dashboard — DBA Azure Project</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0f172a;--sidebar:#1e293b;--card:#1e293b;--border:#334155;
  --text:#f1f5f9;--muted:#94a3b8;--accent:#3b82f6;--green:#22c55e;
  --yellow:#eab308;--red:#ef4444;--purple:#a855f7;
}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);display:flex;height:100vh;overflow:hidden}}

/* Sidebar */
aside{{width:220px;background:var(--sidebar);border-right:1px solid var(--border);display:flex;flex-direction:column;flex-shrink:0}}
.sidebar-logo{{padding:20px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}}
.sidebar-logo svg{{color:var(--accent)}}
.sidebar-logo span{{font-weight:700;font-size:13px;line-height:1.3;color:var(--text)}}
nav{{padding:12px 0;flex:1}}
nav a{{display:flex;align-items:center;gap:10px;padding:9px 16px;font-size:13px;color:var(--muted);text-decoration:none;transition:all .15s;border-right:2px solid transparent}}
nav a:hover{{background:rgba(255,255,255,.05);color:var(--text)}}
nav a.active{{background:rgba(59,130,246,.15);color:var(--accent);border-right-color:var(--accent)}}
nav a svg{{width:16px;height:16px;flex-shrink:0}}
.sidebar-footer{{padding:12px 16px;border-top:1px solid var(--border);font-size:11px;color:var(--muted)}}

/* Main */
main{{flex:1;display:flex;flex-direction:column;overflow:hidden}}
.topbar{{height:52px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 24px;background:var(--sidebar);flex-shrink:0}}
.topbar h1{{font-size:15px;font-weight:600}}
.cost-notice{{border-bottom:1px solid var(--border);background:rgba(234,179,8,.08);color:#fbbf24;padding:8px 24px;font-size:12px;line-height:1.4;flex-shrink:0}}
.badge{{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:500}}
.badge.live{{background:rgba(34,197,94,.15);color:#4ade80}}
.badge.live::before{{content:'';width:6px;height:6px;background:#22c55e;border-radius:50%;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.badge.snap{{background:rgba(59,130,246,.15);color:#60a5fa}}
.badge.disabled{{background:rgba(148,163,184,.12);color:#94a3b8}}
.generated{{font-size:11px;color:var(--muted)}}

.content{{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:24px}}

/* KPI cards */
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}}
.kpi{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px}}
.kpi-header{{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px}}
.kpi-icon{{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center}}
.kpi-icon.blue{{background:rgba(59,130,246,.15)}}
.kpi-icon.green{{background:rgba(34,197,94,.15)}}
.kpi-icon.purple{{background:rgba(168,85,247,.15)}}
.kpi-icon.yellow{{background:rgba(234,179,8,.15)}}
.kpi-value{{font-size:28px;font-weight:700;line-height:1}}
.kpi-label{{font-size:13px;color:var(--muted);margin-top:4px}}
.kpi-sub{{font-size:11px;color:var(--muted);margin-top:6px}}

/* Charts grid */
.charts-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.charts-grid.wide{{grid-template-columns:2fr 1fr}}
@media(max-width:900px){{.charts-grid,.charts-grid.wide{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px}}
.card-title{{font-size:13px;font-weight:600;margin-bottom:16px;color:var(--text)}}
.chart-wrap{{position:relative;height:220px}}

/* Table */
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{text-align:left;padding:8px 10px;color:var(--muted);border-bottom:1px solid var(--border);font-weight:500}}
td{{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.04)}}
tr:last-child td{{border-bottom:none}}
.status-ok{{color:#4ade80;font-weight:600}}
.status-fail{{color:#f87171;font-weight:600}}
.status-run{{color:#fbbf24;font-weight:600}}
.btn-export{{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;border:1px solid var(--border);background:rgba(255,255,255,.05);color:var(--muted);transition:all .15s}}
.btn-export:hover{{background:rgba(59,130,246,.15);color:#60a5fa;border-color:#3b82f6}}
.btn-export:disabled{{opacity:.4;cursor:not-allowed}}

/* Data Export section */
.export-grid{{display:flex;flex-direction:column;gap:12px}}
.export-item{{display:flex;align-items:center;gap:16px;padding:16px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,.02);transition:background .15s}}
.export-item:hover{{background:rgba(255,255,255,.04)}}
.export-icon{{width:44px;height:44px;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
.export-info{{flex:1;min-width:0}}
.export-name{{font-size:14px;font-weight:600;color:var(--text);margin-bottom:3px}}
.export-desc{{font-size:12px;color:var(--muted);margin-bottom:4px}}
.export-cols{{font-size:10px;color:#475569;font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.btn-export-lg{{flex-shrink:0;padding:7px 16px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid var(--border);background:rgba(59,130,246,.1);color:#60a5fa;transition:all .15s;white-space:nowrap}}
.btn-export-lg:hover{{background:rgba(59,130,246,.25);border-color:#3b82f6}}
.btn-export-lg:disabled{{opacity:.4;cursor:not-allowed}}

/* About section */
.about-grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
@media(max-width:900px){{.about-grid{{grid-template-columns:1fr}}}}
.about-desc{{font-size:14px;line-height:1.7;color:var(--muted)}}
.about-desc p{{margin-bottom:12px}}
.about-note{{font-size:12px;color:#64748b;border-left:2px solid var(--border);padding-left:12px;margin-top:8px}}
.about-label{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:8px}}
.tech-badges{{display:flex;flex-wrap:wrap;gap:6px}}
.tech-badge{{padding:4px 10px;border-radius:6px;font-size:11px;font-weight:600}}
.tech-badge.python{{background:rgba(234,179,8,.12);color:#fbbf24}}
.tech-badge.azure{{background:rgba(59,130,246,.12);color:#60a5fa}}
.tech-badge.misc{{background:rgba(148,163,184,.1);color:#94a3b8}}
.data-sources{{display:flex;flex-direction:column;gap:6px}}
.data-src{{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-radius:8px;background:rgba(255,255,255,.02);border:1px solid var(--border)}}
.data-src-name{{font-size:12px;font-weight:600;color:var(--text)}}
.data-src-detail{{font-size:11px;color:var(--muted)}}

/* How it works section */
.flow-steps{{display:flex;align-items:flex-start;justify-content:center;gap:0;flex-wrap:wrap;margin-bottom:20px}}
.flow-step{{display:flex;flex-direction:column;align-items:center;text-align:center;width:150px;gap:8px}}
.flow-icon{{width:44px;height:44px;border-radius:10px;display:flex;align-items:center;justify-content:center}}
.flow-title{{font-size:12px;font-weight:700;color:var(--text)}}
.flow-desc{{font-size:11px;color:var(--muted);line-height:1.4}}
.flow-arrow{{font-size:20px;color:var(--border);padding:10px 8px 0;align-self:flex-start;margin-top:10px}}
.flow-details{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;border-top:1px solid var(--border);padding-top:16px}}
.flow-detail{{display:flex;flex-direction:column;gap:2px;padding:10px 14px;border-radius:8px;background:rgba(255,255,255,.02)}}
.flow-detail-label{{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
.flow-detail-value{{font-size:12px;color:var(--text)}}

/* Nav separator */
.nav-sep{{height:1px;background:var(--border);margin:6px 16px}}

@media(max-width:680px){{
  aside{{display:none}}
  .content{{padding:16px}}
  .flow-steps{{flex-direction:column;align-items:center}}
  .flow-arrow{{transform:rotate(90deg);padding:4px 0}}
}}
</style>
</head>
<body>
<aside>
  <div class="sidebar-logo">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
    <span>DBA Azure<br/>Project</span>
  </div>
  <nav>
    <a href="#dashboard" class="active">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>
      Dashboard
    </a>
    <a href="#hospitals">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9,22 9,12 15,12 15,22"/></svg>
      Hospitals
    </a>
    <a href="#metrics">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>
      Quality Metrics
    </a>
    <a href="#etl">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17,1 21,5 17,9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7,23 3,19 7,15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
      ETL Operations
    </a>
    <a href="#export">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7,10 12,15 17,10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      Data Export
    </a>
    <div class="nav-sep"></div>
    <a href="#about">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
      About
    </a>
    <a href="#how-it-works">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12,6 12,12 16,14"/></svg>
      How It Works
    </a>
    <a href="index.html">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>
      Project Docs
    </a>
  </nav>
  <div class="sidebar-footer">
    Azure SQL · westus3<br/>
    App Insights · eastus
  </div>
</aside>

<main>
  <div class="topbar">
    <h1>Hospital Quality Dashboard</h1>
    <div style="display:flex;align-items:center;gap:12px">
      <span class="badge disabled" id="data-badge">API DISABLED</span>
      <span class="generated" id="gen-time"></span>
    </div>
  </div>
  <div class="cost-notice">Notice: Live API and full export are disabled for cost efficiency. They can be re-enabled by starting the Azure Function App.</div>

  <div class="content">

    <!-- KPI Row -->
    <div class="kpi-grid" id="dashboard">
      <div class="kpi">
        <div class="kpi-header">
          <div class="kpi-icon blue">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9,22 9,12 15,12 15,22"/></svg>
          </div>
          <span class="badge snap">CMS</span>
        </div>
        <div class="kpi-value" id="kpi-hospitals">—</div>
        <div class="kpi-label">Total Hospitals</div>
        <div class="kpi-sub">50 States + DC</div>
      </div>
      <div class="kpi">
        <div class="kpi-header">
          <div class="kpi-icon yellow">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2"><polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/></svg>
          </div>
          <span class="badge snap">AVG</span>
        </div>
        <div class="kpi-value" id="kpi-rating">—</div>
        <div class="kpi-label">Avg Overall Rating</div>
        <div class="kpi-sub">Scale 1–5</div>
      </div>
      <div class="kpi">
        <div class="kpi-header">
          <div class="kpi-icon green">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22,4 12,14.01 9,11.01"/></svg>
          </div>
          <span class="badge snap">SNAPSHOT</span>
        </div>
        <div class="kpi-value" id="kpi-emergency">—</div>
        <div class="kpi-label">Emergency Services</div>
        <div class="kpi-sub">Have ER capability</div>
      </div>
      <div class="kpi">
        <div class="kpi-header">
          <div class="kpi-icon purple">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>
          </div>
          <span class="badge snap">SNAPSHOT</span>
        </div>
        <div class="kpi-value" id="kpi-metrics">—</div>
        <div class="kpi-label">Quality Metrics</div>
        <div class="kpi-sub">Unplanned visit records</div>
      </div>
    </div>

    <!-- Charts Row 1 -->
    <div class="charts-grid wide" id="hospitals">
      <div class="card">
        <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
          <span>Hospitals by State (Top 20)</span>
          <button class="btn-export" onclick="exportStates()">↓ CSV</button>
        </div>
        <div class="chart-wrap"><canvas id="chartStates"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">Overall Rating Distribution</div>
        <div class="chart-wrap"><canvas id="chartRating"></canvas></div>
      </div>
    </div>

    <!-- Charts Row 2 -->
    <div class="charts-grid" id="metrics">
      <div class="card">
        <div class="card-title">Hospital Types</div>
        <div class="chart-wrap"><canvas id="chartTypes"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">National Quality Comparison</div>
        <div class="chart-wrap"><canvas id="chartNational"></canvas></div>
      </div>
    </div>

    <!-- ETL Table -->
    <div class="card" id="etl">
      <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>ETL Run History</span>
        <div style="display:flex;align-items:center;gap:8px">
          <span class="badge disabled">DISABLED</span>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Run ID</th><th>Started</th><th>Status</th>
            <th>Hospitals</th><th>Metrics</th><th>Duration</th>
          </tr>
        </thead>
        <tbody id="etl-body"></tbody>
      </table>
    </div>

    <!-- Data Export -->
    <div class="card" id="export">
      <div class="card-title">Data Export</div>
      <div class="export-grid">

        <div class="export-item">
          <div class="export-icon" style="background:rgba(59,130,246,.15)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9,22 9,12 15,12 15,22"/></svg>
          </div>
          <div class="export-info">
            <div class="export-name">All Hospitals</div>
            <div class="export-desc">5,433 hospitals · 12 columns including address, phone, GPS coordinates</div>
            <div class="export-cols">FacilityID · FacilityName · Address · City · State · ZipCode · Phone · HospitalType · EmergencyServices · OverallRating · Latitude · Longitude</div>
          </div>
          <button class="btn-export-lg" id="btn-all-hospitals" disabled title="Disabled while the Azure Function App is stopped for cost control">Disabled</button>
        </div>

        <div class="export-item">
          <div class="export-icon" style="background:rgba(168,85,247,.15)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>
          </div>
          <div class="export-info">
            <div class="export-name">Quality Metrics</div>
            <div class="export-desc">67,088 records · hospital-level clinical quality measures</div>
            <div class="export-cols">FacilityID · FacilityName · State · HospitalType · MeasureID · MeasureName · Score · ComparedToNational · NumberOfPatients · PeriodStart · PeriodEnd</div>
          </div>
          <button class="btn-export-lg" id="btn-quality-metrics" disabled title="Disabled while the Azure Function App is stopped for cost control">Disabled</button>
        </div>

        <div class="export-item">
          <div class="export-icon" style="background:rgba(34,197,94,.15)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2"><path d="M17.657 16.657L13.414 20.9a1.998 1.998 0 0 1-2.827 0l-4.244-4.243a8 8 0 1 1 11.314 0z"/><circle cx="12" cy="11" r="3"/></svg>
          </div>
          <div class="export-info">
            <div class="export-name">State Summary</div>
            <div class="export-desc">51 states/territories · aggregate hospital stats per state</div>
            <div class="export-cols">State · TotalHospitals · AvgRating · WithEmergency · TopRatedCount</div>
          </div>
          <button class="btn-export-lg" onclick="exportStates()">↓ CSV</button>
        </div>

        <div class="export-item">
          <div class="export-icon" style="background:rgba(234,179,8,.15)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2"><polyline points="17,1 21,5 17,9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7,23 3,19 7,15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
          </div>
          <div class="export-info">
            <div class="export-name">ETL Run Log</div>
            <div class="export-desc">Last 8 ETL runs · pipeline execution history</div>
            <div class="export-cols">LogID · RunStart · Status · HospitalsLoaded · MetricsLoaded · DurationSec</div>
          </div>
          <button class="btn-export-lg" onclick="exportETL()">↓ CSV</button>
        </div>

      </div>
    </div>

    <!-- About -->
    <div class="card" id="about">
      <div class="card-title">About This Project</div>
      <div class="about-grid">
        <div class="about-desc">
          <p>An end-to-end data pipeline that pulls US hospital quality data from the CMS (Centers for Medicare &amp; Medicaid Services) public API, loads it into Azure SQL Database via automated ETL, and serves it through a REST API and this interactive dashboard.</p>
          <p>Built to demonstrate DBA fundamentals — schema design, index tuning, backup &amp; recovery — alongside cloud data engineering with Azure managed services.</p>
          <div class="about-note">The CMS datasets are publicly available and fully de-identified under HIPAA Safe Harbor (45 CFR &sect;164.514(b)). No Protected Health Information is involved.</div>
        </div>
        <div class="about-meta">
          <div class="about-label">Tech Stack</div>
          <div class="tech-badges">
            <span class="tech-badge python">Python 3.11</span>
            <span class="tech-badge azure">Azure Functions</span>
            <span class="tech-badge azure">Azure SQL</span>
            <span class="tech-badge azure">Key Vault</span>
            <span class="tech-badge azure">App Insights</span>
            <span class="tech-badge misc">Bicep (IaC)</span>
            <span class="tech-badge misc">Chart.js</span>
            <span class="tech-badge misc">GitHub Actions</span>
          </div>
          <div class="about-label" style="margin-top:14px">Data Sources (CMS Public API)</div>
          <div class="data-sources">
            <div class="data-src">
              <span class="data-src-name">Hospital General Information</span>
              <span class="data-src-detail">~5,400 records &middot; Quarterly</span>
            </div>
            <div class="data-src">
              <span class="data-src-name">Unplanned Hospital Visits</span>
              <span class="data-src-detail">~67,000 metrics &middot; Quarterly</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- How It Works -->
    <div class="card" id="how-it-works">
      <div class="card-title">How It Works</div>
      <div class="flow-steps">
        <div class="flow-step">
          <div class="flow-icon" style="background:rgba(34,197,94,.15)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
          </div>
          <div class="flow-title">CMS Public API</div>
          <div class="flow-desc">HTTP GET, no auth<br/>Quarterly data updates</div>
        </div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-step">
          <div class="flow-icon" style="background:rgba(59,130,246,.15)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
          </div>
          <div class="flow-title">Azure Function App</div>
          <div class="flow-desc">Timer Trigger (CRON)<br/>ETL runs twice daily</div>
        </div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-step">
          <div class="flow-icon" style="background:rgba(168,85,247,.15)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
          </div>
          <div class="flow-title">Azure SQL Database</div>
          <div class="flow-desc">Serverless tier, 3 tables<br/>MERGE upsert, no duplicates</div>
        </div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-step">
          <div class="flow-icon" style="background:rgba(234,179,8,.15)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>
          </div>
          <div class="flow-title">REST API + Dashboard</div>
          <div class="flow-desc">5 API endpoints<br/>Chart.js + CSV export</div>
        </div>
      </div>
      <div class="flow-details">
        <div class="flow-detail">
          <span class="flow-detail-label">ETL Schedule</span>
          <span class="flow-detail-value">UTC 00:00 &amp; 12:00 daily</span>
        </div>
        <div class="flow-detail">
          <span class="flow-detail-label">Upsert Strategy</span>
          <span class="flow-detail-value">SQL MERGE on FacilityID &mdash; idempotent, no duplicates</span>
        </div>
        <div class="flow-detail">
          <span class="flow-detail-label">Secret Management</span>
          <span class="flow-detail-value">Azure Key Vault + Managed Identity</span>
        </div>
        <div class="flow-detail">
          <span class="flow-detail-label">Monitoring</span>
          <span class="flow-detail-value">Application Insights + Azure Monitor alerts</span>
        </div>
      </div>
    </div>

  </div>
</main>

<script>
{data_js}

const API = 'https://func-dba-xvel6ncdvwsre.azurewebsites.net/api';
const API_DISABLED = true;

// ── CSV Export ────────────────────────────────────────────────────────────────
function downloadCSV(filename, headers, rows) {{
  const escape = v => {{ const s = String(v ?? ''); return (s.includes(',') || s.includes('"')) ? '"' + s.replace(/"/g,'""') + '"' : s; }};
  const lines = [headers.join(','), ...rows.map(r => headers.map(h => escape(r[h])).join(','))];
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([lines.join('\\n')], {{type:'text/csv'}}));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}}

function exportStates() {{
  const src = window._liveStates || DB_DATA.top_states.map(d => ({{
    state: d.state, total_hospitals: d.hospitals, avg_rating: d.avg_rating,
    with_emergency: '', top_rated_count: ''
  }}));
  downloadCSV('hospital_states.csv', ['state','total_hospitals','avg_rating','with_emergency','top_rated_count'], src);
}}

function exportETL() {{
  downloadCSV('etl_log.csv', ['log_id','run_start','status','hospitals_loaded','metrics_loaded','duration_sec'], DB_DATA.etl_log);
}}

async function exportAllHospitals() {{
  const btn = document.getElementById('btn-all-hospitals');
  btn.disabled = true; btn.textContent = '⏳ Fetching…';
  try {{
    let all = [], offset = 0, total = Infinity;
    while (all.length < total) {{
      const res = await fetch(`${{API}}/hospitals?limit=500&offset=${{offset}}`, {{signal: AbortSignal.timeout(30000)}});
      if (!res.ok) throw new Error();
      const d = await res.json();
      total = d.total;
      all = all.concat(d.data);
      offset += d.data.length;
      btn.textContent = `⏳ ${{all.length}}/${{total}}`;
      if (d.data.length === 0) break;
    }}
    downloadCSV('hospitals_all.csv',
      ['FacilityID','FacilityName','Address','City','State','ZipCode','Phone',
       'HospitalType','EmergencyServices','OverallRating','Latitude','Longitude'],
      all);
    btn.textContent = `✓ ${{all.length}} rows`;
    setTimeout(() => {{ btn.disabled = false; btn.textContent = '↓ All Hospitals'; }}, 3000);
  }} catch (_) {{
    btn.textContent = '✗ Failed';
    setTimeout(() => {{ btn.disabled = false; btn.textContent = '↓ All Hospitals'; }}, 2000);
  }}
}}

async function exportQualityMetrics() {{
  const btn = document.getElementById('btn-quality-metrics');
  btn.disabled = true; btn.textContent = '⏳ Fetching…';
  try {{
    let all = [], offset = 0, total = Infinity;
    while (all.length < total) {{
      const res = await fetch(`${{API}}/metrics/export?limit=2000&offset=${{offset}}`, {{signal: AbortSignal.timeout(60000)}});
      if (!res.ok) throw new Error('API error');
      const d = await res.json();
      total = d.total;
      all = all.concat(d.data);
      offset += d.data.length;
      btn.textContent = `⏳ ${{all.length.toLocaleString()}}/${{total.toLocaleString()}}`;
      if (d.data.length === 0) break;
    }}
    downloadCSV('quality_metrics.csv',
      ['FacilityID','FacilityName','State','City','HospitalType','EmergencyServices',
       'OverallRating','MeasureID','MeasureName','Score','ComparedToNational',
       'NumberOfPatients','PeriodStart','PeriodEnd'],
      all);
    btn.textContent = `✓ ${{all.length.toLocaleString()}} rows`;
    setTimeout(() => {{ btn.disabled = false; btn.textContent = '↓ Quality Metrics'; }}, 3000);
  }} catch (_) {{
    btn.textContent = '✗ Failed';
    setTimeout(() => {{ btn.disabled = false; btn.textContent = '↓ Quality Metrics'; }}, 2000);
  }}
}}

function setBadge(live) {{
  const el = document.getElementById('data-badge');
  if (API_DISABLED) {{
    el.textContent = 'API DISABLED';
    el.className = 'badge disabled';
    return;
  }}
  if (live) {{
    el.textContent = '● LIVE';
    el.className = 'badge live';
  }} else {{
    el.textContent = 'SNAPSHOT';
    el.className = 'badge snap';
  }}
}}

function renderKPIs(kpi, metricsCount) {{
  document.getElementById('kpi-hospitals').textContent = kpi.total_hospitals.toLocaleString();
  document.getElementById('kpi-rating').textContent = (+kpi.avg_rating||0).toFixed(2) + ' ★';
  document.getElementById('kpi-emergency').textContent = kpi.with_emergency.toLocaleString();
  document.getElementById('kpi-metrics').textContent = metricsCount.toLocaleString();
}}

function renderETL(rows) {{
  const tbody = document.getElementById('etl-body');
  tbody.innerHTML = '';
  rows.forEach(r => {{
    const cls = r.status === 'SUCCESS' ? 'status-ok' : r.status === 'FAILED' ? 'status-fail' : 'status-run';
    tbody.innerHTML += `<tr>
      <td>#${{r.log_id}}</td>
      <td>${{r.run_start||'—'}}</td>
      <td class="${{cls}}">${{r.status}}</td>
      <td>${{(r.hospitals_loaded||0).toLocaleString()}}</td>
      <td>${{(r.metrics_loaded||0).toLocaleString()}}</td>
      <td>${{r.duration_sec != null ? r.duration_sec + 's' : '—'}}</td>
    </tr>`;
  }});
}}

// ── Step 1: Render snapshot immediately ──────────────────────────────────────
renderKPIs(DB_DATA.kpi, DB_DATA.metrics_count);
document.getElementById('gen-time').textContent = 'Snapshot: ' + DB_DATA.generated_at;
renderETL(DB_DATA.etl_log);

Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';

const chartStates = new Chart(document.getElementById('chartStates'), {{
  type: 'bar',
  data: {{
    labels: DB_DATA.top_states.map(d => d.state),
    datasets: [{{ label: 'Hospitals', data: DB_DATA.top_states.map(d => d.hospitals), backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 4 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 10 }} }} }}, y: {{ grid: {{ color: '#1e293b' }}, beginAtZero: true }} }}
  }}
}});

const rColors = ['#ef4444','#f97316','#eab308','#22c55e','#3b82f6'];
new Chart(document.getElementById('chartRating'), {{
  type: 'doughnut',
  data: {{ labels: DB_DATA.rating_dist.map(d => d.rating + ' Star'), datasets: [{{ data: DB_DATA.rating_dist.map(d => d.count), backgroundColor: rColors, borderWidth: 2, borderColor: '#1e293b' }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right', labels: {{ font: {{ size: 11 }}, padding: 10 }} }} }} }}
}});

const typeColors = ['#3b82f6','#22c55e','#a855f7','#f97316','#14b8a6','#f43f5e','#84cc16'];
new Chart(document.getElementById('chartTypes'), {{
  type: 'bar',
  data: {{
    labels: DB_DATA.hospital_types.map(d => d.type.length > 25 ? d.type.substring(0,22)+'...' : d.type),
    datasets: [{{ label: 'Count', data: DB_DATA.hospital_types.map(d => d.count), backgroundColor: typeColors, borderRadius: 4 }}]
  }},
  options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ grid: {{ color: '#1e293b' }}, beginAtZero: true }}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 10 }} }} }} }} }}
}});

const natColors = {{ 'Better':'#22c55e','Same':'#3b82f6','Worse':'#ef4444','Not Available':'#64748b' }};
new Chart(document.getElementById('chartNational'), {{
  type: 'doughnut',
  data: {{ labels: DB_DATA.national_comparison.map(d => d.result), datasets: [{{ data: DB_DATA.national_comparison.map(d => d.count), backgroundColor: DB_DATA.national_comparison.map(d => natColors[d.result]||'#64748b'), borderWidth: 2, borderColor: '#1e293b' }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right', labels: {{ font: {{ size: 11 }}, padding: 10 }} }} }} }}
}});

// ── Nav active state (IntersectionObserver) ─────────────────────────────────
(function() {{
  const sections = ['about','how-it-works','dashboard','hospitals','metrics','etl','export'];
  const links = document.querySelectorAll('nav a[href^="#"]');
  const observer = new IntersectionObserver(function(entries) {{
    entries.forEach(function(e) {{
      if (e.isIntersecting) {{
        links.forEach(function(a) {{ a.classList.remove('active'); }});
        var match = document.querySelector('nav a[href="#' + e.target.id + '"]');
        if (match) match.classList.add('active');
      }}
    }});
  }}, {{ rootMargin: '-20% 0px -60% 0px' }});
  sections.forEach(function(id) {{
    var el = document.getElementById(id);
    if (el) observer.observe(el);
  }});
  links.forEach(function(a) {{
    a.addEventListener('click', function() {{
      links.forEach(function(l) {{ l.classList.remove('active'); }});
      a.classList.add('active');
    }});
  }});
}})();

// ── Step 2: Try live API in background ───────────────────────────────────────
(async () => {{
  if (API_DISABLED) {{
    setBadge(false);
    return;
  }}
  try {{
    const [statesRes, hospitalsRes] = await Promise.all([
      fetch(API + '/states/summary', {{ signal: AbortSignal.timeout(15000) }}),
      fetch(API + '/hospitals?limit=1', {{ signal: AbortSignal.timeout(15000) }}),
    ]);
    if (!statesRes.ok || !hospitalsRes.ok) throw new Error('API error');

    const statesData    = await statesRes.json();
    const hospitalsData = await hospitalsRes.json();

    const top20 = statesData.data.slice(0, 20);
    window._liveStates = statesData.data;
    chartStates.data.labels = top20.map(d => d.state);
    chartStates.data.datasets[0].data = top20.map(d => d.total_hospitals);
    chartStates.update();

    const totalHospitals = hospitalsData.total;
    const withEmergency  = statesData.data.reduce((s, d) => s + (d.with_emergency||0), 0);
    const ratedStates    = statesData.data.filter(d => d.avg_rating > 0);
    const avgRating      = ratedStates.length
      ? ratedStates.reduce((s, d) => s + (+d.avg_rating * d.total_hospitals), 0) /
        ratedStates.reduce((s, d) => s + d.total_hospitals, 0)
      : DB_DATA.kpi.avg_rating;

    renderKPIs(
      {{ total_hospitals: totalHospitals, avg_rating: avgRating, with_emergency: withEmergency }},
      DB_DATA.metrics_count
    );

    const pst = new Date(Date.now() - 8*3600*1000);
    const now = pst.toISOString().replace('T',' ').substring(0,16) + ' PST';
    document.getElementById('gen-time').textContent = 'Live: ' + now;
    setBadge(true);

  }} catch (_) {{
    setBadge(false);
  }}
}})();
</script>
</body>
</html>"""

out_path = os.path.join(os.path.dirname(__file__), 'site', 'dashboard.html')
with open(out_path, 'w') as f:
    f.write(html)

print(f"Built: site/dashboard.html ({len(html):,} bytes)")
print(f"  Hospitals: {data['kpi']['total_hospitals']:,}")
print(f"  Metrics:   {data['metrics_count']:,}")
print(f"  States:    {len(data['top_states'])}")
