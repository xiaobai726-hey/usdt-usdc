# 个人财务管理系统 (Personal Finance System)

这是一个基于 Python 和 Streamlit 构建的个人财务管理系统，帮助您记录、分析每月的收入与开销，并提供 Telegram 每日预算提醒。

## 功能特点
1. **仪表盘 (Dashboard)**: 直观展示本月总收入、总支出、剩余预算以及收支趋势图表。
2. **交易记录 (Transactions)**: 查看、筛选和搜索所有历史交易记录。
3. **上传账单 (Upload)**: 支持上传银行、支付宝、微信等导出的 CSV 流水文件，自定义列映射，自动解析并导入数据库。
4. **预算设置 (Settings)**: 设定每月的收入预期和支出预算。
5. **Telegram 推送**: 每天定时（默认晚上8点）向您的 Telegram 发送财务日报，包含当月剩余预算和每日建议支出额度，防止超支。

## 安装与运行

1. 确保已安装 Python 3.8+。
2. 进入项目目录并激活虚拟环境：
   ```bash
   cd finance_app
   source venv/bin/activate
   ```
3. 运行系统：
   ```bash
   ./run.sh
   ```
   这将在后台启动 Telegram 推送服务，并在前台启动 Streamlit Web 界面。
4. 在浏览器中访问 `http://localhost:8501`。

## Telegram Bot 配置指南
1. 在 Telegram 中搜索 `@BotFather`。
2. 发送 `/newbot` 创建一个新的 Bot，并获取 **Bot Token**。
3. 在 Telegram 中搜索 `@userinfobot` 或向您的新 Bot 发送一条消息，然后访问 `https://api.telegram.org/bot<YourBOTToken>/getUpdates` 获取您的 **Chat ID**。
4. 在系统的“设置 (Settings)”页面中填入 Bot Token 和 Chat ID 并保存。

## 账单上传指南
1. 从银行或支付软件导出 CSV 格式的流水记录。
2. 在“上传账单”页面选择该 CSV 文件。
3. 根据 CSV 的表头，选择对应的“日期列”、“金额列”和“描述列”。
4. 选择收支判断方式（例如：正数代表收入，负数代表支出）。
5. 点击“处理并导入”。
