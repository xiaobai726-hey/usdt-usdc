import os
import time
import datetime
import schedule
import requests
from dotenv import load_dotenv
import database as db

def send_telegram_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"[{datetime.datetime.now()}] Message sent successfully.")
    except Exception as e:
        print(f"[{datetime.datetime.now()}] Failed to send message: {e}")

def generate_daily_report():
    today = datetime.date.today()
    current_month = today.strftime("%Y-%m")
    
    # Get budget
    budget = db.get_budget(current_month)
    
    # Get transactions for current month
    df = db.get_transactions_by_month(current_month)
    
    income = df[df['type'] == 'income']['amount'].sum() if not df.empty else 0
    expense = df[df['type'] == 'expense']['amount'].sum() if not df.empty else 0
    
    remaining_budget = budget['expense_budget'] - expense
    
    # Calculate days remaining in month
    import calendar
    _, last_day = calendar.monthrange(today.year, today.month)
    days_remaining = last_day - today.day + 1
    
    daily_allowance = remaining_budget / days_remaining if days_remaining > 0 else 0
    
    # Get today's transactions
    today_str = today.strftime("%Y-%m-%d")
    today_df = df[df['date'] == today_str]
    today_expense = today_df[today_df['type'] == 'expense']['amount'].sum() if not today_df.empty else 0
    
    report = f"📊 <b>个人财务日报 ({today_str})</b>\n\n"
    report += f"💰 <b>本月概况</b>\n"
    report += f"总收入: ¥{income:,.2f} (预算: ¥{budget['income_budget']:,.2f})\n"
    report += f"总支出: ¥{expense:,.2f} (预算: ¥{budget['expense_budget']:,.2f})\n\n"
    
    report += f"🎯 <b>预算追踪</b>\n"
    report += f"剩余支出额度: ¥{remaining_budget:,.2f}\n"
    report += f"本月剩余天数: {days_remaining}天\n"
    
    if remaining_budget > 0:
        report += f"💡 建议每日最多可花: <b>¥{daily_allowance:,.2f}</b>\n\n"
    else:
        report += f"⚠️ <b>警告: 本月支出已超预算！超额 ¥{abs(remaining_budget):,.2f}</b>\n\n"
        
    report += f"📅 <b>今日动态</b>\n"
    report += f"今日支出: ¥{today_expense:,.2f}\n"
    if today_expense > daily_allowance and remaining_budget > 0:
        report += f"⚠️ 今日支出超过了建议的每日额度！"
    elif remaining_budget > 0:
        report += f"✅ 今日支出控制在合理范围内，继续保持！"
        
    return report

def job():
    # Reload env vars in case they were updated via UI
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path, override=True)
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print(f"[{datetime.datetime.now()}] Telegram credentials not configured. Skipping.")
        return
        
    report = generate_daily_report()
    send_telegram_message(token, chat_id, report)

def run_scheduler():
    print("Starting Telegram Notifier Service...")
    # Run once on startup for testing
    job()
    
    # Schedule to run every day at 20:00 (8 PM)
    schedule.every().day.at("20:00").do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    run_scheduler()
