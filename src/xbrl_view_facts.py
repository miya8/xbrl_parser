"""
Arelleを使ったサンプルコード３
損益計算書を階層構造で出力する
"""

import glob
import os
import re
import sys

import pandas as pd

from arelle import Cntlr, ModelManager, ViewFileFactTable
from utils import extract_files_from_zip

# パス関連
EDINET_ROOT_DIR = "D:\\EDINET\\120_yuho_test"
EDINET_XBRL_REGREX = "*\\XBRL\\PublicDoc\\*.xbrl"
OUTPUT_FILE_NAME = "yuho_viewFacts_{fname}.csv"

# EDINETからダウンロードしたXBRLを含むzipファイルが解凍済かどうか
IS_EXTRACTED = True


def export_facts(xbrl_file):
    """XBRLデータを階層構造で出力する"""

    ctrl = Cntlr.Cntlr()
    model_manager = ModelManager.initialize(ctrl)
    model_xbrl = model_manager.load(xbrl_file)
    filename = re.search(r'E\d+', os.path.split(xbrl_file)[1]).group()
    ViewFileFactTable.viewFacts(
        model_xbrl,
        os.path.join(EDINET_ROOT_DIR, OUTPUT_FILE_NAME.format(fname=filename)),
        linkrole="http://disclosure.edinet-fsa.go.jp/role/jppfs/rol_StatementOfIncome"
    )


def main():
    if IS_EXTRACTED:
        pass
    else:
        edinet_zip_dir = os.path.join(EDINET_ROOT_DIR, "zip")
        extract_files_from_zip(
            edinet_zip_dir,
            dest_dir_root=EDINET_ROOT_DIR,
            unzip_members_regrep="|".join(
                [f"XBRL/PublicDoc/.*\.{extension}" for extension in ["xbrl", "xsd", "xml"]]
            )
        )
    # XBRLから情報取得
    xbrl_file_regrex = os.path.join(EDINET_ROOT_DIR, EDINET_XBRL_REGREX)
    xbrl_files = glob.glob(xbrl_file_regrex)
    for index, xbrl_file in enumerate(xbrl_files):
        print(xbrl_file, ":", index + 1, "/", len(xbrl_files))
        export_facts(xbrl_file)

    print(f"{'-'*10} XBRL出力　完了 {'-'*10}")


if __name__ == "__main__":
    main()
