"""
周线爆发选股策略
================
基于布林带扩张 + 放量 + MACD金叉零轴上方的周线级别选股策略。

策略逻辑：
1. BOLL_COND: 布林带上轨上升、中轨上升、下轨下降（布林带开口扩张）
2. VOL_COND: 26周内存在成交量比大于4倍的周（放量）
3. MACD_COND: 3周内存在MACD在零轴上方金叉
"""

import numpy as np
import pandas as pd
import akshare as ak
import json
import os
import sys
from datetime import datetime, timedelta
from jinja2 import Template
import traceback
import time


def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移动平均"""
    return series.ewm(span=period, adjust=False).mean()


def ma(series: pd.Series, period: int) -> pd.Series:
    """简单移动平均"""
    return series.rolling(window=period).mean()


def std(series: pd.Series, period: int) -> pd.Series:
    """标准差"""
    return series.rolling(window=period).std(ddof=0)


def ref(series: pd.Series, n: int) -> pd.Series:
    """前N期引用"""
    return series.shift(n)


def cross(s1: pd.Series, s2: pd.Series) -> pd.Series:
    """上穿：s1从下方穿越s2"""
    return (s1 > s2) & (s1.shift(1) <= s2.shift(1))


def exist(cond: pd.Series, n: int) -> pd.Series:
    """N周期内是否存在满足条件"""
    return cond.rolling(window=n).max().astype(bool)


def apply_strategy(df: pd.DataFrame) -> pd.Series:
    """
    对周线数据应用"周线爆发"策略
    df 需包含: close, vol 列
    返回布尔Series，True表示当前周满足选股条件
    """
    close = df['close']
    vol = df['vol']

    # --- 布林带条件 ---
    mid = ma(close, 20)
    upper = mid + 2 * std(close, 20)
    lower = mid - 2 * std(close, 20)

    boll_cond = (
        (upper > ref(upper, 1)) &
        (mid > ref(mid, 1)) &
        (lower < ref(lower, 1))
    )

    # --- 成交量条件 ---
    vol_ratio = vol / ref(vol, 1)
    vol_cond = exist(vol_ratio > 4, 26)

    # --- MACD条件 ---
    dif = ema(close, 12) - ema(close, 26)
    dea = ema(dif, 9)
    jc = cross(dif, dea)
    zero_cond = dea > 0
    macd_cond = exist(jc & zero_cond, 3)

    # --- 综合选股 ---
    xg = boll_cond & vol_cond & macd_cond
    return xg


def get_all_a_stocks():
    """获取所有A股股票列表"""
    print("[1/4] 获取A股股票列表...")
    try:
        stock_info = ak.stock_zh_a_spot_em()
        # 过滤掉ST、退市股、北交所
        stock_info = stock_info[~stock_info['名称'].str.contains('ST|退|N', na=False)]
        # 只保留沪深主板、创业板、科创板
        stock_info = stock_info[
            stock_info['代码'].str.match(r'^(00|30|60|68)')
        ]
        print(f"  共 {len(stock_info)} 只股票待筛选")
        return stock_info[['代码', '名称']].reset_index(drop=True)
    except Exception as e:
        print(f"  获取股票列表失败: {e}")
        traceback.print_exc()
        return pd.DataFrame(columns=['代码', '名称'])


def get_weekly_data(stock_code: str, name: str) -> pd.DataFrame:
    """获取单只股票的周线数据"""
    try:
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="weekly",
            start_date=(datetime.now() - timedelta(days=800)).strftime('%Y%m%d'),
            end_date=datetime.now().strftime('%Y%m%d'),
            adjust="qfq"
        )
        if df is None or len(df) < 30:
            return pd.DataFrame()

        df = df.rename(columns={
            '收盘': 'close',
            '成交量': 'vol',
            '开盘': 'open',
            '最高': 'high',
            '最低': 'low',
            '日期': 'date'
        })
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


def get_daily_data_for_display(stock_code: str) -> dict:
    """获取最新日线数据用于页面展示"""
    try:
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=(datetime.now() - timedelta(days=10)).strftime('%Y%m%d'),
            end_date=datetime.now().strftime('%Y%m%d'),
            adjust="qfq"
        )
        if df is None or len(df) == 0:
            return {}
        latest = df.iloc[-1]
        prev_close = df.iloc[-2]['收盘'] if len(df) > 1 else latest['开盘']
        change_pct = (latest['收盘'] - prev_close) / prev_close * 100
        return {
            'price': float(latest['收盘']),
            'change_pct': round(change_pct, 2),
            'volume': float(latest['成交量']),
            'turnover': float(latest['成交额']),
            'high': float(latest['最高']),
            'low': float(latest['最低']),
            'open': float(latest['开盘']),
        }
    except Exception:
        return {}


def run_strategy():
    """运行完整选股流程"""
    print("=" * 60)
    print(f"  周线爆发选股策略 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    stocks = get_all_a_stocks()
    if stocks.empty:
        print("无法获取股票列表，退出")
        return []

    selected = []
    total = len(stocks)

    print(f"\n[2/4] 逐只计算策略信号（共 {total} 只）...")
    for idx, row in stocks.iterrows():
        code = row['代码']
        name = row['名称']

        if idx % 100 == 0:
            print(f"  进度: {idx}/{total} ({idx/total*100:.1f}%)")

        df = get_weekly_data(code, name)
        if df.empty:
            continue

        try:
            signal = apply_strategy(df)
            if signal.iloc[-1]:  # 最新一周满足条件
                selected.append({
                    'code': code,
                    'name': name,
                })
                print(f"  ★ 选中: {code} {name}")
        except Exception:
            continue

        # 控制请求频率，避免被封
        time.sleep(0.15)

    print(f"\n[3/4] 获取选中股票的最新行情...")
    for item in selected:
        daily = get_daily_data_for_display(item['code'])
        item.update(daily)
        time.sleep(0.1)

    print(f"\n  共选出 {len(selected)} 只股票")
    return selected


def generate_html(selected_stocks: list, output_path: str):
    """生成移动端适配的HTML展示页面"""
    print(f"\n[4/4] 生成展示页面...")

    template_str = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>周线爆发选股</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
    background: #0a0e27;
    color: #e0e6ff;
    min-height: 100vh;
    padding-bottom: env(safe-area-inset-bottom);
}
.header {
    background: linear-gradient(135deg, #1a1f4e 0%, #0d1234 100%);
    padding: 20px 16px 16px;
    border-bottom: 1px solid rgba(100, 120, 255, 0.15);
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(20px);
}
.header h1 {
    font-size: 20px;
    font-weight: 700;
    background: linear-gradient(90deg, #6c8cff, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: 1px;
}
.header .meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 8px;
    font-size: 12px;
    color: #7a85b3;
}
.header .count {
    background: rgba(100, 120, 255, 0.15);
    color: #8fa4ff;
    padding: 2px 10px;
    border-radius: 12px;
    font-weight: 600;
}
.strategy-tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: rgba(167, 139, 250, 0.12);
    color: #a78bfa;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 11px;
    margin-top: 10px;
}
.strategy-tag::before {
    content: '';
    width: 6px;
    height: 6px;
    background: #a78bfa;
    border-radius: 50%;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
.stock-list { padding: 12px; }
.stock-card {
    background: linear-gradient(135deg, rgba(26, 31, 78, 0.8) 0%, rgba(13, 18, 52, 0.9) 100%);
    border: 1px solid rgba(100, 120, 255, 0.1);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 10px;
    transition: all 0.2s;
    position: relative;
    overflow: hidden;
}
.stock-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, rgba(100, 120, 255, 0.3), transparent);
}
.stock-card:active {
    transform: scale(0.98);
    border-color: rgba(100, 120, 255, 0.3);
}
.card-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
}
.stock-name {
    font-size: 17px;
    font-weight: 700;
    color: #e8ecff;
}
.stock-code {
    font-size: 12px;
    color: #5a6599;
    margin-top: 2px;
    font-family: 'SF Mono', 'Fira Code', monospace;
}
.stock-price {
    text-align: right;
}
.price-value {
    font-size: 22px;
    font-weight: 700;
    font-family: 'SF Mono', 'DIN Alternate', monospace;
}
.price-change {
    font-size: 13px;
    font-weight: 600;
    margin-top: 2px;
}
.up { color: #f43f5e; }
.down { color: #10b981; }
.flat { color: #7a85b3; }
.card-bottom {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid rgba(100, 120, 255, 0.08);
}
.metric {
    text-align: center;
}
.metric-label {
    font-size: 10px;
    color: #5a6599;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.metric-value {
    font-size: 13px;
    color: #b0badf;
    margin-top: 2px;
    font-family: 'SF Mono', monospace;
}
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: #5a6599;
}
.empty-state .icon { font-size: 48px; margin-bottom: 16px; }
.empty-state p { font-size: 14px; line-height: 1.6; }
.footer {
    text-align: center;
    padding: 20px;
    font-size: 11px;
    color: #3d4570;
    border-top: 1px solid rgba(100, 120, 255, 0.06);
    margin-top: 10px;
}
.footer a { color: #5a6599; text-decoration: none; }
.disclaimer {
    background: rgba(234, 179, 8, 0.06);
    border: 1px solid rgba(234, 179, 8, 0.15);
    border-radius: 10px;
    padding: 12px 14px;
    margin: 12px;
    font-size: 11px;
    color: #b8a44a;
    line-height: 1.5;
}
</style>
</head>
<body>
<div class="header">
    <h1>周线爆发选股</h1>
    <div class="meta">
        <span>{{ update_time }}</span>
        <span class="count">{{ stock_count }} 只</span>
    </div>
    <div class="strategy-tag">BOLL扩张 + 放量 + MACD零上金叉</div>
</div>

<div class="disclaimer">
    本页面仅为量化策略筛选结果展示，不构成任何投资建议。股市有风险，投资需谨慎。
</div>

<div class="stock-list">
{% if stocks %}
{% for s in stocks %}
<div class="stock-card">
    <div class="card-top">
        <div>
            <div class="stock-name">{{ s.name }}</div>
            <div class="stock-code">{{ s.code }}</div>
        </div>
        <div class="stock-price">
            {% if s.price %}
            <div class="price-value {% if s.change_pct > 0 %}up{% elif s.change_pct < 0 %}down{% else %}flat{% endif %}">
                {{ "%.2f"|format(s.price) }}
            </div>
            <div class="price-change {% if s.change_pct > 0 %}up{% elif s.change_pct < 0 %}down{% else %}flat{% endif %}">
                {% if s.change_pct > 0 %}+{% endif %}{{ "%.2f"|format(s.change_pct) }}%
            </div>
            {% else %}
            <div class="price-value flat">--</div>
            {% endif %}
        </div>
    </div>
    {% if s.price %}
    <div class="card-bottom">
        <div class="metric">
            <div class="metric-label">开盘</div>
            <div class="metric-value">{{ "%.2f"|format(s.open) }}</div>
        </div>
        <div class="metric">
            <div class="metric-label">最高</div>
            <div class="metric-value">{{ "%.2f"|format(s.high) }}</div>
        </div>
        <div class="metric">
            <div class="metric-label">最低</div>
            <div class="metric-value">{{ "%.2f"|format(s.low) }}</div>
        </div>
    </div>
    {% endif %}
</div>
{% endfor %}
{% else %}
<div class="empty-state">
    <div class="icon">📊</div>
    <p>今日暂无符合"周线爆发"策略的股票<br>策略会在每周交易日自动更新</p>
</div>
{% endif %}
</div>

<div class="footer">
    <p>策略自动运行 · 数据来源: 东方财富</p>
    <p style="margin-top:4px;">周线级别 · 每个交易日收盘后自动更新</p>
</div>
</body>
</html>"""

    template = Template(template_str)
    html = template.render(
        stocks=selected_stocks,
        stock_count=len(selected_stocks),
        update_time=datetime.now().strftime('%Y年%m月%d日 %H:%M 更新'),
    )

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  页面已生成: {output_path}")


def save_data_json(selected_stocks: list, output_path: str):
    """保存选股结果为JSON（供历史记录使用）"""
    data = {
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'strategy': '周线爆发',
        'count': len(selected_stocks),
        'stocks': selected_stocks,
    }
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  数据已保存: {output_path}")


if __name__ == '__main__':
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
    os.makedirs(output_dir, exist_ok=True)

    # 运行策略
    results = run_strategy()

    # 生成HTML页面
    html_path = os.path.join(output_dir, 'index.html')
    generate_html(results, html_path)

    # 保存JSON数据
    json_path = os.path.join(output_dir, 'data.json')
    save_data_json(results, json_path)

    print(f"\n{'=' * 60}")
    print(f"  完成! 共选出 {len(results)} 只股票")
    print(f"  HTML: {html_path}")
    print(f"  JSON: {json_path}")
    print(f"{'=' * 60}")
