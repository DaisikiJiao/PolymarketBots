# PolymarketBots

基于 15 分钟价格预测市场的汇率检测与下单工具。  
本项目通过采集行情（kline / tick）并对短期价格行为做检测与策略执行，自动完成下单、余额同步、数据保存与告警（邮件）等功能。适用于需要在预测市场上自动化做市、套利或自动下单的场景。

---

## 目录（概要）
- actuator.py        — 执行下单/撮合的执行器/接口（负责把信号转为实际下单动作）
- balancesync.py     — 同步账户余额、持仓信息的脚本/任务
- ctfredeemer.py     — 可能用于某类“赎回/领取”逻辑（CTF 类型或活动）
- datasaver.py       — 行情/指标数据持久化（保存 kline、tick 等）
- loggerfactory.py   — 日志工厂，统一日志配置
- mailsender.py      — 邮件告警/通知发送工具
- polymarkettrader.py— 交易核心脚本（策略、信号逻辑、下单调用）
- webredeemer.py     — 基于 web 的赎回/领取工具
- kline_data/        — 存放历史 kline 数据的目录（仓库内）
- icon/              — 项目图标或资源目录
- run.bat            — Windows 平台的快速运行脚本
- .env               — 配置文件（本仓库中为敏感信息，请勿提交真实凭据）

---

## 主要功能
- 自动采集并保存短周期（15 分钟或更短）价格数据
- 基于短周期的价格变化检测生成交易信号
- 自动下单并提供下单执行（actuator）
- 周期性同步账户余额、持仓信息
- 支持邮件告警/通知（下单成功/失败、异常等）
- 日志化与数据持久化，便于回溯和分析

---

## 环境要求
- Python 3.8+
- 推荐在虚拟环境中运行 (venv / virtualenv / conda)
- 常见依赖（若仓库有 requirements.txt，请优先使用）：
  - requests
  - python-dotenv
  - websocket-client / websockets（若使用 WebSocket）
  - pandas（可选，datasaver/策略分析可能会用到）
  - 其它依赖请根据脚本导入检查并安装

示例：
```bash
python -m venv venv
source venv/bin/activate    # Linux / macOS
venv\Scripts\activate       # Windows
pip install -r requirements.txt   # 如果存在 requirements.txt
# 或手动安装常见包
pip install requests python-dotenv pandas
```

---

## 配置 (.env 模板)
项目使用 `.env` 文件存放运行时配置与敏感凭据。请在运行前创建仓库根目录下的 `.env`（注意：不要把真实凭据提交到仓库）。

示例 `.env`（模板，变量名仅作参考，请根据脚本实际读取的环境变量名进行调整）：
```env
# API / 授权
POLYMARKET_API_URL=https://api.polymarket.com
POLYMARKET_API_KEY=your_api_key_here
POLYMARKET_API_SECRET=your_api_secret_here

# 交易参数
TRADE_MARKET_ID=market-xxxxx
TRADE_AMOUNT=0.001
TRADE_SIDE=buy   # buy / sell
MAX_POSITION=10

# 数据与日志
DATA_DIR=./kline_data
LOG_LEVEL=INFO

# 邮件告警（mailsender.py）
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=notify@example.com
SMTP_PASS=your_email_password
ALERT_RECIPIENT=you@example.com

# 其它（根据脚本需要补充）
DB_PATH=./polymarket.db
```

注意：实际脚本可能使用不同的环境变量名称，请打开具体脚本（如 `polymarkettrader.py`、`mailsender.py`、`datasaver.py` 等）查看 `os.getenv(...)` 或 dotenv 加载的键名，并按脚本要求填充 `.env`。

---

## 快速开始（运行示例）
1. 克隆仓库并进入目录：
```bash
git clone https://github.com/DaisikiJiao/PolymarketBots.git
cd PolymarketBots
```

2. 创建并编辑 `.env`（参照上方模板）

3. 安装依赖（若仓库未提供 requirements.txt，请根据脚本导入自行安装）：
```bash
pip install -r requirements.txt    # 如果有文件
# 或
pip install requests python-dotenv pandas
```

4. 运行主脚本（示例）：
```bash
python actuator.py
```

5.Windows 快速运行（支持代理 需要配置.env中的LOCAL_HTTPS_PROXY）：
- 双击或在命令行运行 run.bat

---

## 脚本说明（简要）
- polymarkettrader.py
  - 交易逻辑入口。包含信号判断、风控参数、调用 actuator 执行下单的流程。
- actuator.py
  - 对接下单接口的执行器。把交易信号转化为 API 下单请求（包含重试、错误处理等）。
- datasaver.py
  - 负责采集市场数据并持久化到本地（kline_data/ 或数据库），供策略与回测使用。
- balancesync.py
  - 定时从交易平台获取并更新账户余额 / 持仓信息，可能会保存到数据库或本地文件。
- mailsender.py
  - 发送告警/通知邮件，供策略异常或下单结果通知使用。
- loggerfactory.py
  - 提供统一的日志配置与工厂函数，供各脚本引用以输出文件与控制台日志。
- ctfredeemer.py / webredeemer.py
  - 与“赎回 / 领取”相关的辅助工具脚本（依据活动或平台功能实现）。

---

## 运行建议与部署
- 在真实资金下运行前务必在测试账户或沙盒环境中充分测试。
- 启用日志并记录每次下单的返回值与请求参数，便于排查问题与回溯。
- 建议使用 supervisor / systemd / Docker 或云函数定时器来保证长期稳定运行，并可配合 cron 或任务调度器进行数据采集与余额同步。
- 对关键操作（如下单）设置幂等与重试策略，避免重复下单或网络异常导致的问题。
- 定期备份 kline 数据与数据库文件，以免丢失历史数据。

示例（在 Linux 使用 systemd 或 crontab）：
- crontab（每 15 分钟运行一次数据采集）：
```cron
*/15 * * * * cd /path/to/PolymarketBots && /path/to/venv/bin/python datasaver.py >> logs/datasaver.log 2>&1
```

---

## 安全与注意事项
- 切勿在公开仓库提交真实 API Key / Secret / 邮箱密码等敏感信息。
- 使用 .gitignore 忽略 `.env`、数据库、日志等私密文件。
- 严格测试策略行为并设定风控限制（止损/最大持仓/单次下单上限等）。
- 对第三方库与 API 响应做好异常处理，避免因接口变更或网络问题导致异常行为。

---

## 贡献
欢迎提出 issue 或 PR：
- 若你修复 bug、添加测试、改进日志或添加 README 中遗漏的配置项，欢迎提交 PR。
- 请在 PR 中说明测试步骤与复现方法。

---

## 许可证
本项目采用 MIT 许可证。详见 LICENSE 文件。

---

## 联系方式
如需联系：在 GitHub 仓库中创建 Issue 或直接联系仓库所有者 [DaisikiJiao](https://github.com/DaisikiJiao)。

---
