from google.cloud import bigquery
from google.oauth2 import service_account
from datetime import datetime, timedelta, timezone
import requests
import json
import logging
import sys
import os

# ================= 配置 =================
KEY_PATH = "/root/.openclaw/workspace/keys/gcp_key.json"
WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/5fd3240b-bc3b-4533-9e6e-4b67b2070c62"
DATASET_ID = "AICost"
TABLE_NAME = "gcp_billing_export_v1_01A413_A6C40C_96C18F"  # 标准导出表
PROJECT_ID = "atomic-venture-475014-n1"

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

def get_billing_data():
    try:
        credentials = service_account.Credentials.from_service_account_file(KEY_PATH)
        client = bigquery.Client(credentials=credentials, project=credentials.project_id)
        
        # 获取昨天的日期 (UTC)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        
        # 1. 查询昨日总消耗
        query_total = f"""
            SELECT
                SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) as total_cost
            FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}`
            WHERE DATE(_PARTITIONDATE) = '{yesterday_str}'
        """
        
        # 2. 查询过去7天消耗
        query_7days = f"""
            SELECT
                SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) as total_cost
            FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}`
            WHERE DATE(_PARTITIONDATE) >= DATE_SUB('{yesterday_str}', INTERVAL 6 DAY)
        """
        
        # 3. 按 API Key (Label) 细分
        # 尝试查找 labels.key 为 'api_key' 或 'key_name' 或 'agent_id' 的值
        # 如果没有标签，就归类为 'Unlabeled'
        # 注意：标准导出表中 labels 是 REPEATED RECORD 类型 (key, value)
        query_by_key = f"""
            SELECT
                IFNULL((SELECT value FROM UNNEST(labels) WHERE key = 'api_key'), 'Unlabeled') as api_key,
                project.name as project_name,
                SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) as cost
            FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}`
            WHERE DATE(_PARTITIONDATE) = '{yesterday_str}'
            GROUP BY 1, 2
            ORDER BY cost DESC
        """

        # 4. 过去7天每日趋势
        query_trend = f"""
            SELECT
                DATE(_PARTITIONDATE) as date,
                SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) as cost
            FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}`
            WHERE DATE(_PARTITIONDATE) >= DATE_SUB('{yesterday_str}', INTERVAL 6 DAY)
            GROUP BY 1
            ORDER BY 1
        """

        # 执行查询
        total_cost = list(client.query(query_total).result())[0].total_cost or 0.0
        seven_days_cost = list(client.query(query_7days).result())[0].total_cost or 0.0
        key_costs = list(client.query(query_by_key).result())
        trend_data = list(client.query(query_trend).result())
        
        return {
            "date": yesterday_str,
            "total_cost": total_cost,
            "seven_days_cost": seven_days_cost,
            "keys": [{"key": row.api_key, "project": row.project_name, "cost": row.cost} for row in key_costs],
            "trend": [{"date": row.date.strftime('%Y-%m-%d'), "cost": row.cost} for row in trend_data]
        }

    except Exception as e:
        logger.error(f"查询 BigQuery 失败: {e}")
        return None

def send_feishu_text(data):
    if not data:
        return

    # 格式化 API Key 列表
    key_text = ""
    for k in data['keys']:
        if k['cost'] > 0:
            key_name = k['key']
            if key_name == 'Unlabeled':
                key_name = f"Unlabeled ({k['project'] or 'Unknown Project'})"
            key_text += f"• {key_name}: ${k['cost']:.2f}\n"
    
    # 格式化趋势
    trend_text = ""
    for t in data['trend']:
        icon = "⚪"
        # 简单阈值标记
        if t['cost'] > 100: icon = "🔴" 
        elif t['cost'] > 50: icon = "🟡"
        
        trend_text += f"{icon} {t['date']}: ${t['cost']:.2f}\n"

    # 构建纯文本消息
    content = f"""📊 Google Cloud 每日消耗报告
📅 报告日期: {data['date']}
💰 单日消耗: ${data['total_cost']:.2f}
📊 过去7天总消耗: ${data['seven_days_cost']:.2f}
🔍 数据来源: BigQuery Export

📋 按 API Key 细分:
{key_text}
📈 过去7天消耗趋势:
{trend_text}
📦 关联项目/Key数量: {len(data['keys'])}"""

    payload = {
        "msg_type": "text",
        "content": {
            "text": content
        }
    }

    try:
        resp = requests.post(WEBHOOK_URL, json=payload)
        resp.raise_for_status()
        logger.info("飞书消息发送成功")
    except Exception as e:
        logger.error(f"飞书发送失败: {e}")

if __name__ == "__main__":
    logger.info("开始获取 GCP 账单...")
    data = get_billing_data()
    if data:
        logger.info(f"获取成功，准备发送: {data['date']}")
        send_feishu_text(data)
    else:
        logger.error("获取数据失败")
