"""
自包含 HTML 报告生成器
输出单文件 HTML，包含 Chart.js K线图 + 卦象标注 + 双表格
零服务器依赖，双击即可查看
"""

import json
from iching_analyzer.gua_calculator import GuaAnalysis, GuaResult


def generate_html(analysis: GuaAnalysis) -> str:
    """
    生成完整自包含 HTML 报告

    Args:
        analysis: GuaAnalysis 完整分析结果

    Returns:
        完整的 HTML 字符串
    """
    klines_data = _build_klines_json(analysis)
    annotations_data = _build_annotations_json(analysis)
    gua_windows_json = _build_gua_windows_json(analysis)
    step1_table = _build_step1_table(analysis)
    step2_table = _build_step2_table(analysis)

    # 标题格式: "600519 贵州茅台 — 月线卦象分析报告"
    title = f"{analysis.symbol} {analysis.stock_name} — {analysis.interval_label}卦象分析报告"
    html_title = f"{analysis.symbol} {analysis.stock_name} — {analysis.interval_label}卦象分析"

    # Chart.js time scale 参数
    if analysis.interval == "weekly":
        x_unit = "week"
        x_format = "week: 'yyyy-MM-dd'"
    else:
        x_unit = "month"
        x_format = "month: 'yyyy-MM'"

    # 先用 .format() 填充 HTML 模板变量（不含 data JSON）
    html = _HTML_TEMPLATE.format(
        title=html_title,
        header_title=title,
        stock_name=analysis.stock_name,
        symbol=analysis.symbol,
        interval_label=analysis.interval_label,
        total_klines=analysis.total_klines,
        total_guas=analysis.total_guas,
        date_range=f"{analysis.start_date} ~ {analysis.end_date}",
        step1_table=step1_table,
        step2_table=step2_table,
        summary_text=analysis.trend_summary,
        bullish_ratio=f"{analysis.bullish_ratio:.0%}",
        bullish_count=sum(1 for r in analysis.results if r.hexagram.bullish_level >= 4),
        bearish_count=sum(1 for r in analysis.results if r.hexagram.bullish_level <= 2),
        neutral_count=sum(1 for r in analysis.results if r.hexagram.bullish_level == 3),
        x_unit=x_unit,
        x_format=x_format,
    )
    # 后注入 JSON 数据（避免 JS 对象花括号与 .format() 冲突）
    html = html.replace('__KLINES_JSON__', json.dumps(klines_data, ensure_ascii=False))
    html = html.replace('__ANNOTATIONS_JSON__', json.dumps(annotations_data, ensure_ascii=False))
    html = html.replace('__GUA_WINDOWS_JSON__', json.dumps(gua_windows_json, ensure_ascii=False))
    return html


def _build_klines_json(analysis: GuaAnalysis) -> list[dict]:
    """构建 Chart.js K线图数据"""
    if not analysis.results:
        return []

    date_set = {}
    for result in analysis.results:
        for yao in result.yao_lines:
            k = yao.kline
            if k.date not in date_set:
                from datetime import datetime
                date_part = k.date.split(' ')[0] if ' ' in k.date else k.date
                dt = datetime.strptime(date_part, '%Y-%m-%d')
                ts = int(dt.timestamp() * 1000)
                date_set[k.date] = {
                    "x": ts,
                    "o": k.open,
                    "h": k.high,
                    "l": k.low,
                    "c": k.close,
                    "v": k.volume,
                }

    sorted_dates = sorted(date_set.keys())
    return [date_set[d] for d in sorted_dates]


def _build_annotations_json(analysis: GuaAnalysis) -> list[dict]:
    """构建卦象区域标注数据"""
    annotations = []
    for result in analysis.results:
        from datetime import datetime
        start_dt = datetime.strptime(result.start_date.split(' ')[0], '%Y-%m-%d')
        end_dt = datetime.strptime(result.end_date.split(' ')[0], '%Y-%m-%d')

        start_ts = int(start_dt.timestamp() * 1000)
        end_ts = int(end_dt.timestamp() * 1000)

        level = result.hexagram.bullish_level
        # 所有背景统一透明（纯白底），仅文字颜色区分解读倾向
        bg_color = "transparent"
        if level >= 5:
            text_color = "#b91c1c"
        elif level == 4:
            text_color = "#c2410c"
        elif level == 3:
            text_color = "#475569"
        elif level == 2:
            text_color = "#1d4ed8"
        else:
            text_color = "#15803d"

        annotations.append({
            "id": f"gua_{result.index}",
            "xMin": start_ts,
            "xMax": end_ts,
            "label": result.hexagram.name,
            "symbol": result.hexagram.symbol,
            "backgroundColor": bg_color,
            "textColor": text_color,
        })

    return annotations


def _build_gua_windows_json(analysis: GuaAnalysis) -> list[dict]:
    """构建卦象窗口数据（供 JS hover tooltip 使用）"""
    windows = []
    for result in analysis.results:
        from datetime import datetime
        start_dt = datetime.strptime(result.start_date.split(' ')[0], '%Y-%m-%d')
        end_dt = datetime.strptime(result.end_date.split(' ')[0], '%Y-%m-%d')

        periods = []
        for p in result.periods_with_yao:
            periods.append({
                "label": p["label"],
                "is_yang": p["is_yang"],
            })

        windows.append({
            "index": result.index,
            "start_ts": int(start_dt.timestamp() * 1000),
            "end_ts": int(end_dt.timestamp() * 1000),
            "start_label": result.start_date[:7],
            "end_label": result.end_date[:7],
            "hexagram_name": result.hexagram.name,
            "hexagram_symbol": result.hexagram.symbol,
            "hexagram_meaning": result.hexagram.meaning,
            "hexagram_interpretation": result.hexagram.interpretation,
            "bullish_level": result.hexagram.bullish_level,
            "periods": periods,
        })

    return windows


def _build_step1_table(analysis: GuaAnalysis) -> str:
    """构建第一步表格: 窗口 → 卦名映射（含 6 个 K 线周期的阴阳标识）"""
    rows = []
    for r in analysis.results:
        level_stars = "★" * r.hexagram.bullish_level + "☆" * (5 - r.hexagram.bullish_level)

        # 构建周期明细（带阴阳着色）
        period_spans = []
        for p in r.periods_with_yao:
            cls = "yao-yang" if p["is_yang"] else "yao-yin"
            icon = "阳" if p["is_yang"] else "阴"
            period_spans.append(
                f'<span class="period-tag {cls}">{p["label"]} {icon}</span>'
            )
        periods_html = "".join(period_spans)

        rows.append(f"""
        <tr>
            <td class="num">{r.index}</td>
            <td class="date">{r.date_range}</td>
            <td class="periods">{periods_html}</td>
            <td class="symbol-td">{r.hexagram.symbol}</td>
            <td class="name-td">{r.hexagram.name}</td>
            <td class="level">{level_stars}</td>
        </tr>""")

    return "\n".join(rows)


def _build_step2_table(analysis: GuaAnalysis) -> str:
    """构建第二步表格: 卦象详细解读"""
    rows = []
    for h in analysis.unique_hexagrams:
        occurrences = [r for r in analysis.results if r.hexagram.index == h.index]
        count = len(occurrences)
        positions = ", ".join(str(r.index) for r in occurrences)

        rows.append(f"""
        <tr>
            <td class="symbol-lg">{h.symbol}</td>
            <td class="name-lg">{h.name}</td>
            <td class="meaning">{h.meaning}</td>
            <td class="interpretation">{h.interpretation}</td>
            <td class="count-td">出现 {count} 次<br><span class="pos">#{positions}</span></td>
        </tr>""")

    return "\n".join(rows)


# ============================================================
# HTML 模板
# ============================================================

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.2.1/dist/chartjs-chart-financial.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Microsoft YaHei", sans-serif;
    background: #f8fafc; color: #1e293b; line-height: 1.6;
    padding: 24px;
}}
.container {{ max-width: 1400px; margin: 0 auto; }}
.header {{
    text-align: center; padding: 32px 0; border-bottom: 2px solid #e2e8f0; margin-bottom: 32px;
}}
.header h1 {{ font-size: 28px; color: #0f172a; margin-bottom: 8px; }}
.header .meta {{ color: #64748b; font-size: 14px; }}
.header .meta span {{ margin: 0 12px; }}

.summary-cards {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px; margin-bottom: 32px;
}}
.card {{
    background: #fff; border-radius: 12px; padding: 20px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;
}}
.card .card-value {{ font-size: 32px; font-weight: 700; color: #0f172a; }}
.card .card-label {{ font-size: 13px; color: #64748b; margin-top: 4px; }}
.card.bullish .card-value {{ color: #dc2626; }}
.card.bearish .card-value {{ color: #16a34a; }}

.chart-section {{
    background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 32px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;
}}
.chart-section h2 {{
    font-size: 18px; margin-bottom: 16px; color: #0f172a;
    display: flex; align-items: center; gap: 8px;
}}
.chart-container {{ height: 520px; }}

/* 点击 K 线卦象详情面板 */
.gua-click-panel {{
    margin-top: 20px; background: #fafbfc; border: 1px solid #e2e8f0;
    border-radius: 12px; padding: 20px 24px; position: relative;
    display: block; min-height: 80px;
}}
.gcp-dismiss {{
    position: absolute; top: 12px; right: 16px; width: 28px; height: 28px;
    border-radius: 50%; background: #e2e8f0; color: #64748b;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; line-height: 1; cursor: pointer;
    transition: background 0.15s, color 0.15s; user-select: none; z-index: 10;
}}
.gcp-dismiss:hover {{ background: #cbd5e1; color: #0f172a; }}
.gcp-empty {{
    color: #94a3b8; font-size: 14px; text-align: center; padding: 24px 0;
}}
.gcp-content {{ display: none; }}
.gcp-header {{
    display: flex; align-items: center; gap: 12px; margin-bottom: 14px;
    padding-bottom: 14px; border-bottom: 1px solid #e2e8f0;
}}
.gcp-symbol {{ font-size: 36px; }}
.gcp-name {{ font-weight: 700; font-size: 20px; color: #0f172a; }}
.gcp-range {{ color: #64748b; font-size: 13px; }}
.gcp-level {{ margin-left: auto; font-size: 15px; color: #94a3b8; }}
.gcp-meaning {{
    font-size: 14px; color: #475569; margin-bottom: 8px;
    padding: 8px 14px; background: #f1f5f9; border-radius: 8px;
}}
.gcp-interpretation {{
    font-size: 13px; color: #334155; line-height: 1.8; margin-bottom: 14px;
}}
.gcp-periods {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.gcp-period-tag {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 4px 12px; border-radius: 6px; font-size: 12px;
    font-weight: 600; font-family: "SF Mono","Courier New",monospace;
}}
.gcp-period-tag.yao-yang {{ background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }}
.gcp-period-tag.yao-yin {{ background: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0; }}
.gcp-period-tag .gcp-pos {{ font-size: 10px; color: #94a3b8; font-weight: 400; }}
.gcp-no-data {{
    color: #ef4444; font-size: 14px; text-align: center; padding: 20px 0;
    display: none;
}}

/* 自定义卦象 tooltip 面板 */
.gua-tooltip {{
    position: absolute; z-index: 100;
    background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 16px 20px; box-shadow: 0 8px 30px rgba(0,0,0,0.12);
    pointer-events: none; max-width: 360px; font-size: 13px;
    display: none; line-height: 1.7;
}}
.gua-tooltip .tt-header {{
    display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
    padding-bottom: 8px; border-bottom: 1px solid #f1f5f9;
}}
.gua-tooltip .tt-symbol {{ font-size: 26px; }}
.gua-tooltip .tt-name {{ font-weight: 700; font-size: 16px; color: #0f172a; }}
.gua-tooltip .tt-range {{ color: #64748b; font-size: 12px; }}
.gua-tooltip .tt-meaning {{ color: #475569; margin-bottom: 6px; }}
.gua-tooltip .tt-interpretation {{ color: #334155; }}
.gua-tooltip .tt-periods {{ margin-top: 8px; padding-top: 8px; border-top: 1px solid #f1f5f9; }}
.gua-tooltip .tt-period-tag {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; margin: 2px 3px; font-weight: 600;
}}
.tt-period-yang {{ background: #fef2f2; color: #dc2626; }}
.tt-period-yin {{ background: #f0fdf4; color: #16a34a; }}

.table-section {{
    background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 32px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;
    overflow-x: auto;
}}
.table-section h2 {{
    font-size: 18px; margin-bottom: 16px; color: #0f172a;
    display: flex; align-items: center; gap: 8px;
}}

table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th {{
    background: #f1f5f9; padding: 12px 16px; text-align: left; font-weight: 600;
    color: #475569; border-bottom: 2px solid #e2e8f0; white-space: nowrap;
}}
td {{ padding: 10px 16px; border-bottom: 1px solid #f1f5f9; }}
tr:hover {{ background: #f8fafc; }}

.num {{ text-align: center; color: #64748b; font-weight: 600; width: 50px; }}
.date {{ color: #334155; font-family: "SF Mono", "Courier New", monospace; font-size: 13px; white-space: nowrap; }}
.periods {{ white-space: nowrap; }}
.symbol-td {{ font-size: 22px; text-align: center; }}
.name-td {{ font-weight: 600; color: #0f172a; }}
.level {{ color: #94a3b8; font-size: 13px; }}
.symbol-lg {{ font-size: 28px; text-align: center; min-width: 60px; }}
.name-lg {{ font-weight: 700; color: #0f172a; font-size: 15px; min-width: 70px; white-space: nowrap; }}
.meaning {{ color: #475569; font-size: 13px; max-width: 150px; }}
.interpretation {{ font-size: 13px; color: #334155; line-height: 1.7; max-width: 500px; }}
.count-td {{ text-align: center; font-size: 13px; }}
.count-td .pos {{ color: #94a3b8; font-size: 12px; }}

/* 阴阳周期标签 */
.period-tag {{
    display: inline-block; padding: 3px 9px; border-radius: 5px;
    font-size: 12px; margin: 2px 4px; font-weight: 600;
    font-family: "SF Mono", "Courier New", monospace;
}}
.period-tag.yao-yang {{
    background: #fef2f2; color: #dc2626; border: 1px solid #fecaca;
}}
.period-tag.yao-yin {{
    background: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0;
}}

.trend-summary {{
    background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 32px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;
}}
.trend-summary h2 {{ font-size: 18px; margin-bottom: 12px; }}
.trend-summary p {{ font-size: 15px; color: #475569; line-height: 1.8; }}

.footer {{ text-align: center; padding: 32px 0; color: #94a3b8; font-size: 12px; }}

@media (max-width: 768px) {{
    body {{ padding: 12px; }}
    .chart-container {{ height: 420px; }}
    .header h1 {{ font-size: 22px; }}
}}
</style>
</head>
<body>
<div class="container">

<!-- 头部 -->
<div class="header">
    <h1>{header_title}</h1>
    <div class="meta">
        <span>数据范围: {date_range}</span>
        <span>K线数量: {total_klines}</span>
        <span>卦象数量: {total_guas}</span>
    </div>
</div>

<!-- 统计卡片 -->
<div class="summary-cards">
    <div class="card">
        <div class="card-value">{total_guas}</div>
        <div class="card-label">总卦象数</div>
    </div>
    <div class="card bullish">
        <div class="card-value">{bullish_count}</div>
        <div class="card-label">看涨卦象</div>
    </div>
    <div class="card">
        <div class="card-value">{neutral_count}</div>
        <div class="card-label">中性卦象</div>
    </div>
    <div class="card bearish">
        <div class="card-value">{bearish_count}</div>
        <div class="card-label">看跌卦象</div>
    </div>
    <div class="card">
        <div class="card-value">{bullish_ratio}</div>
        <div class="card-label">看涨比例</div>
    </div>
</div>

<!-- 趋势总结 -->
<div class="trend-summary">
    <h2>趋势总结</h2>
    <p>{summary_text}</p>
</div>

<!-- K线图 + 卦象标注 + 悬停解读 -->
<div class="chart-section">
    <h2>K线图与卦象标注 <span style="font-size:12px;color:#94a3b8;font-weight:400;">（悬停查看卦象解读 | 点击 K 线查看以该线为首的 6 周期卦象）</span></h2>
    <div style="position:relative;">
        <div class="chart-container">
            <canvas id="klinesChart"></canvas>
        </div>
        <div class="gua-tooltip" id="guaTooltip">
            <div class="tt-header">
                <span class="tt-symbol" id="ttSymbol"></span>
                <div>
                    <div class="tt-name" id="ttName"></div>
                    <div class="tt-range" id="ttRange"></div>
                </div>
            </div>
            <div class="tt-meaning" id="ttMeaning"></div>
            <div class="tt-interpretation" id="ttInterpretation"></div>
            <div class="tt-periods" id="ttPeriods"></div>
        </div>
    </div>
    <!-- 点击K线卦象详情面板 -->
    <div class="gua-click-panel" id="guaClickPanel">
        <div class="gcp-dismiss" id="gcpDismiss" title="关闭">&times;</div>
    <div class="gcp-empty" id="gcpEmpty">点击 K 线即可查看以该 K 线为首的 6 周期卦象</div>
    <div class="gcp-no-data" id="gcpNoData"></div>
    <div class="gcp-content" id="gcpContent">
            <div class="gcp-header">
                <span class="gcp-symbol" id="gcpSymbol"></span>
                <div>
                    <div class="gcp-name" id="gcpName"></div>
                    <div class="gcp-range" id="gcpRange"></div>
                </div>
                <div class="gcp-level" id="gcpLevel"></div>
            </div>
            <div class="gcp-meaning" id="gcpMeaning"></div>
            <div class="gcp-interpretation" id="gcpInterpretation"></div>
            <div class="gcp-periods" id="gcpPeriods"></div>
        </div>
    </div>
</div>

<!-- Step 1: 卦象时间映射表 -->
<div class="table-section">
    <h2>第一步：卦象时间映射表</h2>
    <table class="step1-table">
        <thead>
            <tr>
                <th>序号</th>
                <th>时间范围</th>
                <th>K线周期明细</th>
                <th>卦象</th>
                <th>卦名</th>
                <th>看涨程度</th>
            </tr>
        </thead>
        <tbody>
            {step1_table}
        </tbody>
    </table>
</div>

<!-- Step 2: 卦象详细解读 -->
<div class="table-section">
    <h2>第二步：卦象详细解读</h2>
    <table class="step2-table">
        <thead>
            <tr>
                <th>卦象</th>
                <th>卦名</th>
                <th>卦义</th>
                <th>行情解读</th>
                <th>出现频次</th>
            </tr>
        </thead>
        <tbody>
            {step2_table}
        </tbody>
    </table>
</div>

<div class="footer">
    由 K线卦象分析系统 自动生成 &nbsp;|&nbsp; 仅供参考，不构成投资建议
</div>

</div>

<script>
// ============================================================
// K线图 + 卦象标注 + 悬停卦象解读
// ============================================================

const klinesData = __KLINES_JSON__;
const annotations = __ANNOTATIONS_JSON__;
const guaWindows = __GUA_WINDOWS_JSON__;

// 计算最大成交量，用于限制柱体高度（控制成交量区域占比）
const maxVolume = Math.max(...klinesData.map(function(d) {{ return d.v || 0; }}));

// chartjs-chart-financial 的 UMD 脚本已自动注册 candlestick/ohlc 类型
// annotation 插件全局名为 "chartjs-plugin-annotation"（含连字符，需 bracket 访问）
Chart.register(window["chartjs-plugin-annotation"]);

const ctx = document.getElementById('klinesChart').getContext('2d');

// 构建 annotation 配置
const annotationConfigs = {{}};
annotations.forEach(function(ann) {{
    annotationConfigs[ann.id] = {{
        type: 'box',
        xMin: ann.xMin,
        xMax: ann.xMax,
        yMin: 'min',
        yMax: 'max',
        backgroundColor: ann.backgroundColor,
        borderWidth: 0,
        label: {{
            display: true,
            content: ann.label + ' ' + ann.symbol,
            position: {{ x: 'center', y: 'start' }},
            backgroundColor: 'transparent',
            color: ann.textColor,
            font: {{
                size: 11,
                weight: 'bold',
                family: '"PingFang SC","Microsoft YaHei",sans-serif'
            }},
            yAdjust: -14
        }}
    }};
}});

// 动态高亮 annotation（点击 K 线时显示）
annotationConfigs['hexagram-highlight'] = {{
    type: 'box',
    xMin: 0,
    xMax: 0,
    yMin: 'min',
    yMax: 'max',
    backgroundColor: 'rgba(234, 179, 8, 0.12)',
    borderColor: '#eab308',
    borderWidth: 2,
    borderDash: [8, 4],
    display: false,
}};

// 构建 gua 时间戳索引（用于快速查找）
const guaIndex = {{}};
guaWindows.forEach(function(gw, idx) {{
    // 用 start_ts 建索引
    const key = gw.start_ts;
    if (!guaIndex[key]) guaIndex[key] = [];
    guaIndex[key].push(idx);
}});

// 根据时间戳查找对应的卦象
function findGuaByTimestamp(ts) {{
    // 查找包含该时间戳的窗口
    for (let i = guaWindows.length - 1; i >= 0; i--) {{
        if (ts >= guaWindows[i].start_ts && ts <= guaWindows[i].end_ts) {{
            return guaWindows[i];
        }}
    }}
    return null;
}}

// Tooltip DOM 元素
const tooltipEl = document.getElementById('guaTooltip');
const ttSymbol = document.getElementById('ttSymbol');
const ttName = document.getElementById('ttName');
const ttRange = document.getElementById('ttRange');
const ttMeaning = document.getElementById('ttMeaning');
const ttInterpretation = document.getElementById('ttInterpretation');
const ttPeriods = document.getElementById('ttPeriods');

const chart = new Chart(ctx, {{
    type: 'candlestick',
    data: {{
        datasets: [{{
            label: '{interval_label}K线',
            data: klinesData,
            yAxisID: 'y',
            order: 1,
            // 直接反过来：up=红、down=绿，与成交量图一致
            backgroundColors: {{
                up: '#dc2626',      // 红
                down: '#16a34a',    // 绿
                unchanged: '#999'
            }},
            borderColors: {{
                up: '#dc2626',
                down: '#16a34a',
                unchanged: '#999'
            }}
        }}, {{
            label: '成交量',
            type: 'bar',
            data: klinesData.map(function(d) {{ return {{ x: d.x, v: d.v || 0 }}; }}),
            yAxisID: 'volume',
            order: 2,
            backgroundColor: klinesData.map(function(d) {{ return d.c >= d.o ? '#dc2626' : '#16a34a'; }}),
            borderWidth: 0,
            parsing: {{
                xAxisKey: 'x',
                yAxisKey: 'v',
            }},
            barPercentage: 0.85,
            categoryPercentage: 1.0,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{
            mode: 'index',
            intersect: false
        }},
        plugins: {{
            annotation: {{
                annotations: annotationConfigs
            }},
            tooltip: {{
                enabled: false
            }},
            legend: {{ display: true, position: 'top' }}
        }},
        scales: {{
            x: {{
                type: 'time',
                time: {{
                    unit: '{x_unit}',
                    displayFormats: {{ {x_format} }}
                }},
                title: {{ display: true, text: '日期' }},
                ticks: {{ maxTicksLimit: 24 }}
            }},
            y: {{
                position: 'left',
                title: {{ display: true, text: '价格' }},
                ticks: {{
                    callback: function(v) {{ return v.toFixed(2); }}
                }}
            }},
            volume: {{
                position: 'right',
                title: {{ display: false }},
                grid: {{ display: false }},
                // 成交量柱体只占图表下方约 1/10 区域
                min: 0,
                max: maxVolume * 10,
                ticks: {{
                    callback: function(v) {{
                        if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿';
                        if (v >= 1e4) return (v / 1e4).toFixed(1) + '万';
                        return v;
                    }},
                    maxTicksLimit: 4,
                }}
            }}
        }},
        // 鼠标悬停事件 — 显示卦象解读
        onHover: function(event, elements) {{
            if (elements && elements.length > 0) {{
                const el = elements[0];
                const dataPoint = klinesData[el.index];
                if (!dataPoint) return;
                const ts = dataPoint.x;
                const gua = findGuaByTimestamp(ts);
                if (!gua) return;

                // 填充 tooltip
                ttSymbol.textContent = gua.hexagram_symbol;
                ttName.textContent = gua.hexagram_name;
                ttRange.textContent = gua.start_label + ' → ' + gua.end_label;
                ttMeaning.textContent = gua.hexagram_meaning;
                ttInterpretation.textContent = gua.hexagram_interpretation;

                // 构建周期标签
                let periodHtml = '';
                gua.periods.forEach(function(p) {{
                    const cls = p.is_yang ? 'tt-period-yang' : 'tt-period-yin';
                    const icon = p.is_yang ? '阳' : '阴';
                    periodHtml += '<span class="tt-period-tag ' + cls + '">' + p.label + ' ' + icon + '</span>';
                }});
                ttPeriods.innerHTML = periodHtml;

                // 定位 tooltip (position:absolute 相对于 wrapper)
                const chartArea = chart.chartArea;
                if (!chartArea) return;
                const canvas = chart.canvas;
                const wrapper = tooltipEl.parentElement;
                const wrapperRect = wrapper.getBoundingClientRect();
                const canvasRect = canvas.getBoundingClientRect();
                let left = canvasRect.left - wrapperRect.left + chartArea.left + (el.element.x || 0);
                let top = canvasRect.top - wrapperRect.top + chartArea.top - 10;

                // 防止溢出
                const tooltipWidth = tooltipEl.offsetWidth || 380;
                if (left + tooltipWidth + 10 > wrapperRect.width) left = wrapperRect.width - tooltipWidth - 10;
                if (left < 0) left = 10;
                if (top < 0) top = 10;

                tooltipEl.style.left = left + 'px';
                tooltipEl.style.top = top + 'px';
                tooltipEl.style.display = 'block';
            }} else {{
                tooltipEl.style.display = 'none';
            }}
        }}
    }}
}});

// 鼠标离开 canvas 隐藏 tooltip
document.getElementById('klinesChart').addEventListener('mouseleave', function() {{
    tooltipEl.style.display = 'none';
}});

// ============================================================
// 点击 K 线 → 显示以该 K 线为首的 6 周期卦象
// ============================================================
const clickPanel = document.getElementById('guaClickPanel');
const gcpDismiss = document.getElementById('gcpDismiss');
const gcpEmpty = document.getElementById('gcpEmpty');
const gcpContent = document.getElementById('gcpContent');
const gcpNoData = document.getElementById('gcpNoData');
const gcpSymbol = document.getElementById('gcpSymbol');
const gcpName = document.getElementById('gcpName');
const gcpRange = document.getElementById('gcpRange');
const gcpLevel = document.getElementById('gcpLevel');
const gcpMeaning = document.getElementById('gcpMeaning');
const gcpInterpretation = document.getElementById('gcpInterpretation');
const gcpPeriods = document.getElementById('gcpPeriods');

function showGuaByStartTs(ts, dataPoint) {{
    const indices = guaIndex[ts];
    if (!indices || indices.length === 0) {{
        // 最后 5 根 K 线无法构成完整卦象
        gcpEmpty.style.display = 'none';
        gcpContent.style.display = 'none';
        if (gcpNoData) gcpNoData.style.display = 'block';
        const dt = new Date(ts);
        if (gcpNoData) gcpNoData.textContent = '⚠ 数据不足：' + dt.toISOString().slice(0, 7) + ' 起不足 6 个周期，未形成完整卦象';
        return;
    }}

    const gua = guaWindows[indices[0]];

    // 更新图表高亮区域
    const annots = chart.options.plugins.annotation.annotations;
    annots['hexagram-highlight'].xMin = ts;
    annots['hexagram-highlight'].xMax = gua.end_ts;
    annots['hexagram-highlight'].display = true;
    chart.update('none');

    // 填充面板内容
    gcpSymbol.textContent = gua.hexagram_symbol;
    gcpName.textContent = gua.hexagram_name;
    gcpRange.textContent = gua.start_label + ' → ' + gua.end_label;

    // 看涨程度星级
    const stars = '★'.repeat(gua.bullish_level) + '☆'.repeat(5 - gua.bullish_level);
    const levelLabels = ['', '强烈看跌', '看跌', '中性', '看涨', '强烈看涨'];
    gcpLevel.textContent = stars + ' ' + levelLabels[gua.bullish_level];

    gcpMeaning.textContent = gua.hexagram_meaning;
    gcpInterpretation.textContent = gua.hexagram_interpretation;

    // 构建周期标签（上爻→初爻，最旧→最新）
    let periodHtml = '';
    const posLabels = ['', '初', '二', '三', '四', '五', '上'];
    gua.periods.forEach(function(p, idx) {{
        const cls = p.is_yang ? 'yao-yang' : 'yao-yin';
        const icon = p.is_yang ? '阳' : '阴';
        const pos = 6 - idx; // periods 是 上爻→初爻（最旧→最新）
        periodHtml += '<span class="gcp-period-tag ' + cls + '">' +
            '<span class="gcp-pos">' + posLabels[pos] + '</span>' +
            p.label + ' ' + icon +
            '</span>';
    }});
    gcpPeriods.innerHTML = periodHtml;

    // 显示面板内容
    gcpEmpty.style.display = 'none';
    if (gcpNoData) gcpNoData.style.display = 'none';
    gcpContent.style.display = 'block';
}}

document.getElementById('klinesChart').addEventListener('click', function(evt) {{
    const points = chart.getElementsAtEventForMode(evt, 'index', {{ intersect: true }});
    if (!points || points.length === 0) return;

    const idx = points[0].index;
    const dataPoint = klinesData[idx];
    if (!dataPoint) return;

    showGuaByStartTs(dataPoint.x, dataPoint);
}});

// 关闭面板按钮
gcpDismiss.addEventListener('click', function(e) {{
    e.stopPropagation();
    gcpContent.style.display = 'none';
    if (gcpNoData) gcpNoData.style.display = 'none';
    gcpEmpty.style.display = 'block';
    // 清除图表高亮
    chart.options.plugins.annotation.annotations['hexagram-highlight'].display = false;
    chart.update('none');
}});
</script>

</body>
</html>"""
