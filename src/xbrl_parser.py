import glob
import os
import re
import zipfile

import pandas as pd

from arelle import Cntlr, ModelManager, ModelValue
from edinetcd_info import get_edinetcd_info, EDINETCD_COL

EDINET_ROOT_DIR = "D:\\EDINET\\test"
EDINET_XBRL_REGREX = "*\\XBRL\\PublicDoc\\*.xbrl"
OUTPUT_FILE_NAME = "yuho.csv"
# EdinetcodeDlInfo.csv から取得する列
# 必須項目: https://disclosure.edinet-fsa.go.jp/download/ESE140119.pdf 参照
EDINETCDDLINFO_COLS = [
    EDINETCD_COL,
    "提出者業種",
    "上場区分",
    "提出者種別",
    "提出者名"
]
# 有価証券報告書から取得する列
HAS_CONSOLIDATED_ELM_NAME = "WhetherConsolidatedFinancialStatementsArePreparedDEI"
YUHO_COLS_DICT = {
    "jpdei_cor": {
        HAS_CONSOLIDATED_ELM_NAME: "連結決算の有無",
        "EDINETCodeDEI": EDINETCD_COL,
        "AccountingStandardsDEI": "会計基準",
        "SecurityCodeDEI": "証券コード",
        "FilerNameInJapaneseDEI": "提出者名_有報",
        "CurrentPeriodEndDateDEI": "当会計期間終了日",
        "CurrentFiscalYearEndDateDEI": "当事業年度終了日"
    },
    "jppfs_cor": {
        "Assets": "資産",
        "CurrentAssets": "流動資産",
        "PropertyPlantAndEquipment": "有形固定資産",
        "IntangibleAssets": "無形固定資産",
        "InvestmentsAndOtherAssets": "投資その他の資産",
        "NoncurrentAssets": "固定資産",
        "DeferredAssets": "繰延資産",
        "Liabilities": "負債",
        "CurrentLiabilities": "流動負債",
        "NoncurrentLiabilities": "固定負債",
        "NetAssets": "純資産",
        "LiabilitiesAndNetAssets": "負債純資産",
        "NetSales": "売上高",
        "GrossProfit": "売上総利益又は売上総損失（△）",
        "OperatingIncome": "営業利益又は営業損失（△）",
        "OrdinaryIncome": "経常利益又は経常損失（△）",
        "IncomeBeforeIncomeTaxes": "税引前当期純利益又は税引前当期純損失（△）",
        "ProfitLoss": "当期純利益又は当期純損失（△）",
        "ComprehensiveIncome": "包括利益",
        "NetCashProvidedByUsedInOperatingActivities": "営業活動によるキャッシュ・フロー",
        "NetCashProvidedByUsedInInvestmentActivities": "投資活動によるキャッシュ・フロー",
        "NetCashProvidedByUsedInFinancingActivities": "財務活動によるキャッシュ・フロー",
        "CashAndCashEquivalents": "現金及び現金同等物の残高"
    }
}
# データフレームに追加する列
CONSOLIDATED_OR_NONCONSOLIDATED_COL = "連結/個別"


def extract_files_from_zip(zip_dir):
    """zipファイルから必要なファイルを抽出する"""

    unzip_tgt_regrep = "|".join(
        [f"XBRL/PublicDoc/.*\.{extension}" for extension in ["xbrl", "xsd", "xml"]]
    )
    zip_files = glob.glob(os.path.join(zip_dir, '*.zip'))
    zip_file_num = len(zip_files)
    for index, zip_file in enumerate(zip_files):
        zfile_name = os.path.splitext(os.path.basename(zip_file))[0]
        print(f"{zfile_name}: {index + 1} / {zip_file_num}")
        with zipfile.ZipFile(zip_file) as zf:
            tgt_files_namelist = []
            for filename in zf.namelist():
                if re.findall(unzip_tgt_regrep, filename):
                    tgt_files_namelist.append(filename)
            zf.extractall(
                path=os.path.join(EDINET_ROOT_DIR, zfile_name),
                members=tgt_files_namelist
            )
            zf.close()


def get_tgt_data(model_xbrl, yuho_cols, is_consolidated, has_consolidated):
    """有価証券報告書から取得対象の項目を取得する"""

    ser_yuho = pd.Series([None for i in range(
        len(yuho_cols))], dtype="object", index=yuho_cols)
    ser_yuho[CONSOLIDATED_OR_NONCONSOLIDATED_COL] = "連結" if is_consolidated else "個別"
    ser_yuho[HAS_CONSOLIDATED_ELM_NAME] = has_consolidated
    # 【忘備】: 有価証券報告書xbrlから必要情報抽出（総なめしない）
    # 1. ModelXbrlクラスのfactsByQname属性（辞書型）に すべてのfactが格納されている
    # 2. 1のキーはQnameクラスオブジェクト。Prefix:要素名の文字列からQname型オブジェクトを作成するために、ModelValue.py の qname関数を使用
    # 3. 2のvalue指定に名前空間uriが必要。ModelXbrlクラスのprefixedNamespaces属性（辞書型）から取得。
    for qname_prefix, localnames in YUHO_COLS_DICT.items():
        print("qname_prefix: ", qname_prefix)
        ns = model_xbrl.prefixedNamespaces[qname_prefix]
        for localname in localnames:
            facts = model_xbrl.factsByQname[ModelValue.qname(
                ns, name=f"{qname_prefix}:{localname}")]
            if not facts:
                ser_yuho[localname] = None
            elif qname_prefix == "jpdei_cor":
                ser_yuho[localname] = list(facts)[0].value
            elif qname_prefix == "jppfs_cor":
                for fact in facts:
                    if fact.context.isStartEndPeriod:
                        # 期間型勘定科目
                        tgt_contextid = "CurrentYearDuration" if is_consolidated \
                            else "CurrentYearDuration_NonConsolidatedMember"
                    elif fact.context.isInstantPeriod:
                        # 時点型勘定科目
                        tgt_contextid = "CurrentYearInstant" if is_consolidated \
                            else "CurrentYearInstant_NonConsolidatedMember"
                    else:
                        continue
                    if fact.contextID == tgt_contextid:
                        ser_yuho[localname] = fact.value
                        ser_yuho[f"{fact.localName}_unitid"] = fact.unitID
                        break
        # TODO: lxmlのfindメソッドのように見つけられないのか？下記は総なめパターン →　上で改善した
        '''
        for fact in model_xbrl.facts:
            for qname_prefix in YUHO_COLS_DICT.keys():
                if fact.prefix == qname_prefix:
                    if fact.localName in YUHO_COLS_DICT[qname_prefix].keys():
                        ser_yuho[fact.localName] = fact.value
                        if qname_prefix == "jppfs_cor":
                            ser_yuho[f"{fact.localName}_unitid"] = fact.unitID
                        break
        '''
    return ser_yuho


def get_yuho_data(xbrl_files, df_edinetcd_info):
    """有価証券報告書の対象項目を取得し、会社情報を追加する"""

    # 格納用のデータフレームを用意
    yuho_cols = [CONSOLIDATED_OR_NONCONSOLIDATED_COL]
    for key_level1, vals_level1 in YUHO_COLS_DICT.items():
        for key in vals_level1.keys():
            yuho_cols.append(key)
            if key_level1 == "jppfs_cor":
                yuho_cols.append(f"{key}_unitid")
    df_yuho = pd.DataFrame([], columns=yuho_cols)
    df_row = 0
    # 有価証券報告書から対象項目を取得
    for index, xbrl_file in enumerate(xbrl_files):
        print(xbrl_file, ":", index + 1, "/", len(xbrl_files))
        ctrl = Cntlr.Cntlr()
        model_manager = ModelManager.initialize(ctrl)
        print("model_manager.defaultLang: ", model_manager.defaultLang)
        model_xbrl = model_manager.load(xbrl_file)
        # 連結財務諸表ありかどうか
        ns = model_xbrl.prefixedNamespaces["jpdei_cor"]
        facts_has_consolidated = model_xbrl.factsByQname[ModelValue.qname(
            ns, name=f"jpdei_cor:{HAS_CONSOLIDATED_ELM_NAME}")]
        if list(facts_has_consolidated)[0].value == "true":
            has_consolidated = True
        elif list(facts_has_consolidated)[0].value == "false":
            has_consolidated = False
        else:
            print("連結決算の有無の項目の値が想定外です。")
            print(f"該当ファイル: {xbrl_file}")
        # 個別財務諸表はデフォルトで取得
        is_consolidated_list = [False]
        # 連結財務諸表ありの場合、追加
        if has_consolidated:
            is_consolidated_list.append(True)
        for is_consolidated in is_consolidated_list:
            ser_yuho = get_tgt_data(
                model_xbrl, yuho_cols, is_consolidated, has_consolidated)
            ser_yuho.name = df_row
            df_yuho = df_yuho.append(ser_yuho)
            df_row += 1
    # カラム名を日本語に変換
    yuho_cols_rep = {
        key: val
        for val_level1 in YUHO_COLS_DICT.values()
        for key, val in val_level1.items()
    }
    df_yuho.rename(columns=yuho_cols_rep, inplace=True)
    # 企業情報をマージ
    df_yuho = df_yuho.merge(df_edinetcd_info, on=EDINETCD_COL, how="left")
    return df_yuho


def main():
    # EDINETコードリストから企業情報を取得
    df_edinetcd_info = get_edinetcd_info(EDINETCDDLINFO_COLS)
    # EDINETからダウンロードしたZIPファイルから必要なファイルを抽出
    # '''★★テストのため無効中
    edinet_zip_dir = os.path.join(EDINET_ROOT_DIR, "zip")
    extract_files_from_zip(edinet_zip_dir)
    # '''
    xbrl_file_regrex = os.path.join(EDINET_ROOT_DIR, EDINET_XBRL_REGREX)
    xbrl_files = glob.glob(xbrl_file_regrex)
    # 有価証券報告書の情報を取得する
    df_yuho = get_yuho_data(xbrl_files, df_edinetcd_info)

    df_yuho.to_csv(
        os.path.join(EDINET_ROOT_DIR, OUTPUT_FILE_NAME),
        index=False,
        encoding="cp932"
    )
    print(f"{'-'*10} 情報抽出　完了 {'-'*10}")


if __name__ == "__main__":
    main()
