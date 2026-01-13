# USDT/USDC 自动化监控（链上 + CEX）

这个仓库包含一个监控脚本 `monitor_usdt_usdc.py`，用于：

- 连接以太坊主网与 Base 链的 RPC Provider
- 读取以太坊主网上 Curve 3pool 的 USDT/USDC 余额与比例

## 环境变量

- `ETH_RPC_URL`: 以太坊主网 HTTP RPC
- `BASE_RPC_URL`: Base 链 HTTP RPC

## 运行

安装依赖：

```bash
pip3 install -r requirements.txt
```

运行：

```bash
ETH_RPC_URL="https://..." BASE_RPC_URL="https://..." python3 monitor_usdt_usdc.py
```

