from google.cloud import bigquery
from google.oauth2 import service_account
import os

KEY_PATH = "/root/.openclaw/workspace/keys/gcp_key.json"

try:
    credentials = service_account.Credentials.from_service_account_file(KEY_PATH)
    client = bigquery.Client(credentials=credentials, project=credentials.project_id)
    
    print(f"成功连接到项目: {credentials.project_id}")
    
    datasets = list(client.list_datasets())
    if not datasets:
        print("未找到任何数据集 (Dataset)")
    else:
        print(f"找到 {len(datasets)} 个数据集:")
        for dataset in datasets:
            print(f"  - Dataset: {dataset.dataset_id}")
            tables = list(client.list_tables(dataset.dataset_id))
            if not tables:
                print("    (无表)")
            else:
                for table in tables:
                    print(f"    - Table: {table.table_id}")

except Exception as e:
    print(f"连接或查询失败: {e}")
