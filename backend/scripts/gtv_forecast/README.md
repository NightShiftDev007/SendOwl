# GTV 成交推演试点（离线）

对应设计文档：`docs/gtv-deal-forecast.md`。

**不修改**决策中心五步流程 / OASIS；代码与派生数据隔离在本目录。

## 运行

```bash
cd backend
# 依赖：pandas duckdb pyarrow scikit-learn（已在 .venv 中安装）
.venv/bin/python -m scripts.gtv_forecast run
```

分步：`import` → `labels` → `gate` → `backtest`。

环境变量：`GTV_DATA_ROOT` 可覆盖 dump 根目录（默认 `/Users/ssyb/Downloads/data/lyy_manage`）。

## 产物

- `_data/parquet/`：脱敏表与标签/样本
- `_data/reports/`：门禁、回测指标、三榜、`demo_report.md`
- `data_dictionary.md`：ER 与字段说明

`_data/` 已 gitignore，勿提交原始 SQL dump。
