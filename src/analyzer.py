import pandas as pd
from collections import Counter


def get_statistics(df):
    """计算岗位总数、平均薪资和有效薪资岗位数。"""
    total_jobs = len(df)
    salary_series = pd.to_numeric(df["salary_avg"], errors="coerce").dropna()
    average_salary = float(salary_series.mean()) if not salary_series.empty else 0.0
    return {
        "total_jobs": total_jobs,
        "average_salary": average_salary,
        "salary_count": len(salary_series),
    }


def count_top_cities(df, top_n=10):
    """统计城市岗位数量，并返回 Top N。"""
    counts = df["city"].value_counts().head(top_n)
    return counts.reset_index(name="count").rename(columns={"index": "city"})


def count_skill_frequency(df, skill_col="tags", top_n=20):
    """统计技能词频，并返回 Top N。"""
    all_skills = []
    for item in df[skill_col].fillna(""):
        parts = [part.strip() for part in re_split_skills(item) if part.strip()]
        all_skills.extend(parts)
    counter = Counter(all_skills)
    top = counter.most_common(top_n)
    return pd.DataFrame(top, columns=["skill", "count"])


def re_split_skills(text):
    """按常见分隔符拆分技能标签字符串。"""
    separators = [",", ";", "|", "、", " "]
    result = [text]
    for sep in separators:
        pieces = []
        for part in result:
            pieces.extend(part.split(sep))
        result = pieces
    return result
