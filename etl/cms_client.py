"""
CMS Provider Data API client.
Fetches Hospital General Information and Unplanned Hospital Visits datasets.
"""

import requests
import time

CMS_BASE = "https://data.cms.gov/provider-data/api/1/datastore/query"
HOSPITAL_DATASET = "xubh-q36u"
VISITS_DATASET   = "632h-zaca"
PAGE_SIZE        = 1000
MAX_RETRIES      = 3
RETRY_DELAY      = 5


def _get_page(dataset_id: str, offset: int, session: requests.Session) -> dict:
    url = f"{CMS_BASE}/{dataset_id}/0"
    params = {
        "limit":  PAGE_SIZE,
        "offset": offset,
        "count":  "true",
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            print(f"  [retry {attempt}/{MAX_RETRIES}] {exc}")
            time.sleep(RETRY_DELAY)


def fetch_hospitals() -> list[dict]:
    """Return all records from the Hospital General Information dataset."""
    session = requests.Session()
    records = []
    offset = 0

    print("Fetching Hospital General Information from CMS...")
    while True:
        data = _get_page(HOSPITAL_DATASET, offset, session)
        page = data.get("results", [])
        total = data.get("count", 0)
        records.extend(page)
        offset += len(page)
        print(f"  fetched {offset}/{total}")
        if offset >= total or not page:
            break

    return records


def fetch_visit_metrics() -> list[dict]:
    """Return all records from the Unplanned Hospital Visits dataset."""
    session = requests.Session()
    records = []
    offset = 0

    print("Fetching Unplanned Hospital Visits from CMS...")
    while True:
        data = _get_page(VISITS_DATASET, offset, session)
        page = data.get("results", [])
        total = data.get("count", 0)
        records.extend(page)
        offset += len(page)
        print(f"  fetched {offset}/{total}")
        if offset >= total or not page:
            break

    return records
