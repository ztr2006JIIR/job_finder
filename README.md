# job-analyzer

一个简单的招聘信息分析平台 MVP，使用 Python 和 Streamlit 实现。

## 功能

- 支持上传 `jobs.csv`
- 显示岗位表格
- 支持岗位关键词搜索
- 支持城市筛选
- 支持薪资清洗，解析 `10-15K`、`15-25K·13薪`、`8千-1.2万`、`面议`
- 显示岗位总数、平均薪资、城市岗位数量 Top10、技能词频 Top20
- 支持导出筛选后的 Excel
- 支持按关键词和城市抓取前程无忧公开搜索结果，并整理成统一岗位表格

## 目录结构

```
job-analyzer/
├─ app.py
├─ data/
│  └─ sample_jobs.csv
├─ src/
│  ├─ data_loader.py
│  ├─ cleaner.py
│  ├─ analyzer.py
│  ├─ crawler_51job.py
│  └─ exporter.py
├─ requirements.txt
└─ README.md
```

## 运行方式

1. 安装依赖：

```bash
pip install -r requirements.txt
playwright install chromium
```

2. 运行 Streamlit：

```bash
streamlit run app.py
```

3. 打开浏览器访问提示页，上传自己的 `jobs.csv` 或使用示例数据。

## 前程无忧抓取说明

页面中选择“实时抓取前程无忧”，输入岗位关键词、城市和每次抓取页数后即可抓取公开搜索结果。可以点击“立即抓取”，也可以打开“自动抓取”，按 10 秒、30 秒或 60 秒周期自动更新。

实时抓取结果会保存到 `data/live_51job_jobs.csv`，页面刷新或重启后会继续加载这份数据，并按岗位链接去重。抓取结果会整理为：

```csv
title,company,city,salary,tags,description,source,url,fetched_at
```

如果前程无忧触发访问防护，抓取器会自动切换到 Playwright 浏览器模式。后续接入 AI 推荐时，可以直接复用这套统一字段。
抓取器会先尝试前程无忧搜索接口；如果接口被拦截或没有数据，会自动切换到 Playwright 浏览器模式，从已渲染页面和搜索接口响应中整理岗位。

## 示例数据说明

`data/sample_jobs.csv` 包含 50 条中文示例招聘数据，用于快速体验平台功能。
