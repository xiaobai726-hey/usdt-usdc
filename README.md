# USDT/USDC 自动化监控（链上 + CEX）

这个仓库包含一个监控脚本 `monitor_usdt_usdc.py`，用于：

- 连接以太坊主网与 Base 链的 RPC Provider
- 读取以太坊主网上 Curve 3pool 的 USDT/USDC 余额与比例
- 通过 ccxt 获取 Binance/Coinbase 的 USDT/USDC 买一卖一，并对比 Curve 模拟 100 万 USDC 兑换价格，计算 Basis

## 环境变量

- `ETH_RPC_URL`: 以太坊主网 HTTP RPC
- `BASE_RPC_URL`: Base 链 HTTP RPC
- `SLACK_WEBHOOK_URL`（可选）: Slack Incoming Webhook
- `TELEGRAM_BOT_TOKEN`（可选）: Telegram Bot Token
- `TELEGRAM_CHAT_ID`（可选）: Telegram Chat ID

## 运行

安装依赖：

```bash
pip3 install -r requirements.txt
```

单次运行：

```bash
ETH_RPC_URL="https://..." BASE_RPC_URL="https://..." python3 monitor_usdt_usdc.py --once
```

常驻监控（默认每 5 分钟采样一次）：

```bash
ETH_RPC_URL="https://..." BASE_RPC_URL="https://..." SLACK_WEBHOOK_URL="https://..." python3 monitor_usdt_usdc.py
```

发送 Telegram 测试消息（不跑监控逻辑）：

```bash
ETH_RPC_URL="https://..." BASE_RPC_URL="https://..." TELEGRAM_BOT_TOKEN="123:AA..." TELEGRAM_CHAT_ID="1473275053" \
  python3 monitor_usdt_usdc.py --telegram-test
```

