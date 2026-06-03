import io

import pandas as pd


def export_to_excel(df):
    """将当前 DataFrame 导出为 Excel 二进制内容。"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Jobs")
    return output.getvalue()
