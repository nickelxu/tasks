#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
恐惧贪婪指数监控机器人
每天定时获取 BTC 恐惧贪婪指数并发送飞书通知
支持多数据源：Alternative.me 和 CoinMarketCap
"""

import requests
import time
import sys
import logging
from datetime import datetime, timezone, timedelta

# ================= 配置区域 =================

# 飞书 Webhook 地址
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/0096a17c-3ea5-4277-b452-bc2f4f57ad4c"

# 策略阈值（基于 Alternative.me 指数，金额单位：人民币）
STRATEGY = {
    "buy_lv1": {"limit": 25, "amt": 2000, "desc": "恐惧 (20-25)"},
    "buy_lv2": {"limit": 20, "amt": 5000, "desc": "极度恐惧 (15-20)"},
    "buy_lv3": {"limit": 15, "amt": 10000, "desc": "极度恐惧 (<20)"},  # 15以下统一1万
    
    "sell_lv1": {"limit": 75, "amt": 2000, "desc": "贪婪 (75-80)"},
    "sell_lv2": {"limit": 80, "amt": 10000, "desc": "极度贪婪 (>80)"}
}

# 完整投资策略说明（每天提醒中显示）
STRATEGY_SUMMARY = """
📋 我的投资策略
━━━━━━━━━━━━━━━━━━
【买入策略】
• 指数 20-25 (恐惧)：买入 ¥2,000 等值BTC
• 指数 15-20 (极度恐惧)：买入 ¥5,000 等值BTC
• 指数 <15 (极度恐惧)：买入 ¥10,000 等值BTC

【卖出策略】
• 指数 75-80 (贪婪)：卖出 ¥2,000 等值BTC
• 指数 >80 (极度贪婪)：卖出 ¥10,000 等值BTC

【持有策略】
• 指数 25-75 (中性区间)：持有不动，无操作
━━━━━━━━━━━━━━━━━━"""

# 最大重试次数
MAX_RETRIES = 18 
RETRY_INTERVAL = 600  # 秒 (10分钟)

# ===========================================

# 配置日志
LOG_DIR = "/root/.openclaw/workspace/logs"  # 修改为 workspace 下的 logs 目录，确保有权限
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
# 如果日志目录存在，添加 FileHandler
import os
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
logging.getLogger().addHandler(logging.FileHandler(f"{LOG_DIR}/fear_greed.log", encoding="utf-8"))

logger = logging.getLogger(__name__)

# HTTP 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def get_alternative_index():
    """
    获取 Alternative.me 恐惧贪婪指数
    返回: (数值, 分类, 数据日期, 是否今日)
    """
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        latest = data["data"][0]
        value = int(latest["value"])
        timestamp = int(latest["timestamp"])
        classification = latest.get("value_classification", "Unknown")
        
        # 修正时区处理
        data_date = datetime.fromtimestamp(timestamp, timezone.utc).date()
        current_date = datetime.now(timezone.utc).date()
        is_today = (data_date == current_date)
        
        return value, classification, data_date, is_today
    except Exception as e:
        logger.error(f"Alternative.me API 请求失败: {e}")
        return None, None, None, False


def get_cmc_index():
    """
    获取 CoinMarketCap 恐惧贪婪指数
    返回: (数值, 分类, BTC价格)
    """
    try:
        now = int(time.time())
        start = now - 86400 * 7  # 7天前（CMC API 需要较长时间范围才返回 historicalValues）
        url = f"https://api.coinmarketcap.com/data-api/v3/fear-greed/chart?start={start}&end={now}"
        
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status", {}).get("error_code") == "0":
            historical = data.get("data", {}).get("historicalValues", {})
            now_data = historical.get("now", {})
            
            if now_data:
                value = int(now_data.get("score", 0))
                classification = now_data.get("name", "Unknown")
                
                # 获取最新的 BTC 价格
                data_list = data.get("data", {}).get("dataList", [])
                btc_price = float(data_list[-1].get("btcPrice", 0)) if data_list else 0
                
                if value > 0:  # 确保获取到有效数值
                    return value, classification, btc_price
            
            logger.warning(f"CMC API 返回数据不完整: historicalValues={historical}")
            return None, None, None
        else:
            logger.warning(f"CMC API 返回错误: {data.get('status')}")
            return None, None, None
    except Exception as e:
        logger.error(f"CoinMarketCap API 请求失败: {e}")
        return None, None, None


def get_classification_cn(value):
    """根据数值返回中文分类"""
    if value < 20:
        return "极度恐惧"
    elif value < 40:
        return "恐惧"
    elif value < 60:
        return "中性"
    elif value < 80:
        return "贪婪"
    else:
        return "极度贪婪"


def send_feishu(title, text):
    """发送飞书通知"""
    if "指数" not in title:
        title += " (指数监控)"
    
    headers = {"Content-Type": "application/json"}
    data = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": [[{"tag": "text", "text": text}]]
                }
            }
        }
    }
    
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=data, headers=headers, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("code") == 0:
                logger.info(f"飞书通知发送成功: {title}")
            else:
                logger.warning(f"飞书通知返回异常: {result}")
        else:
            logger.warning(f"飞书通知HTTP异常: {resp.status_code}")
    except Exception as e:
        logger.error(f"飞书通知发送失败: {e}")


def analyze_and_send(alt_index, alt_class, cmc_index, cmc_class, btc_price):
    """核心策略分析 - 基于 Alternative.me 指数"""
    bj_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    
    # 策略判断（基于 Alternative.me）
    index = alt_index
    if index < 20:  # 20以下都是买入区间
        if index < 15:
            msg_title = f"🚨 抄底机会！指数 {index}"
            strategy_msg = f"当前处于【极度恐惧 (<20)】\n👉 今日建议：买入 ¥{STRATEGY['buy_lv3']['amt']:,} 等值BTC"
        else:  # 15-20
            msg_title = f"⚡ 买入提醒！指数 {index}"
            strategy_msg = f"当前处于【极度恐惧 (15-20)】\n👉 今日建议：买入 ¥{STRATEGY['buy_lv2']['amt']:,} 等值BTC"
    elif 20 <= index < 25:
        msg_title = f"💡 定投提醒！指数 {index}"
        strategy_msg = f"当前处于【恐惧 (20-25)】\n👉 今日建议：买入 ¥{STRATEGY['buy_lv1']['amt']:,} 等值BTC"
    elif index > 80:
        msg_title = f"🔥 极度贪婪！指数 {index}"
        strategy_msg = f"当前处于【极度贪婪 (>80)】\n👉 今日建议：卖出 ¥{STRATEGY['sell_lv2']['amt']:,} 等值BTC"
    elif 75 <= index <= 80:
        msg_title = f"💰 止盈提醒！指数 {index}"
        strategy_msg = f"当前处于【贪婪 (75-80)】\n👉 今日建议：卖出 ¥{STRATEGY['sell_lv1']['amt']:,} 等值BTC"
    else:
        msg_title = f"🍵 日常巡检：指数 {index}"
        strategy_msg = f"当前处于【观望区间 (25-75)】\n👉 今日建议：持有不动，无操作"
    
    # 构建双指数对比消息
    msg_content = f"{strategy_msg}\n\n"
    msg_content += "━━━━━━━━━━━━━━━━━━\n"
    msg_content += "📊 恐惧贪婪指数对比\n"
    msg_content += "━━━━━━━━━━━━━━━━━━\n"
    msg_content += f"🔹 Alternative.me: {alt_index} ({get_classification_cn(alt_index)})\n"
    
    if cmc_index is not None:
        msg_content += f"🔸 CoinMarketCap: {cmc_index} ({get_classification_cn(cmc_index)})\n"
        diff = abs(alt_index - cmc_index)
        if diff > 10:
            msg_content += f"⚠️ 两个指数差异较大 ({diff}点)\n"
    else:
        msg_content += f"🔸 CoinMarketCap: 获取失败\n"
    
    # BTC 价格
    if btc_price and btc_price > 0:
        msg_content += f"\n💰 BTC 价格: ${btc_price:,.2f}\n"
    
    # 添加完整投资策略说明
    msg_content += f"\n{STRATEGY_SUMMARY}\n"
    
    msg_content += f"\n🕐 北京时间: {bj_time}"
    
    send_feishu(msg_title, msg_content)
    logger.info(f"分析完成 - Alt: {alt_index}, CMC: {cmc_index}")


def main():
    bj_time = datetime.now(timezone(timedelta(hours=8)))
    logger.info(f"🚀 任务启动: {bj_time.strftime('%Y-%m-%d %H:%M:%S')}")

    retry_count = 0
    alt_index = None
    alt_class = None
    data_date = None
    
    # 主循环：等待 Alternative.me 更新今日数据
    while retry_count < MAX_RETRIES:
        alt_index, alt_class, data_date, is_today = get_alternative_index()
        
        if alt_index is not None:
            if is_today:
                logger.info(f"✅ Alternative.me 获取到最新数据: {alt_index} (日期: {data_date})")
                
                # 获取 CMC 数据（不影响主流程）
                cmc_index, cmc_class, btc_price = get_cmc_index()
                if cmc_index:
                    logger.info(f"✅ CoinMarketCap 指数: {cmc_index}")
                else:
                    logger.warning("⚠️ CoinMarketCap 数据获取失败，继续使用单数据源")
                
                # 发送分析通知
                analyze_and_send(alt_index, alt_class, cmc_index, cmc_class, btc_price)
                return  # 成功，结束脚本
            else:
                logger.info(f"⏳ API 数据仍为旧数据 ({data_date})，等待更新中... (第 {retry_count+1} 次重试)")
        else:
            logger.info(f"⚠️ API 请求失败，等待重试... (第 {retry_count+1} 次重试)")
        
        retry_count += 1
        if retry_count < MAX_RETRIES:
            time.sleep(RETRY_INTERVAL)
    
    # 重试多次仍失败，发送警报
    alert_msg = f"已尝试 {MAX_RETRIES} 次，Alternative.me API 仍未更新今日数据。\n"
    if alt_index is not None:
        alert_msg += f"最后获取到的旧指数为：{alt_index}\n日期：{data_date}\n"
    alert_msg += "请手动检查数据源。"
    
    send_feishu("⚠️ 数据源异常", alert_msg)
    logger.warning("数据源异常警报已发送")


if __name__ == "__main__":
    main()
