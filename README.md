# K线卦象分析系统

将六十四卦应用于股票K线分析，通过滑动窗口将K线阴阳映射为卦象，生成自包含的交互式 HTML 分析报告。

## 功能特性

- **多市场支持**：A股、港股、美股，自动识别市场类型
- **多周期支持**：周线、月线卦象分析
- **64 卦完整数据库**：含卦名、释义、投资解读、看涨程度评级
- **交互式报告**：Chart.js 烛台图 + 卦象标注 + 悬停解读 + 点击查看任意6周期卦象
- **零依赖部署**：HTML 报告自包含，CDN 加载前端资源，双击即可查看

## 快速开始

### 安装

```bash
pip install mootdx requests
```

### 使用

```bash
# A股 — 周线分析
python main.py 600519 -i weekly -n 48 -o output/maotai.html

# 港股 — 月线分析
python main.py 09626 -i monthly -n 720 -o output/bilibili.html

# 美股 — 周线分析
python main.py AAPL -i weekly -n 120 -o output/apple.html
```

参数说明：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `symbol` | 股票代码 | 必填 |
| `-i, --interval` | 周期：`weekly` / `monthly` | `monthly` |
| `-n, --count` | K线数量 | `24` |
| `-o, --output` | 输出路径 | `output/{symbol}_{interval}_{timestamp}.html` |

## 项目架构

```
iching-stock/
├── main.py              # CLI 入口，四步流程编排
├── data_fetcher.py      # 统一数据获取层（mootdx / Yahoo）
├── gua_calculator.py    # K线 → 卦象滑动窗口计算
├── hexagram_engine.py   # 六十四卦数据库与查询
├── report_generator.py  # 自包含 HTML 报告生成器
└── output/              # 生成的 HTML 报告
```

### 数据流

```
股票代码 + 周期
    │
    ▼
data_fetcher.py  ←  mootdx (A股) / Yahoo (港股/美股)
    │              获取周线或月线K线数据
    ▼
gua_calculator.py  ←  6根K线滑动窗口 → 阴阳爻映射
    │
    ▼
hexagram_engine.py  ←  64卦数据库：爻位 → 卦名/释义/看涨等级
    │
    ▼
report_generator.py  ←  生成自包含HTML报告
```

## 卦象映射规则

- **K线 → 爻位**：阳线（收盘 ≥ 开盘）→ 阳爻，阴线（收盘 < 开盘）→ 阴爻
- **窗口**：6 根 K 线 = 1 个卦象，滑动步长 1
- **方向**：最旧 K 线 → 上爻，最新 K 线 → 初爻
- **数据库**：64 卦，每卦含看涨程度评级（1~5星）

## 技术栈

| 层级 | 技术 |
|------|------|
| 数据获取 | mootdx (A股)、Yahoo Finance API (港股/美股) |
| 核心逻辑 | Python 3.8+，dataclass 数据结构 |
| 前端报告 | Chart.js 4.x + chartjs-chart-financial + chartjs-plugin-annotation |
| 部署 | 自包含 HTML，零服务器依赖 |

## 报告功能

- **K线图**：Candlestick 图表，A 股红涨绿跌配色，带成交量柱状图（双 Y 轴混合图）
- **卦象标注**：每 6 周期区间上方显示卦名标签
- **悬停解读**：鼠标悬停 K 线显示所在卦象的详细解读
- **点击交互**：点击任意 K 线，显示以该线为首的 6 周期卦象面板 + 高亮标注
- **双表格**：Step1 卦象时间映射表 + Step2 卦象详细解读表

## 已知限制

- A 股数据依赖 mootdx 服务器，网络不可达时回退到腾讯 K 线 API
- 美股/港股依赖 Yahoo Finance API，可能受地域限制
- 不支持日线卦象分析（只支持周线/月线）

## License

MIT
