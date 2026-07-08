import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import database as db
import parser
import os
from dotenv import load_dotenv, set_key

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

st.set_page_config(page_title="Personal Finance System", layout="wide")

# Initialize DB
db.init_db()

def main():
    st.sidebar.title("💰 财务管理系统")
    menu = ["仪表盘 (Dashboard)", "交易记录 (Transactions)", "上传账单 (Upload)", "设置 (Settings)"]
    choice = st.sidebar.radio("导航", menu)

    if choice == "仪表盘 (Dashboard)":
        show_dashboard()
    elif choice == "交易记录 (Transactions)":
        show_transactions()
    elif choice == "上传账单 (Upload)":
        show_upload()
    elif choice == "设置 (Settings)":
        show_settings()

def show_dashboard():
    st.title("仪表盘")
    
    # Select month
    today = datetime.date.today()
    current_month = today.strftime("%Y-%m")
    
    # Get all transactions to find available months
    all_tx = db.get_all_transactions()
    if not all_tx.empty:
        all_tx['month'] = pd.to_datetime(all_tx['date']).dt.strftime('%Y-%m')
        months = sorted(all_tx['month'].unique().tolist(), reverse=True)
        if current_month not in months:
            months.insert(0, current_month)
    else:
        months = [current_month]
        
    selected_month = st.selectbox("选择月份", months, index=months.index(current_month) if current_month in months else 0)
    
    currency = st.radio("选择币种", ["HKD", "USDT"], horizontal=True)
    
    # Fetch data
    budget = db.get_budget(selected_month, currency)
    df = db.get_transactions_by_month(selected_month)
    
    # Filter by currency
    if not df.empty:
        df = df[df['currency'] == currency]
    
    income = df[df['type'] == 'income']['amount'].sum() if not df.empty else 0
    expense = df[df['type'] == 'expense']['amount'].sum() if not df.empty else 0
    
    remaining_budget = budget['expense_budget'] - expense
    
    # Display metrics
    col1, col2, col3, col4 = st.columns(4)
    prefix = "$" if currency == "HKD" else "₮"
    col1.metric("本月总收入", f"{prefix}{income:,.2f}", f"预算: {prefix}{budget['income_budget']:,.2f}")
    col2.metric("本月总支出", f"{prefix}{expense:,.2f}", f"预算: {prefix}{budget['expense_budget']:,.2f}")
    col3.metric("剩余支出预算", f"{prefix}{remaining_budget:,.2f}")
    col4.metric("净收益", f"{prefix}{(income - expense):,.2f}")
    
    st.divider()
    
    if not df.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("支出分类占比")
            expense_df = df[df['type'] == 'expense']
            if not expense_df.empty:
                fig = px.pie(expense_df, values='amount', names='category', hole=0.4)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("本月暂无支出记录")
                
        with col2:
            st.subheader("每日收支趋势")
            daily_df = df.groupby(['date', 'type'])['amount'].sum().reset_index()
            fig = px.bar(daily_df, x='date', y='amount', color='type', barmode='group',
                         color_discrete_map={'income': 'green', 'expense': 'red'})
            st.plotly_chart(fig, use_container_width=True)
            
        st.subheader("最近交易记录")
        st.dataframe(df.sort_values('date', ascending=False).head(10), use_container_width=True)
    else:
        st.info("本月暂无交易记录。")

def show_transactions():
    st.title("交易记录")
    
    df = db.get_all_transactions()
    if df.empty:
        st.info("暂无交易记录。请在“上传账单”页面导入数据。")
        return
        
    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        type_filter = st.selectbox("类型", ["全部", "收入 (income)", "支出 (expense)"])
    with col2:
        categories = ["全部"] + sorted(df['category'].unique().tolist())
        cat_filter = st.selectbox("分类", categories)
    with col3:
        search = st.text_input("搜索描述")
        
    # Apply filters
    filtered_df = df.copy()
    if type_filter != "全部":
        t_type = "income" if "收入" in type_filter else "expense"
        filtered_df = filtered_df[filtered_df['type'] == t_type]
    if cat_filter != "全部":
        filtered_df = filtered_df[filtered_df['category'] == cat_filter]
    if search:
        filtered_df = filtered_df[filtered_df['description'].str.contains(search, case=False, na=False)]
        
    st.dataframe(filtered_df.sort_values('date', ascending=False), use_container_width=True)

def show_upload():
    st.title("上传账单")
    
    st.write("支持上传 CSV, PDF, 或图片 (PNG/JPG) 格式的账单。")
    uploaded_file = st.file_uploader("选择账单文件", type=['csv', 'pdf', 'png', 'jpg', 'jpeg'])
    
    if uploaded_file is not None:
        file_ext = uploaded_file.name.split('.')[-1].lower()
        
        currency = st.selectbox("账单币种", ["HKD", "USDT"])
        source = st.text_input("账单来源 (如: 招商银行, 支付宝, Binance)", "Bank")
        
        if file_ext == 'csv':
            df = pd.read_csv(uploaded_file)
            st.write("数据预览:")
            st.dataframe(df.head())
            
            st.subheader("列映射设置")
            columns = df.columns.tolist()
            
            col1, col2 = st.columns(2)
            with col1:
                date_col = st.selectbox("日期列", columns)
                amount_col = st.selectbox("金额列", columns)
                desc_col = st.selectbox("描述列", columns)
                
            with col2:
                st.write("收支判断方式")
                type_mode = st.radio("模式", ["金额正负判断", "指定收支类型列"])
                
                type_col, income_val, expense_val = None, None, None
                invert_amount = False
                
                if type_mode == "金额正负判断":
                    invert_amount = st.checkbox("负数代表收入 (默认正数为收入)")
                else:
                    type_col = st.selectbox("类型列", columns)
                    income_val = st.text_input("收入对应的值 (如: 收入)")
                    expense_val = st.text_input("支出对应的值 (如: 支出)")
                    
            if st.button("处理并导入"):
                with st.spinner("处理中..."):
                    processed_df, error = parser.process_csv_statement(
                        df, date_col, amount_col, desc_col, 
                        type_col, income_val, expense_val, 
                        invert_amount=invert_amount
                    )
                    
                    if error:
                        st.error(f"处理失败: {error}")
                    else:
                        st.success(f"成功解析 {len(processed_df)} 条记录！")
                        st.dataframe(processed_df.head())
                        
                        # Insert into DB
                        success_count = 0
                        for _, row in processed_df.iterrows():
                            db.add_transaction(
                                row['date'], row['amount'], currency, row['category'], 
                                row['type'], row['description'], source
                            )
                            success_count += 1
                        st.success(f"成功将 {success_count} 条记录导入数据库！")
        
        elif file_ext in ['pdf', 'png', 'jpg', 'jpeg']:
            st.info("正在使用 OCR/文本提取解析文件，这可能需要一些时间...")
            
            file_bytes = uploaded_file.read()
            if file_ext == 'pdf':
                raw_text = parser.extract_text_from_pdf(file_bytes)
            else:
                raw_text = parser.extract_text_from_image(file_bytes)
                
            with st.expander("查看提取的原始文本"):
                st.text(raw_text)
                
            if st.button("尝试自动解析并导入"):
                with st.spinner("解析中..."):
                    processed_df, error = parser.parse_raw_text_to_df(raw_text)
                    
                    if error:
                        st.error(error)
                        st.warning("自动解析失败。请检查原始文本格式，或手动将数据整理为 CSV 格式上传。")
                    else:
                        st.success(f"成功解析 {len(processed_df)} 条记录！")
                        
                        # Allow user to edit the parsed dataframe before inserting
                        edited_df = st.data_editor(processed_df, num_rows="dynamic")
                        
                        if st.button("确认导入数据库"):
                            success_count = 0
                            for _, row in edited_df.iterrows():
                                db.add_transaction(
                                    row['date'], row['amount'], currency, row['category'], 
                                    row['type'], row['description'], source
                                )
                                success_count += 1
                            st.success(f"成功将 {success_count} 条记录导入数据库！")

def show_settings():
    st.title("设置")
    
    st.header("1. 预算设置")
    today = datetime.date.today()
    current_month = today.strftime("%Y-%m")
    
    col_m, col_c = st.columns(2)
    with col_m:
        month_input = st.text_input("月份 (YYYY-MM)", current_month)
    with col_c:
        currency_input = st.selectbox("币种", ["HKD", "USDT"])
    
    current_budget = db.get_budget(month_input, currency_input)
    
    col1, col2 = st.columns(2)
    prefix = "$" if currency_input == "HKD" else "₮"
    with col1:
        income_budget = st.number_input(f"预期收入 ({prefix})", min_value=0.0, value=float(current_budget['income_budget']), step=100.0)
    with col2:
        expense_budget = st.number_input(f"支出预算 ({prefix})", min_value=0.0, value=float(current_budget['expense_budget']), step=100.0)
        
    if st.button("保存预算"):
        db.set_budget(month_input, currency_input, income_budget, expense_budget)
        st.success(f"已保存 {month_input} 的 {currency_input} 预算设置！")
        
    st.divider()
    
    st.header("2. Telegram 推送设置")
    st.write("用于每天定时推送账单及预算剩余情况。")
    
    bot_token = st.text_input("Bot Token", os.getenv("TELEGRAM_BOT_TOKEN", ""), type="password")
    chat_id = st.text_input("Chat ID", os.getenv("TELEGRAM_CHAT_ID", ""))
    
    if st.button("保存 Telegram 设置"):
        if not os.path.exists(dotenv_path):
            open(dotenv_path, 'a').close()
        set_key(dotenv_path, "TELEGRAM_BOT_TOKEN", bot_token)
        set_key(dotenv_path, "TELEGRAM_CHAT_ID", chat_id)
        st.success("Telegram 设置已保存！")

if __name__ == "__main__":
    main()
