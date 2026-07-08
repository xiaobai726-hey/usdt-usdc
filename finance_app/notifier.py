import os
import time
import datetime
import schedule
import requests
import pandas as pd
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
    
    report = f"📊 <b>个人财务日报 ({today.strftime('%Y-%m-%d')})</b>\n\n"
    
    # Exchange rate for combined view
    USDT_TO_HKD = 7.8
    
    # Get all transactions for annual calculation
    df_all = db.get_all_transactions()
    
    # Get transactions for current month
    df = df_all[df_all['date'].str.startswith(current_month)] if not df_all.empty else pd.DataFrame()
    
    # HKD Stats
    hkd_df = df[df['currency'] == 'HKD'] if not df.empty else pd.DataFrame()
    hkd_income = hkd_df[hkd_df['type'] == 'income']['amount'].sum() if not hkd_df.empty else 0
    # Exclude Credit Card Repayments from expense tracking so it doesn't double count or blow up the budget
    hkd_expense = hkd_df[(hkd_df['type'] == 'expense') & (hkd_df['category'] != 'Credit Card Repayment')]['amount'].sum() if not hkd_df.empty else 0
    
    # USDT Stats
    usdt_df = df[df['currency'] == 'USDT'] if not df.empty else pd.DataFrame()
    usdt_income = usdt_df[usdt_df['type'] == 'income']['amount'].sum() if not usdt_df.empty else 0
    usdt_expense = usdt_df[(usdt_df['type'] == 'expense') & (usdt_df['category'] != 'Credit Card Repayment')]['amount'].sum() if not usdt_df.empty else 0
    
    # Combined Expenses in HKD
    total_expense_hkd = hkd_expense + (usdt_expense * USDT_TO_HKD)
    
    # Target Budget: 72,000 HKD (50k HKD + 22k HKD from USDT)
    TARGET_BUDGET_HKD = 72000.0
    remaining_budget_hkd = TARGET_BUDGET_HKD - total_expense_hkd
    
    # Calculate days remaining in month
    import calendar
    _, last_day = calendar.monthrange(today.year, today.month)
    days_remaining = last_day - today.day + 1
    
    daily_allowance = remaining_budget_hkd / days_remaining if days_remaining > 0 else 0
    
    # Get today's transactions
    today_str = today.strftime("%Y-%m-%d")
    today_df = df[df['date'] == today_str] if not df.empty else pd.DataFrame()
    today_hkd_expense = today_df[(today_df['currency'] == 'HKD') & (today_df['type'] == 'expense') & (today_df['category'] != 'Credit Card Repayment')]['amount'].sum() if not today_df.empty else 0
    today_usdt_expense = today_df[(today_df['currency'] == 'USDT') & (today_df['type'] == 'expense') & (today_df['category'] != 'Credit Card Repayment')]['amount'].sum() if not today_df.empty else 0
    today_total_expense_hkd = today_hkd_expense + (today_usdt_expense * USDT_TO_HKD)
    
    report += f"🎯 <b>本月总预算追踪 (目标: $72,000.00)</b>\n"
    report += f"已支出总额: ${total_expense_hkd:,.2f}\n"
    report += f"剩余总额度: ${remaining_budget_hkd:,.2f}\n"
    
    if remaining_budget_hkd > 0:
        report += f"💡 建议每日最多可花: <b>${daily_allowance:,.2f}</b>\n"
    else:
        report += f"⚠️ <b>警告: 本月总支出已超预算！超额 ${abs(remaining_budget_hkd):,.2f}</b>\n"
        
    report += f"\n📅 <b>今日动态</b>\n"
    report += f"今日总支出: ${today_total_expense_hkd:,.2f}\n"
    if today_total_expense_hkd > daily_allowance and remaining_budget_hkd > 0:
        report += f"⚠️ 今日支出超过了建议的每日额度！\n"
    elif remaining_budget_hkd > 0:
        report += f"✅ 今日支出控制在合理范围内！\n"
        
    report += f"\n💼 <b>各账户明细</b>\n"
    report += f"<b>HKD 账户:</b>\n"
    report += f"- 支出: ${hkd_expense:,.2f}\n"
    report += f"- 收入: ${hkd_income:,.2f}\n"
    report += f"<b>USDT 账户:</b>\n"
    report += f"- 支出: ₮{usdt_expense:,.2f}\n"
    report += f"- 收入: ₮{usdt_income:,.2f} (包含佣金)\n"
    
    # Calculate savings
    # Total income minus total expenses
    total_income_hkd = hkd_income + (usdt_income * USDT_TO_HKD)
    total_savings_hkd = total_income_hkd - total_expense_hkd
    
    report += f"\n🏦 <b>本月储蓄概况</b>\n"
    report += f"本月净结余 (折合HKD): ${total_savings_hkd:,.2f}\n"
    
    # Calculate Annual Savings Goal
    current_year = today.strftime("%Y")
    year_tx = df_all[df_all['date'].str.startswith(current_year)] if not df_all.empty else pd.DataFrame()
    
    if not year_tx.empty:
        hkd_tx = year_tx[year_tx['currency'] == 'HKD']
        # For savings calculation, we also exclude Credit Card Repayments to avoid double counting
        # since the actual expenses were already recorded when the credit card was swiped.
        hkd_income_yr = hkd_tx[(hkd_tx['type'] == 'income') & (hkd_tx['category'] != 'Credit Card Repayment')]['amount'].sum() if not hkd_tx.empty else 0
        hkd_expense_yr = hkd_tx[(hkd_tx['type'] == 'expense') & (hkd_tx['category'] != 'Credit Card Repayment')]['amount'].sum() if not hkd_tx.empty else 0
        
        usdt_tx = year_tx[year_tx['currency'] == 'USDT']
        usdt_income_yr = usdt_tx[(usdt_tx['type'] == 'income') & (usdt_tx['category'] != 'Credit Card Repayment')]['amount'].sum() if not usdt_tx.empty else 0
        usdt_expense_yr = usdt_tx[(usdt_tx['type'] == 'expense') & (usdt_tx['category'] != 'Credit Card Repayment')]['amount'].sum() if not usdt_tx.empty else 0
        
        total_income_hkd_yr = hkd_income_yr + (usdt_income_yr * USDT_TO_HKD)
        total_expense_hkd_yr = hkd_expense_yr + (usdt_expense_yr * USDT_TO_HKD)
        
        current_savings_yr = total_income_hkd_yr - total_expense_hkd_yr
    else:
        current_savings_yr = 0
        
    GOAL = 1000000.0
    progress = (current_savings_yr / GOAL) * 100
    
    report += f"\n🏆 <b>年度储蓄目标 (100万 HKD)</b>\n"
    report += f"当前已存: ${current_savings_yr:,.2f}\n"
    report += f"目标进度: {progress:.1f}%\n"
    if current_savings_yr < GOAL:
        report += f"距离目标还差: ${(GOAL - current_savings_yr):,.2f}\n"
    else:
        report += f"🎉 恭喜！已达成年度储蓄目标！\n"
    
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
