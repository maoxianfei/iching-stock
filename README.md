# K线卦象分析系统

A股/港股/美股 K线 → 易经六十四卦 映射分析系统。

包含三大子系统：
- **iching_analyzer**：单股深度分析（HTML交互报告）
- **hexagram_screener**：全市场卦象批量筛选（CSV导出）
- **backtest**：策略回测系统（MA粘合 + 易经K线形态 + 胜率统计）

---

## 功能特性

- **单股分析**：Chart.js 烛台图 + 卦象标注 + 悬停解读 + 点击6周期卦象面板
- **全市场筛选**：MA60周线预过滤 → 卦象序列扫描 → 时间过滤 → 信号分层导出
- **多市场支持**：A股（mootdx）、港股（Yahoo/腾讯）、美股（Yahoo/新浪）
- **多周期支持**：日线/周线/月线三维度
- **64卦完整数据库**：含卦名、卦义、行情解读、看涨程度评级（1~5星）
- **零部署依赖**：HTML报告自包含，CDN加载前端资源，双击即可查看

---

## 项目架构

```
iching-stock/
├── main.py                      # 统一CLI入口（路由到子系统）
├── backtest/                    # ★ 回测系统（新增）
│   ├── __init__.py
│   ├── runner.py               # CLI入口（screen/backtest/batch）
│   ├── strategy_base.py        # 策略基类 + FilterResult/ScreenResult
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── ma_convergence.py   # MA粘合策略
│   │   └── yijing.py           # 易经K线形态策略
│   ├── engine.py               # 两阶段筛选引擎（ThreadPoolExecutor）
│   ├── backtester.py          # 通用回测核心（胜率/收益统计）
│   ├── output.py               # 控制台打印 + Excel导出
│   └── scheduler.py            # 定时调度（交易日14:30触发）
│
├── core/                        # 核心共享模块（跨子系统复用）
│   ├── models.py                # KLine 数据模型 + 市场识别
│   ├── hexagram_db.py           # 64卦数据库 + 看涨等级 + 查询API
│   ├── hexagram_mapper.py       # K线→爻位映射 + 滑动窗口 + 序列检测
│   ├── data_fetcher.py          # 统一数据拉取层（A股+港股+美股）
│   ├── indicators.py            # ★ 技术指标库（MA/偏离度/粘合/涨停/爆量）
│   └── config.py                # ★ 全局配置（并发/输出/调度参数）
│
├── iching_analyzer/             # 易经个股模块（单股深度分析 + HTML报告）
│   ├── main.py                  # 子系统入口
│   ├── gua_calculator.py        # GuaResult/GuaAnalysis + 滑动窗口卦象分析
│   └── report_generator.py      # HTML报告生成（Chart.js K线图 + 卦象标注）
│
├── hexagram_screener/           # 卦象扫描模块（全市场筛选 + CSV导出）
│   ├── main.py                  # 子系统入口
│   └── screener.py              # MA60过滤 + 卦象扫描 + 时间过滤 + 信号分层 + 导出
│
├── output/                      # 分析报告/导出输出（gitignore）
└── README.md
```

### 模块归属原则

- **`core/`** — 纯数据/工具层，不绑定任何业务逻辑，可被所有子系统调用
  - `models.py`：KLine 数据模型（统一 volume 为 float）
  - `hexagram_db.py`：Hexagram dataclass + 64卦完整数据 + 看涨等级
  - `hexagram_mapper.py`：K线→卦象核心算法（滑动窗口、序列检测）
  - `data_fetcher.py`：统一数据拉取（A股mootdx、港股Yahoo/腾讯、美股Yahoo/新浪）

- **`iching_analyzer/`** — 易经个股模块（独有）
  - `gua_calculator.py`：GuaResult/GuaAnalysis 滑动窗口分析模型
  - `report_generator.py`：自包含 HTML 交互报告

- **`hexagram_screener/`** — 卦象扫描模块（独有）
  - `screener.py`：MA60预筛选 + 卦象序列扫描 + 信号分层 + CSV导出

---

## 快速开始

### 安装

```bash
pip install mootdx requests
```

### 单股分析（iching_analyzer 子系统）

```bash
# A股 — 月线分析（默认24周期）
python main.py analyze 600519

# A股 — 周线分析，指定周期数
python main.py analyze 600519 -i weekly -n 30

# 港股 — 周线分析
python main.py analyze 09626 -i weekly -n 50

# 美股 — 月线分析
python main.py analyze AAPL -i monthly -n 24

# 指定输出路径
python main.py analyze 600519 -o output/maotai.html
```

**参数说明：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `symbol` | 股票代码（A股6位 / 美股字母 / 港股5位） | 必填 |
| `-i, --interval` | 周期：`weekly` / `monthly` | `monthly` |
| `-n, --count` | K线数量 | `24` |
| `-o, --output` | 输出路径 | `output/<symbol>_<interval>_<timestamp>.html` |

### 全市场筛选（hexagram_screener 子系统）

```bash
# 全市场扫描（MA60预筛选 + 卦象扫描 + 最近365天信号过滤）
python main.py screen

# 全市场扫描 + 导出CSV（同花顺可导入）
python main.py screen --export

# 全市场扫描，90天窗口 + 导出
python main.py screen --days 90 --export

# 单股三维度扫描
python main.py screen --single 600021
```

**筛选参数：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--single` | 单股扫描模式，指定股票代码 | 全市场 |
| `--market` | 市场（`a`=A股, `hk`=港股, `us`=美股） | `a` |
| `--days` | 时间过滤窗口（天） | `365` |
| `--export` | 导出数据文件（CSV+代码列表） | 不导出 |
| `--output-dir` | 导出目录 | `output/` |

**导出文件说明：**

| 文件 | 内容 | 用途 |
|------|------|------|
| `resonance_codes.txt` | 共振股票代码（每行一个） | 导入同花顺自选股 |
| `resonance_detail.csv` | 共振股详情（代码/名称/各维度信号数/区间/价格） | Excel对照分析 |
| `all_signals.csv` | 全部信号（按维度分块，结束时间倒序） | 完整数据备用 |

---

## 数据流

### 单股分析（iching_analyzer）

```
股票代码 + 周期
    │
    ▼
core/data_fetcher.py  ← mootdx (A股) / Yahoo (港股/美股)
    │               获取周线或月线K线数据
    ▼
iching_analyzer/gua_calculator.py  ← 6根K线滑动窗口 → 阴阳爻映射
    │
    ▼
core/hexagram_db.py  ← 64卦数据库：爻位 → 卦名/释义/看涨等级
    │
    ▼
iching_analyzer/report_generator.py  ← 生成自包含HTML报告
```

### 全市场筛选（hexagram_screener）

```
全市场A股 5200+只
    │
    ▼
hexagram_screener/screener.py 第1步: MA60周线过滤
    │  收盘价 > MA60周线 → 保留约52%
    ▼
hexagram_screener/screener.py 第2步: 卦象序列扫描
    │  日线/周线/月线三维度，检测火地晋→水雷屯等序列
    ▼
hexagram_screener/screener.py 第3步: 时间过滤
    │  只保留最近N天内触发的信号
    ▼
信号分层:
  日线+周线/月线共振 → 优质买点（优先关注）
  仅日线 → 短期噪音
  仅周线/月线 → 等待日线买点
    │
    ▼
export_to_file → CSV + 代码列表（可导入同花顺）
```

---

## 卦象映射规则

- **K线 → 爻位**：阳线（收盘 ≥ 开盘）→ 阳爻，阴线（收盘 < 开盘）→ 阴爻
- **滑动窗口**：6 根 K 线 = 1 个卦象，滑动步长 1
- **方向**：最旧 K 线 → 上爻，最新 K 线 → 初爻
- **数据库**：64 卦，每卦含看涨程度评级（1~5星）

---

## 信号分层逻辑

| 分层 | 含义 | 操作建议 |
|------|------|----------|
| 日线+周线/月线共振 | 有买点 + 有支撑 | 优先关注，值得深入研究 |
| 日线+周线+月线三重 | 最强信号 | 重点关注，趋势确认度最高 |
| 仅日线 | 短期噪音 | 不追，等待周/月线支撑确认 |
| 仅周线/月线 | 有支撑但无买点 | 放入观察池，等日线信号触发 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 数据获取 | mootdx (A股)、Yahoo Finance API (港股/美股)、腾讯/新浪（回退） |
| 核心逻辑 | Python 3.8+，dataclass 数据结构 |
| 前端报告 | Chart.js 4.x + chartjs-chart-financial + chartjs-plugin-annotation |
| 部署 | 自包含 HTML，零服务器依赖 |

---

## 已知限制

- A股数据依赖 mootdx 服务器，网络不可达时会自动回退到腾讯K线API
- 美股/港股依赖 Yahoo Finance API，可能受地域限制
- 卦象信号仅供参考，不构成投资建议
- 回测系统依赖 akshare 获取股票列表和东方财富实时行情（可选）

---

## 回测系统（backtest/）

基于 a_stock_screener 移植的策略回测框架，支持：
- **两阶段筛选**：pre_filter 粗筛（快）+ analyze 精筛（慢，并发）
- **策略框架**：`BaseStrategy` 基类，可插拔新策略
- **回测引擎**：指定筛选日 + 验证日，统计胜率/平均收益/最大盈亏
- **批量回测**：多日期区间自动回测

### 安装额外依赖

```bash
pip install akshare openpyxl tqdm
```

### 策略列表

| 策略名 | 说明 |
|--------|------|
| `ma_convergence` | MA粘合：跌幅区间 + MA10偏离 + 均线粘合 + MA趋势 + 涨停/爆量信号 |
| `yijing` | 易经选股：K线阴阳形态序列匹配（支持严格/模糊/滑动窗口） |

### 实时筛选

```bash
# MA粘合策略筛选
python backtest/runner.py screen --strategy ma_convergence

# 易经策略筛选（自定义形态）
python backtest/runner.py screen --strategy yijing --pattern 阳阴阳阴阴阴阳

# 导出Excel
python backtest/runner.py screen --strategy ma_convergence --export
```

### 单次回测

```bash
# 在 2026-05-14 筛选，2026-05-15 验证收益
python backtest/runner.py backtest \
  --strategy ma_convergence \
  --screen-date 20260514 \
  --verify-date 20260515

# 易经策略回测（只抽样100只快速验证）
python backtest/runner.py backtest \
  --strategy yijing \
  --screen-date 20260514 \
  --pattern 阳阴阳阴阴阴阳 \
  --sample 100
```

### 批量回测

```bash
# 2026年5月全月，每1个交易日验证
python backtest/runner.py batch \
  --strategy ma_convergence \
  --start 20260501 \
  --end 20260531 \
  --offset 1
```

### 定时调度

```python
# 在 Python 中调用
from backtest.scheduler import run_scheduled
run_scheduled(strategy_name="ma_convergence")  # 每个交易日 14:30 触发
```

---

## License

MIT
