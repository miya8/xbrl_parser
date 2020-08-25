"""
Arelleを使ったサンプルコード２
Dimensionを利用し、セグメント情報を取得する

【備考】
- セグメント利益の項目は、企業により報告している利益の種類が異なる
  - （売上総利益、経常利益、など）
- 同様の項目でも企業により項目名が異なる
  - （売上、営業収益など）
- このスクリプトについて
  - 会計基準 = 日本基準の書類のみ対象としている
  - EDINETの仕様を利用した処理を含んでいる
"""

import glob
import os
import re
import sys
import zipfile

import pandas as pd

from arelle import Cntlr, ModelManager, XbrlConst
from arelle.ModelValue import qname
from edinetcd_info import get_edinetcd_info
from utils import extract_files_from_zip

# パス関連
EDINET_ROOT_DIR = "D:\\EDINET\\140_qr_test"
EDINET_XBRL_REGREX = "*\\XBRL\\PublicDoc\\*.xbrl"
OUTPUT_FILE_NAME = "qr_segment_info.csv"

# 様式指定
TGT_DOC_TYPE = "第四号の三様式"

# EDINETからダウンロードしたXBRLを含むzipファイルが解凍済かどうか
IS_EXTRACTED = True

# ----- 財務情報XBRLから取得する内容 -----
# 会計基準を示す要素
ACCOUNTING_STD_ELM_NAME = "AccountingStandardsDEI"
# EDINETコードを示す要素
EDINET_CD_ELM_NAME = "EDINETCodeDEI"
# 連結有無を示す要素
HAS_CONSOLIDATED_ELM_NAME = "WhetherConsolidatedFinancialStatementsArePreparedDEI"
# 提出書類の様式を示す要素
DOC_TYPE_ELM_NAME = "DocumentTypeDEI"

# 取得対象のDEI（会社・書類情報）
# - 今回欲しい以下の項目は全企業登録必須のため、Qname（名前空間:要素名）指定で取得する
#   - 必須項目について
#     - EDINETバリデーションガイドライン: DEI 必須項目　参照
#   - 要素名について
#     - タクソノミ要素リスト: DEI  (jpdei)　参照
DEI_COLS = [
    ACCOUNTING_STD_ELM_NAME,
    DOC_TYPE_ELM_NAME,
    EDINET_CD_ELM_NAME,
    HAS_CONSOLIDATED_ELM_NAME,
    "SecurityCodeDEI",
    "FilerNameInJapaneseDEI",
    "CurrentPeriodEndDateDEI",
    "CurrentFiscalYearEndDateDEI"
]
# 【備考】財務諸表本表の勘定科目は企業ごとに異なるため、
# リンクベースに沿って情報を取得する

# ----- EDINETコードリストから取得する列 -----
EDINETCD_COL = "ＥＤＩＮＥＴコード"
EDINETCDDLINFO_COLS = [
    EDINETCD_COL,
    "提出者業種",
    "上場区分",
    "提出者種別",
    "提出者名"
]


def get_segments_facts(model_xbrl):
    """XBRLデータからセグメント情報を取得する"""

    qname_prefix = "jpcrp_cor"
    ns = model_xbrl.prefixedNamespaces[qname_prefix]
    dict_facts = {}

    # 【備考】factsByDimMemQnameメソッドで、
    # 指定したDimensionが設定されているfactを取得できる。
    # ここではセグメントを示すDimensionを指定する。
    tgt_dimension = qname(
        model_xbrl.prefixedNamespaces[qname_prefix],
        name=f"{qname_prefix}:OperatingSegmentsAxis"
    )
    facts_by_dim = model_xbrl.factsByDimMemQname(tgt_dimension)
    if not facts_by_dim:
        print("セグメントなし")
        return None
    for fact in facts_by_dim:
        # セグメント情報のDimensionメンバーごと・会計期間毎に1行としてデータを作成する
        # 【備考】Dimensionメンバーのラベル取得方法
        # 1. fact.context.dimValue(tgt_dimension) 
        #    - factに設定されているセグメントを示すDimensionの値
        #      （ModelDimensionValueクラスのインスタンス）を取得
        #      ここではセグメントのDimensionを扱っているので、例えば
        #     「商業施設部門」「チェーンストア部門」などセグメントの種類を示す。
        # 2. .member
        #    - ModelDimensionValueクラスのインスタンスの属性の１つで
        #      ModelConceptクラスのインスタンス
        # 3. .label()
        #    - 2に設定されているラベルを取得
        dim_mem_label = fact.context.dimValue(tgt_dimension).member.label()
        # 日本円のfactのみ取得する
        if fact.unitID == "JPY":
            fact_label = fact.concept.label()
            period = fact.context.period.stringValue
            if not dim_mem_label in dict_facts.keys():
                dict_facts[dim_mem_label] = {}
            if not period in dict_facts[dim_mem_label]:
                dict_facts[dim_mem_label][period] = {"セグメント": dim_mem_label, "会計期間": period}
            dict_facts[dim_mem_label][period][fact_label] = fact.value
    list_facts = [val_per_enddt for val_per_dim in dict_facts.values() for val_per_enddt in val_per_dim.values()]
    df_facts = pd.DataFrame(list_facts)
    df_facts.sort_values(by="会計期間", inplace=True)

    return df_facts


def get_dei_facts(model_xbrl):
    """XBRLデータから会社・書類情報を取得する"""

    qname_prefix = "jpdei_cor"
    ns = model_xbrl.prefixedNamespaces[qname_prefix]
    dict_facts = {}

    # 【備考】: Qname指定でfactを取得
    # ModelXbrlクラスのインスタンスのfactsBy*属性（辞書型）にfactが格納されている。
    # このうち、QnameをキーとするfactsByQnameを使用する。
    # 但し、factsByQnameのキーはQname文字列ではなく、Qnameクラスのインスタンス。
    # 文字列からQnameインスタンスを作成するために、qname関数を使用する。
    for localname in DEI_COLS:
        facts = model_xbrl.factsByQname[qname(
            ns, name=f"{qname_prefix}:{localname}")]
        if (not facts) or (len(facts) > 1):
            print(f"【想定外】1つのXBRL内に{qname_prefix}:{localname}のfactが複数存在します。")
            sys.exit()
        fact = list(facts)[0]
        if localname == ACCOUNTING_STD_ELM_NAME:
            if fact.value != "Japan GAAP":
                print(f"会計基準: {fact.value}　処理対象外")
                return None
        if localname == DOC_TYPE_ELM_NAME:
            if fact.value != TGT_DOC_TYPE:
                print(f"提出書類の様式: {fact.value}　処理対象外")
                return None
        if localname == EDINET_CD_ELM_NAME:
            dict_facts[EDINETCD_COL] = fact.value
        else:
            dict_facts[fact.concept.label()] = fact.value

    return pd.DataFrame([dict_facts])


def get_facts(model_manager, xbrl_file):
    """XBRL形式のデータから情報を取得する"""

    model_xbrl = model_manager.load(xbrl_file)

    # 会社・書類情報を取得
    df_facts_dei = get_dei_facts(model_xbrl)
    if df_facts_dei is None:
        return None

    # セグメント情報を取得
    df_facts_segment = get_segments_facts(model_xbrl)
    if df_facts_segment is None:
        return None

    # マージ
    df_facts_segment.loc[:, "key"] = 1
    df_facts_dei.loc[:, "key"] = 1
    df_facts = df_facts_dei.merge(df_facts_segment, on="key", how="left").drop(columns=["key"])

    model_manager.close()
    return df_facts


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
    list_df_facts = []
    ctrl = Cntlr.Cntlr()
    model_manager = ModelManager.initialize(ctrl)
    for index, xbrl_file in enumerate(xbrl_files):
        print(xbrl_file, ":", index + 1, "/", len(xbrl_files))
        df_facts = get_facts(model_manager, xbrl_file)
        if df_facts is not None:
            list_df_facts.append(df_facts)
    if list_df_facts:
        df_xbrl = pd.concat(list_df_facts, axis=0, sort=False)
        # Edinetコードリストの情報をマージ
        df_edinetcd_info = get_edinetcd_info(EDINETCDDLINFO_COLS)
        df_xbrl = df_edinetcd_info.merge(df_xbrl, on=EDINETCD_COL, how="right")
        df_xbrl.to_csv(
            os.path.join(EDINET_ROOT_DIR, OUTPUT_FILE_NAME),
            index=False,
            encoding="cp932"
        )
        print(f"{'-'*10} 情報抽出　完了 {'-'*10}")
    else:
        print("処理対象のデータはありませんでした。")


if __name__ == "__main__":
    main()
