"""
Arelleを使ったサンプルコード３
XBRL形式のデータを階層構造で出力する
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

# 取得対象のリンクロール
#TGT_LINK_ROLE = None #リンクロール指定しない
TGT_LINK_ROLE = "http://disclosure.edinet-fsa.go.jp/role/jpcrp/rol_BusinessResultsOfReportingCompany"

# EDINETからダウンロードしたXBRLを含むzipファイルが解凍済かどうか
IS_EXTRACTED = True


def export_facts(model_manager, xbrl_file):
    """XBRLデータを階層構造で出力する"""

    model_xbrl = model_manager.load(xbrl_file)
    filename = re.search(r'E\d+', os.path.split(xbrl_file)[1]).group()
    ViewFileFactTable.viewFacts(
        model_xbrl,
        os.path.join(EDINET_ROOT_DIR, OUTPUT_FILE_NAME.format(fname=filename)),
        linkrole=TGT_LINK_ROLE
    )
    model_manager.close()


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
    ctrl = Cntlr.Cntlr()
    model_manager = ModelManager.initialize(ctrl)
    for index, xbrl_file in enumerate(xbrl_files):
        print(xbrl_file, ":", index + 1, "/", len(xbrl_files))
        export_facts(model_manager, xbrl_file)

    print(f"{'-'*10} XBRL出力　完了 {'-'*10}")


if __name__ == "__main__":
    main()
