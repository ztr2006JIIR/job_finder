import json
from json import JSONDecodeError

import pandas as pd


DEFAULT_BASE_URL = "https://api.gptsapi.net/v1"
DEFAULT_MODEL = "gpt-4o"


class AIRecommendationError(Exception):
    """AI 推荐过程中的可展示错误。"""


def prepare_job_candidates(df, limit=20):
    """从岗位 DataFrame 中整理给 AI 使用的候选岗位。"""
    if df is None or df.empty:
        return []

    safe_df = df.head(limit).copy()
    candidates = []
    for index, row in safe_df.iterrows():
        candidates.append(
            {
                "candidate_id": int(index),
                "title": _clean(row.get("title")),
                "company": _clean(row.get("company")),
                "city": _clean(row.get("city")),
                "salary": _clean(row.get("salary")),
                "salary_avg": _clean(row.get("salary_avg")),
                "tags": _clean(row.get("tags")),
                "description": _clean(row.get("description"), max_length=500),
                "url": _clean(row.get("url")),
            }
        )
    return candidates


def recommend_jobs_with_ai(
    api_key,
    user_profile,
    jobs,
    base_url=DEFAULT_BASE_URL,
    model=DEFAULT_MODEL,
):
    """调用 OpenAI 兼容接口，返回结构化岗位推荐。"""
    if not api_key:
        raise AIRecommendationError("缺少 API key，请先配置 .streamlit/secrets.toml。")
    if not user_profile:
        raise AIRecommendationError("请先填写求职者需求。")
    if not jobs:
        raise AIRecommendationError("当前没有可用于推荐的岗位。")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise AIRecommendationError("缺少 openai 依赖，请先安装 requirements.txt。") from error

    client = OpenAI(api_key=api_key, base_url=base_url)
    prompt = _build_prompt(user_profile, jobs)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个严谨的中文求职顾问。你只能基于用户提供的候选岗位做推荐，"
                        "不能编造不存在的岗位、公司或链接。请优先考虑技能匹配、城市、薪资、"
                        "岗位描述和风险点。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
    except Exception as error:
        raise AIRecommendationError(f"AI API 调用失败：{error}") from error

    raw_text = response.choices[0].message.content if response.choices else ""
    return parse_recommendation_response(raw_text)


def parse_recommendation_response(raw_text):
    """解析模型返回的 JSON，失败时保留原始文本。"""
    text = (raw_text or "").strip()
    if not text:
        raise AIRecommendationError("AI 没有返回内容。")

    json_text = _extract_json(text)
    try:
        data = json.loads(json_text)
    except JSONDecodeError:
        return {
            "recommendations": [],
            "overall_advice": "",
            "raw_text": text,
            "parse_error": "AI 返回内容不是有效 JSON，已显示原始回答。",
        }

    recommendations = data.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []

    return {
        "recommendations": recommendations,
        "overall_advice": _clean(data.get("overall_advice")),
        "raw_text": text,
        "parse_error": "",
    }


def recommendations_to_dataframe(result):
    """将推荐结果转换为页面表格。"""
    rows = []
    for item in result.get("recommendations", []):
        rows.append(
            {
                "排名": item.get("rank"),
                "岗位名称": item.get("title"),
                "公司": item.get("company"),
                "匹配分": item.get("match_score"),
                "推荐理由": item.get("match_reason"),
                "风险点": item.get("risk_points"),
                "建议行动": item.get("suggested_action"),
                "岗位链接": item.get("url"),
            }
        )
    return pd.DataFrame(rows)


def _build_prompt(user_profile, jobs):
    return (
        "请根据求职者需求，从候选岗位中选出最合适的 5 个岗位，并返回严格 JSON。\n\n"
        f"求职者需求：\n{json.dumps(user_profile, ensure_ascii=False, indent=2)}\n\n"
        f"候选岗位：\n{json.dumps(jobs, ensure_ascii=False, indent=2)}\n\n"
        "返回格式必须是：\n"
        "{\n"
        '  "recommendations": [\n'
        "    {\n"
        '      "rank": 1,\n'
        '      "title": "岗位名称",\n'
        '      "company": "公司名称",\n'
        '      "match_score": 0,\n'
        '      "match_reason": "为什么匹配",\n'
        '      "risk_points": "需要注意的风险",\n'
        '      "suggested_action": "建议求职者下一步怎么做",\n'
        '      "url": "候选岗位原始链接"\n'
        "    }\n"
        "  ],\n"
        '  "overall_advice": "整体求职建议"\n'
        "}\n"
        "要求：match_score 为 0 到 100 的整数；必须使用候选岗位中的 title/company/url；"
        "用中文输出；不要输出 Markdown。"
    )


def _extract_json(text):
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _clean(value, max_length=None):
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if max_length and len(text) > max_length:
        return text[:max_length] + "..."
    return text
