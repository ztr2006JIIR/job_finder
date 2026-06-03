import re


def parse_salary(salary_text):
    """解析中文薪资字符串，返回平均月薪数字。"""
    if not isinstance(salary_text, str):
        return None
    text = salary_text.strip().replace("，", ",")
    if text in ["面议", "面议", "negotiable"]:
        return None

    # 处理带 13 薪、12 薪等情况
    extra_months = 12
    if "13薪" in text:
        extra_months = 13
        text = text.replace("·13薪", "").replace("13薪", "")
    elif "14薪" in text:
        extra_months = 14
        text = text.replace("·14薪", "").replace("14薪", "")
    elif "12薪" in text:
        extra_months = 12
        text = text.replace("·12薪", "").replace("12薪", "")

    text = text.replace("千", "k").replace("K", "k").replace("万", "w").replace("元", "")
    text = text.replace("-", "-").replace("至", "-")
    text = re.sub(r"\s+", "", text)

    pattern = r"([0-9]+\.?[0-9]*)([kw]?)\s*-\s*([0-9]+\.?[0-9]*)([kw]?)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        low, low_unit, high, high_unit = match.groups()
        low_unit = (low_unit or high_unit).lower()
        high_unit = (high_unit or low_unit).lower()
        low = float(low)
        high = float(high)
        low = low * 1000 if low_unit == "k" else low * 10000 if low_unit == "w" else low
        high = high * 1000 if high_unit == "k" else high * 10000 if high_unit == "w" else high
        avg = (low + high) / 2
        return avg * extra_months / 12

    pattern_single = r"([0-9]+\.?[0-9]*)([kw]?)"
    match_single = re.search(pattern_single, text, re.IGNORECASE)
    if match_single:
        value, unit = match_single.groups()
        value = float(value)
        return value * 1000 if unit == "k" else value * 10000 if unit == "w" else value

    return None


def clean_salary_column(df, salary_col="salary"):
    """对 DataFrame 的薪资列进行清洗，生成标准化薪资列。"""
    df = df.copy()
    df["salary_min"] = None
    df["salary_max"] = None
    df["salary_avg"] = None

    for index, value in df[salary_col].items():
        avg = parse_salary(value)
        df.at[index, "salary_avg"] = avg
        if isinstance(value, str):
            text = value.replace("，", ",").replace("至", "-")
            pattern = r"([0-9]+\.?[0-9]*)([kw]?)\s*-\s*([0-9]+\.?[0-9]*)([kw]?)"
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                low, low_unit, high, high_unit = match.groups()
                low_unit = (low_unit or high_unit).lower()
                high_unit = (high_unit or low_unit).lower()
                low = float(low)
                high = float(high)
                low = low * 1000 if low_unit == "k" else low * 10000 if low_unit == "w" else low
                high = high * 1000 if high_unit == "k" else high * 10000 if high_unit == "w" else high
                df.at[index, "salary_min"] = low
                df.at[index, "salary_max"] = high
    return df
