"""
Shared DB connection helper.
Locally: reads DB_CONNECTION_STRING from environment.
Azure:   reads secret from Key Vault via DefaultAzureCredential (Managed Identity).
"""

import os
import pyodbc

_conn_str: str | None = None


def _build_conn_str() -> str:
    global _conn_str
    if _conn_str:
        return _conn_str

    # 1. Direct env var (local .env or Azure App Settings)
    direct = os.getenv("DB_CONNECTION_STRING")
    if direct:
        _conn_str = direct
        return _conn_str

    # 2. Key Vault via Managed Identity (production Azure Function)
    kv_url = os.getenv("AZURE_KEY_VAULT_URL")
    if kv_url:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
        client = SecretClient(vault_url=kv_url, credential=DefaultAzureCredential())
        _conn_str = client.get_secret("DB-CONNECTION-STRING").value
        return _conn_str

    raise EnvironmentError("Set DB_CONNECTION_STRING or AZURE_KEY_VAULT_URL")


def get_conn() -> pyodbc.Connection:
    conn = pyodbc.connect(_build_conn_str(), timeout=30)
    conn.autocommit = True
    return conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    cols = [c[0] for c in cursor.description]
    rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return rows
