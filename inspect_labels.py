from google.cloud import bigquery
from google.oauth2 import service_account
import json

KEY_PATH = "/root/.openclaw/workspace/keys/gcp_key.json"
DATASET_ID = "AICost"
TABLE_NAME = "gcp_billing_export_v1_01A413_A6C40C_96C18F"
PROJECT_ID = "atomic-venture-475014-n1"

credentials = service_account.Credentials.from_service_account_file(KEY_PATH)
client = bigquery.Client(credentials=credentials, project=credentials.project_id)

# 查询最近 10 条记录的 labels 和 system_labels，看看有没有线索
query = f"""
    SELECT
        service.description as service_name,
        sku.description as sku_name,
        labels,
        system_labels
    FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}`
    WHERE cost > 0
    LIMIT 10
"""

try:
    results = client.query(query).result()
    print("=== BigQuery Sample Data (Labels) ===")
    for row in results:
        print(f"Service: {row.service_name}")
        print(f"SKU: {row.sku_name}")
        print(f"Labels: {row.labels}")
        print(f"System Labels: {row.system_labels}")
        print("-" * 20)
except Exception as e:
    print(f"Error: {e}")
