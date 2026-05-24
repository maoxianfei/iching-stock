# iching-stock — 大股票分析系统

A股/港股/美股 全品类量化分析平台。融合**易经六十四卦 K线映射**与**多策略回测框架**，
覆盖单股深度分析、全市场批量化筛选、策略回测验证三大场景。

---

## 系统概览

```
┌─────────────────────────────────────────────────────────────┐
│                    iching-stock 大股票系统                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐  ┌────────────────┐  ┌──────────────┐ │
│  │ iching_analyzer │  │hexagram_screener│  │   backtest   │ │
│  │   单股深度分析   │  │  全市场卦象筛选  │  │  策略回测系统 │ │
│  │                  │  │                │  │              │ │
│  │ K线 → 64卦映射  │  │ MA60 → 卦象扫描│  │ 策略框架     │ │
│  │ HTML 交互报告   │  │ → 时间过滤     │  │ 两阶段筛选   │ │
│  │ Chart.js 烛台图  │  │ → CSV 信号导出 │  │ 收益/胜率统计│ │
│  └────────┬────────┘  └───────┬────────┘  └──────┬───────┘ │
│           │                   │                   │         │
│           └───────────────────┼───────────────────┘         │
│                               │                             │
│                    ┌──────────┴──────────┐                  │
│                    │       core/         │                  │
│                    │  共享核心层（6模块）  │                  │
│                    │                     │                  │
│                    │ models · hexagram_db│                  │
│                    │ hexagram_mapper     │                  │
│                    │ data_fetcher        │                  │
│                    │ indicators · config │                  │
│                    └─────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 子系统简介

| 子系统 | 用途 | 输入 | 输出 | 入口 |
|--------|------|------|------|------|
| **iching_analyzer** | 单股卦象深度分析 | 1只股票 + 周期 | HTML交互报告（K线图+卦象标注） | `main.py analyze` |
| **hexagram_screener** | 全市场卦象批量筛选 | 全市场5200+只 | CSV信号导出 + 代码列表 | `main.py screen` |
| **backtest** | 策略筛选与回测 | 策略参数 + 日期区间 | Excel报表 + 胜率/收益统计 | `backtest/runner.py` |

---

## 项目架构

```
iching-stock/
│
├── main.py                         # 统一 CLI 入口（路由到子系统）
│
├── core/                           # 共享核心层（所有子系统复用）
│   ├── models.py                   #   KLine 数据模型 + 市场识别 + 股票名称查询
│   ├── hexagram_db.py             #   64卦完整数据库 + 看涨评级(1-5星) + 查询API
│   ├── hexagram_mapper.py         #   K线→爻位映射 + 滑动窗口算法 + 序列检测
│   ├── data_fetcher.py            #   统一数据获取（A股mootdx/港股Yahoo/美股Yahoo）
│   ├── indicators.py              #   技术指标库（MA/偏离度/粘合/涨停/爆量/形态匹配）
│   └── config.py                  #   全局配置（并发/输出/调度参数）
│
├── iching_analyzer/                # 子系统1：单股深度分析
│   ├── main.py                     #   子系统 CLI 入口
│   ├── gua_calculator.py          #   GuaResult/GuaAnalysis 滑动窗口卦象分析模型
│   └── report_generator.py        #   自包含 HTML 交互报告（Chart.js 烛台图+卦象标注）
│
├── hexagram_screener/              # 子系统2：全市场卦象筛选
│   ├── main.py                     #   子系统 CLI 入口
│   └── screener.py                #   MA60过滤 + 卦象扫描 + 时间过滤 + 信号分层 + CSV导出
│
├── backtest/                       # 子系统3：策略回测
│   ├── runner.py                   #   子系统 CLI 入口（screen/backtest/batch/strategy-list）
│   ├── strategy_base.py           #   BaseStrategy 策略基类 + FilterResult/ScreenResult
│   ├── strategies/
│   │   ├── ma_convergence.py      #   MA粘合策略（5条件 AND 精筛）
│   │   └── yijing.py              #   易经K线形态匹配策略
│   ├── engine.py                   #   两阶段筛选引擎（ThreadPoolExecutor 20线程并发）
│   ├── backtester.py              #   回测引擎（筛选日→验证日胜率/收益统计）
│   ├── output.py                   #   控制台表格打印 + Excel 导出
│   └── scheduler.py               #   定时调度器（交易日 14:30 自动触发）
│
├── webui/                          # Web Dashboard（统一前端）
│   ├── app.py                       #   Flask 主应用（SSE 路由 + 子进程管理）
│   └── templates/
│       └── index.html               #   单页三 Tab Dashboard（原生 HTML/CSS/JS）
│
├── output/                         # 分析报告 & 导出文件（gitignore）
├── .gitignore
└── README.md
```

---

## 模块归属原则

- **`core/`** — 纯数据/工具层，不绑定任何业务逻辑，可被所有子系统调用
- **`iching_analyzer/`** — 单股维度：卦象计算 + HTML 可视化
- **`hexagram_screener/`** — 全市场维度：批量筛选 + 信号分层
- **`backtest/`** — 时间序列维度：策略验证 + 回测统计

---

## 快速开始

### 基础依赖（所有子系统通用）

```bash
pip install mootdx requests
```

### 子系统1：单股卦象分析

```bash
# A股月线分析
python main.py analyze 600519

# A股周线分析，指定周期数
python main.py analyze 600519 -i weekly -n 30

# 港股/美股分析
python main.py analyze 09626 -i weekly    # 港股 Bilibili
python main.py analyze AAPL -i monthly    # 美股 Apple

# 指定输出路径
python main.py analyze 600519 -o output/maotai.html
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `symbol` | 股票代码 | 必填 |
| `-i, --interval` | 周期：`weekly` / `monthly` | `monthly` |
| `-n, --count` | K线数量 | `24` |
| `-o, --output` | 输出路径 | `output/<symbol>_<timestamp>.html` |

### 子系统2：全市场卦象筛选

```bash
# 全市场扫描（MA60预筛选 + 卦象扫描 + 365天信号过滤）
python main.py screen

# 导出 CSV（可导入同花顺）
python main.py screen --export

# 90天窗口 + 导出
python main.py screen --days 90 --export

# 单股三维度扫描
python main.py screen --single 600021
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--single` | 单股扫描模式 | 全市场 |
| `--market` | 市场：`a`/`hk`/`us` | `a` |
| `--days` | 时间过滤窗口（天） | `365` |
| `--export` | 导出数据文件 | 否 |
| `--output-dir` | 导出目录 | `output/` |

**导出文件说明：**

| 文件 | 内容 | 用途 |
|------|------|------|
| `resonance_codes.txt` | 共振股票代码列表 | 导入同花顺自选股 |
| `resonance_detail.csv` | 共振股详情（代码/名称/信号数/区间/价格） | Excel 对照分析 |
| `all_signals.csv` | 全部信号（按维度分块，时间倒序） | 完整数据备用 |

### 子系统3：策略回测

依赖：
```bash
pip install akshare openpyxl tqdm
```

**策略列表：**

| 策略名 | 说明 |
|--------|------|
| `ma_convergence` | MA粘合：跌幅区间 + MA10偏离 + 均线粘合 + MA趋势 + 涨停/爆量信号 |
| `yijing` | 易经选股：K线阴阳形态序列匹配（支持严格/模糊/滑动窗口） |

```bash
# 实时筛选
python backtest/runner.py screen --strategy ma_convergence --export

# 单次回测（筛选日筛选 → 验证日验证）
python backtest/runner.py backtest \
  --strategy ma_convergence \
  --screen-date 20260514 \
  --verify-date 20260515

# 易经策略回测（抽样100只快速验证）
python backtest/runner.py backtest \
  --strategy yijing \
  --screen-date 20260514 \
  --pattern 阳阴阳阴阴阴阳 \
  --sample 100

# 批量回测（多日期区间）
python backtest/runner.py batch \
  --strategy ma_convergence \
  --start 20260501 \
  --end 20260531 \
  --offset 1
```

---

## Web Dashboard（统一前端）

一站式 Web 界面，无需记忆 CLI 参数，三个子系统 Tab 一键切换。

```bash
# 安装依赖
pip install flask

# 启动 Dashboard
python webui/app.py

# 浏览器打开 → http://localhost:5000
```

**功能覆盖：**

| Tab | 功能 | 操作 |
|-----|------|------|
| 🔮 卦象分析 | 单股深度分析 | 填代码 → 选周期 → 点击执行，iframe 内嵌 Chart.js 报告 |
| 📊 卦象筛选 | 全市场 / 单股扫描 | 选模式 → 填参数 → SSE 实时进度 → 统计卡片 |
| ⚡ 策略回测 | 实时筛选 / 单次回测 / 批量回测 | 选策略 → 填日期 → 胜率/收益统计 + 表格 |

**技术实现：** Flask + SSE (Server-Sent Events) 实时推送 + 原生 HTML/CSS/JS，零前端构建工具。

---

## 数据流

### 单股分析（iching_analyzer）

```
股票代码 + 周期参数
    │
    ▼
core/data_fetcher.py              ← mootdx (A股) / Yahoo (港股/美股)
    │                               获取日线/周线/月线 K线数据
    ▼
iching_analyzer/gua_calculator.py ← 6根K线滑动窗口 → 阴阳爻映射 → 64卦
    │
    ▼
core/hexagram_db.py               ← 64卦数据库：爻位 → 卦名/释义/看涨等级
    │
    ▼
iching_analyzer/report_generator.py ← 自包含 HTML（Chart.js 烛台图 + 卦象叠加层）
```

### 全市场筛选（hexagram_screener）

```
全市场 A股 5200+ 只
    │
    ▼
[第1步] MA60 周线过滤           ← 收盘价 > MA60 → 保留约 52%
    │
    ▼
[第2步] 卦象序列扫描            ← 日线/周线/月线三维度，检测卦象形态序列
    │
    ▼
[第3步] 时间过滤                ← 只保留最近 N 天内触发的信号
    │
    ▼
信号分层:
  日线 + 周线/月线共振 → ★★★ 优质买点
  仅日线               → 短期噪音
  仅周线/月线          → 等待日线信号
    │
    ▼
export → CSV + 代码列表（可导入同花顺）
```

### 策略回测（backtest）

```
策略参数 + 筛选日期
    │
    ▼
[粗筛] pre_filter()             ← 快速过滤（股价/市值/ST 等基础条件）
    │
    ▼
[精筛] analyze() × 20线程并发   ← 技术指标 / 卦象形态 / 复杂判定逻辑
    │
    ▼
[回测] 筛选日候选 → 验证日开盘买入
    │
    ▼
统计: 胜率 / 平均收益 / 最大盈利 / 最大亏损 / 盈亏比
```

---

## 卦象映射规则

- **K线 → 爻位**：阳线（收盘 ≥ 开盘）→ 阳爻 `⚊`，阴线（收盘 < 开盘）→ 阴爻 `⚋`
- **滑动窗口**：6 根 K 线 = 1 个卦象（六爻），滑动步长 1
- **方向**：最旧 K 线 → 上爻（第 6 位），最新 K 线 → 初爻（第 1 位）
- **数据库**：64 卦完整收录，每卦含卦名、卦义、行情解读、看涨评级（1~5 星）

---

## 信号分层逻辑

| 分层 | 含义 | 操作建议 |
|------|------|----------|
| 日线 + 周线/月线共振 | 有买点 + 有支撑 | 优先关注，值得深入研究 |
| 日线 + 周线 + 月线三重 | 最强信号 | 趋势确认度最高 |
| 仅日线 | 短期噪音 | 不追，等待周/月线确认 |
| 仅周线/月线 | 有支撑但无买点 | 放入观察池，等待日线触发 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 数据获取 | mootdx (A股)、Yahoo Finance API (港股/美股)、腾讯/新浪（回退）、akshare（股票列表） |
| 核心逻辑 | Python 3.8+，dataclass，ThreadPoolExecutor 并发 |
| 技术指标 | numpy，pandas（DataFrame 与 KLine 双模式） |
| 前端报告 | Chart.js 4.x + chartjs-chart-financial + chartjs-plugin-annotation |
| 输出格式 | HTML（自包含）/ CSV / Excel（openpyxl） |
| 部署 | 零服务器依赖，HTML 双击即可查看 |

---

## 已知限制

- A股数据依赖 mootdx 服务器，不可达时自动回退到腾讯 K线 API
- 美股/港股依赖 Yahoo Finance API，可能受地域限制
- 卦象信号仅供参考，不构成投资建议
- 回测系统的 akshare 依赖用于获取全市场股票列表（非实时行情）

---

## License

MIT
