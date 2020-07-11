import pandas as pd

EDINETCD_INFO_PATH = "D:\\EDINET\\Edinetcode_20200413\\EdinetcodeDlInfo.csv"
EDINETCD_COL = "ＥＤＩＮＥＴコード"

# EdinetcodeDlInfo.csv から取得する列
# 必須項目: https://disclosure.edinet-fsa.go.jp/download/ESE140119.pdf 参照
EDINETCDDLINFO_COLS = [
    EDINETCD_COL,
    "提出者業種",
    "上場区分",
    "提出者種別",
    "提出者名"
]

def get_edinetcd_info(use_cols):
    """EDINETコードリストから企業情報を取得する"""

    df_edinetcd_info = pd.read_csv(
        EDINETCD_INFO_PATH,
        skiprows=1,
        usecols=use_cols,
        encoding='cp932'
    )
    return df_edinetcd_info
