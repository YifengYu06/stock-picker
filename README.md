# 周线爆发选股

基于布林带扩张 + 放量 + MACD零轴上方金叉的A股周线级别量化选股策略。

## 策略逻辑

- **BOLL扩张**: 布林带上轨上升、中轨上升、下轨下降
- **放量**: 26周内存在单周成交量超过前周4倍
- **MACD金叉**: 3周内DIF上穿DEA且DEA在零轴上方

## 部署

1. Fork 本仓库
2. 在仓库 Settings → Pages 中选择 GitHub Actions 作为 Source
3. 手动运行一次 Actions 或等待每周五自动运行
4. 访问 `https://你的用户名.github.io/stock-picker/` 查看结果

## 本地运行

```bash
pip install -r requirements.txt
python strategy.py
```

生成的页面在 `docs/index.html`。
