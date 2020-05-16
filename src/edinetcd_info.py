import pandas as pd

EDINETCD_INFO_PATH = "D:\\EDINET\\Edinetcode_20200413\\EdinetcodeDlInfo.csv"
EDINETCD_COL = "ＥＤＩＮＥＴコード"


def get_edinetcd_info(use_cols):
    """EDINETコードリストから企業情報を取得する"""

    df_edinetcd_info = pd.read_csv(
        EDINETCD_INFO_PATH,
        skiprows=1,
        usecols=use_cols,
        encoding='cp932'
    )
    return df_edinetcd_info
