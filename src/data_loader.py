import pandas as pd


def load_jobs(source):
    """加载招聘 CSV 数据，并返回 DataFrame。"""
    try:
        df = pd.read_csv(source)
        return df
    except Exception as error:
        print(f"加载数据时发生错误：{error}")
        return pd.DataFrame()
