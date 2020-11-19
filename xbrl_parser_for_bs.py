"""
Arelleを使ったサンプルコード４
有価証券報告書からDEIと貸借対照表の第一階層の勘定科目の値を取得する
（表示リンクの利用）

【備考】
- このスクリプトについて
  - 会計基準 = 日本基準の書類のみ対象としている
  - EDINETの仕様を利用した処理を含んでいる
"""

import glob
import os
import sys

import pandas as pd

from arelle import Cntlr, ModelManager, XbrlConst
from arelle.ModelValue import qname
from edinetcd_info import get_edinetcd_info
from utils import extract_files_from_zip

# パス関連
EDINET_ROOT_DIR = "D:\\EDINET\\120_yuho_test"
EDINET_XBRL_REGREX = "*\\XBRL\\PublicDoc\\*.xbrl"
OUTPUT_FILE_NAME = "120_yuho_test_bs.csv"

# EDINETからダウンロードしたXBRLを含むzipファイルが解凍済かどうか
IS_EXTRACTED = True

# ----- 財務情報XBRLから取得する内容 -----
# 会計基準を示す要素
ACCOUNTING_STD_ELM_NAME = "AccountingStandardsDEI"
# EDINETコードを示す要素
EDINET_CD_ELM_NAME = "EDINETCodeDEI"
# 連結有無を示す要素
HAS_CONSOLIDATED_ELM_NAME = "WhetherConsolidatedFinancialStatementsArePreparedDEI"
# 当会計期間の種類を示す要素
TYPE_OF_PERIOD_ELM_NAME = "TypeOfCurrentPeriodDEI"

# 取得対象のDEI（会社・書類情報）
# - 以下の項目は全企業登録必須のため、Qname（名前空間:要素名）指定で取得する
#   - 必須項目について
#     - EDINETバリデーションガイドライン: DEI 必須項目　参照
#   - 要素名について
#     - タクソノミ要素リスト: DEI  (jpdei)　参照
DEI_COLS = [
    ACCOUNTING_STD_ELM_NAME,
    EDINET_CD_ELM_NAME,
    HAS_CONSOLIDATED_ELM_NAME,
    "SecurityCodeDEI",
    "FilerNameInJapaneseDEI",
    "CurrentFiscalYearStartDateDEI",
    TYPE_OF_PERIOD_ELM_NAME,
    "CurrentPeriodEndDateDEI"
]
# 【備考】財務諸表本表の項目は企業ごとに項目が異なるため、
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

# ----- アウトプットに列名指定で設定する列 -----
CONSOLIDATED_OR_NONCONSOLIDATED_COL = "連結/個別"


def get_bs_facts(model_xbrl, is_consolidated, type_of_period):
    """XBRLデータから貸借対照表の第一階層の勘定科目の値を取得する"""

    qname_prefix = "jppfs_cor"
    ns = model_xbrl.prefixedNamespaces[qname_prefix]
    dict_facts = {}

    # 当会計期間の種類の値により異なるアークロール名に埋め込む文字列
    # TODO: EDINET仕様書で会計期間によるアークロールIDの違いの明記部分を確認する（下記top_str_for_linkroleは実データより）
    # 年度（有価証券報告書）
    if type_of_period == "FY":
        top_str_for_linkrole = ""
        top_str_for_contextid = "CurrentYear"
    # 中間期（半期報告書）
    elif type_of_period == "HY":
        top_str_for_linkrole = "SemiAnnual"
        top_str_for_contextid = "Interim"
    # 四半期（四半期報告書）
    elif type_of_period in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        top_str_for_linkrole = "Quarterly"
        top_str_for_contextid = "CurrentQuarter"
    else:
        print("当会計期間の種類の項目の値が想定外です。確認してください。")
        print("この文書の貸借対照表のデータは取得しません。")
        return None
    # 表示の親子関係を表すリレーションシップを取得
    # linkrole=で対象のリンクロールに絞り込み
    if is_consolidated:
        link_role = f"http://disclosure.edinet-fsa.go.jp/role/jppfs/rol_{top_str_for_linkrole}ConsolidatedBalanceSheet"
    else:
        link_role = f"http://disclosure.edinet-fsa.go.jp/role/jppfs/rol_{top_str_for_linkrole}BalanceSheet"
    pc_rel_set = model_xbrl.relationshipSet(
        XbrlConst.parentChild,
        linkrole=link_role
    )
    # 貸借対照表のLineItemsを親とする表示リレーションシップを抽出
    qname_from = qname(ns, name=f"{qname_prefix}:BalanceSheetLineItems")
    rel_from_tgt_list = pc_rel_set.fromModelObject(
        model_xbrl.qnameConcepts.get(qname_from))
    # 連結四半期財務諸表を提出する場合個別四半期財務諸表の提出は要しないとされているため
    # 四半期の場合の個別はないことが多い
    if not rel_from_tgt_list:
        print("指定したアークロールの表示リレーションシップはありませんでした。")
        print(f"指定アークロール: {link_role}")
        return None

    for rel_from_tgt in rel_from_tgt_list:
        mcpt_to = rel_from_tgt.toModelObject

        # 【備考】：abstract == True の場合、タイトル項目なので金額情報なし。
        # その表示子要素の内、合計金額を表す要素のfactを取得する
        # 1. タイトル項目をfrom(親)とする表示リレーションシップを取得
        # 2. 1のリレーションシップの内、一番最後のリレーションシップのto(子)のfactを取得する
        if mcpt_to.isAbstract:
            pc_rels_from_tgt = pc_rel_set.fromModelObject(mcpt_to)
            # 【備考】：タイトル項目のfactに子が存在しないケースがあった。
            # （表示リンク・定義リンク共に）該当項目を親とする関係が定義されておらず
            # 該当項目と同階層に該当項目の内訳が定義されていた。
            # 関係が正しく定義されていないため、当スクリプトでは処理対象から除外する
            if not pc_rels_from_tgt:
                print(f"{mcpt_to.qname.localName} に子が存在しない")
                return None
            mcpt_to = pc_rels_from_tgt[-1].toModelObject
        
        # fact を取得
        # 【備考】1つの要素に対し、コンテキスト・ユニットの異なる複数のfactが存在し得る
        # - コンテキストID
        #   報告書インスタンス作成ガイドライン：5-4-5 コンテキストの設定例　参照
        # 　【注意】有報では時点型／期間型どちらも当期を表す接頭辞はCurrentYearで同じだが
        # 　　　　　四半期報告書は時点型はCurrentQuarter、期間型はCurrentQuarterとCurrentYTD(累積)がある
        # 貸借対照表は対象期末（対象期間終了日）時点の状態を表すので勘定科目は時点型(一応periodTypeを取得)
        # EDINET勘定科目リスト　参照
        contextid = f"{top_str_for_contextid}{mcpt_to.periodType.capitalize()}"
        if not is_consolidated:
            contextid += "_NonConsolidatedMember"
        localname = mcpt_to.qname.localName
        facts = model_xbrl.factsByQname[qname(
            ns, name=f"{qname_prefix}:{localname}")]
        for fact in facts:
            # 当年度の財務情報かつユニットが日本円のfactを取得する
            if (fact.contextID == contextid) and (fact.unitID == "JPY"):
                dict_facts[mcpt_to.label()] = fact.value
                break

    return dict_facts


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
                return None, None
        if localname == EDINET_CD_ELM_NAME:
            dict_facts[EDINETCD_COL] = fact.value
        else:
            dict_facts[fact.concept.label()] = fact.value
        if localname == HAS_CONSOLIDATED_ELM_NAME:
            if fact.value == "true":
                has_consolidated = True
            elif fact.value == "false":
                has_consolidated = False
            else:
                print("連結決算の有無の項目の値が想定外です。")
                print("無しとして処理を続行しますが、該当ファイルを確認してください。")
                print(f"想定: 'true' or 'false'  データ: {fact.value}")
                has_consolidated = False
        if localname == TYPE_OF_PERIOD_ELM_NAME:
            type_of_period = fact.value

    return dict_facts, has_consolidated, type_of_period


def get_facts(model_manager, xbrl_file):
    """有価証券報告書から情報を取得する"""

    model_xbrl = model_manager.load(xbrl_file)
    # 会社・書類情報を取得
    dict_facts_dei, has_consolidated, type_of_period = get_dei_facts(
        model_xbrl)
    if dict_facts_dei is None:
        return None
    # 貸借対照表の情報を取得
    # 非連結または個別財務諸表はデフォルトで取得、連結ありの場合追加
    list_is_consolidated = [False]
    if has_consolidated:
        list_is_consolidated.append(True)
    list_dict_facts = []
    for is_consolidated in list_is_consolidated:
        dict_facts_bs = get_bs_facts(
            model_xbrl, is_consolidated, type_of_period)
        if dict_facts_bs is None:
            continue
        dict_facts_bs[CONSOLIDATED_OR_NONCONSOLIDATED_COL] \
            = "連結" if is_consolidated else "個別／非連結"
        list_dict_facts.append({**dict_facts_dei, **dict_facts_bs})

    model_manager.close()
    return list_dict_facts


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
    list_dict_facts = []
    ctrl = Cntlr.Cntlr()
    model_manager = ModelManager.initialize(ctrl)
    for index, xbrl_file in enumerate(xbrl_files):
        print(xbrl_file, ":", index + 1, "/", len(xbrl_files))
        list_dict_facts_per_file = get_facts(model_manager, xbrl_file)
        if list_dict_facts_per_file is not None:
            list_dict_facts = list_dict_facts + list_dict_facts_per_file
    if list_dict_facts:
        df_yuho = pd.DataFrame(list_dict_facts)
        df_yuho.to_csv(
            os.path.join(EDINET_ROOT_DIR, OUTPUT_FILE_NAME),
            index=False,
            encoding="cp932"
        )
        print(f"{'-'*10} 情報抽出　完了 {'-'*10}")
    else:
        print("処理対象のデータはありませんでした。")


if __name__ == "__main__":
    main()
