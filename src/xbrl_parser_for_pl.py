import glob
import os
import re
import sys
import zipfile

import pandas as pd

from arelle import Cntlr, ModelManager, XbrlConst
from arelle.ModelValue import qname
from edinetcd_info import EDINETCD_COL, EDINETCDDLINFO_COLS, get_edinetcd_info
from utils import extract_files_from_zip

# 動作確認
IS_TEST = True

# パス関連
EDINET_ROOT_DIR = "D:\\EDINET\\test"
EDINET_XBRL_REGREX = "*\\XBRL\\PublicDoc\\*.xbrl"
OUTPUT_FILE_NAME = "yuho.csv"

# 連結有無を示す要素のローカル名
HAS_CONSOLIDATED_ELM_NAME = "WhetherConsolidatedFinancialStatementsArePreparedDEI"

# キー: 名前空間名、値: ローカル名
# - "jpdei_cor"（会社・書類情報）:
#   - 今回欲しい以下の項目は全企業登録必須のため、qname指定で取得する
#     - EDINETバリデーションガイドライン: DEI 必須項目　参照
# - "jppfs_cor"（財務諸表本表）:
#   - 企業ごとに項目が異なるため、リンクベースに沿って情報を取得する
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
    "jppfs_cor": {}
}

# アウトプットに追加する列
CONSOLIDATED_OR_NONCONSOLIDATED_COL = "連結/個別"


def get_pl_facts(model_xbrl, dict_yuho, ns, qname_prefix,
                 pc_rel_set, is_consolidated):
    """
    損益計算書LineItemsの直下の勘定科目の値を取得する
    """

    # 【備考】ここでは表示リレーションシップを使う
    # 計算リレーションシップで計算関係を辿ることもできるが
    # この関数の目的には表示リレーションシップを使う方が楽だった

    # 損益計算書LineItemsを親とする表示リレーションシップを抽出
    qname_from = qname(ns, name=f"{qname_prefix}:StatementOfIncomeLineItems")
    rel_from_tgt_list = pc_rel_set.fromModelObject(
        model_xbrl.qnameConcepts.get(qname_from))
    '''
    TODO: ここ使わない。どっかに整理後削除。
    # 【備考】非連結または個別のfactを取得
    # ただし、連結には連結／非連結軸がscenarioに設定されず、以下の処理では取得されない
    # （報告書インスタンス作成ガイドライン：5-4-1 コンテキストIDの命名規約 より）
    facts_by_dim = model_xbrl.factsByDimMemQname(
            qname(model_xbrl.prefixedNamespaces["jppfs_cor"], name="jppfs_cor:ConsolidatedOrNonConsolidatedAxis")
    )
    '''

    for rel_from_tgt in rel_from_tgt_list:
        mcpt_to = rel_from_tgt.toModelObject

        # 【備考】：abstract == True の場合、タイトル項目なので金額情報なし。
        # その表示子要素の内、合計金額を表す要素のfactを取得する
        # 1. タイトル項目をfrom(親)とする表示リレーションシップを取得
        # 2. 1のリレーションシップの内、一番最後のリレーションシップのto(子)のfactを取得する
        if mcpt_to.isAbstract:
            pc_rels_from_tgt = pc_rel_set.fromModelObject(mcpt_to)
            if len(pc_rels_from_tgt) == 1:
                print(f"【想定外】勘定科目のタイトル項目の子が1件のみ　Qname: {mcpt_to.qname}")
                sys.exit()
            # 【備考】タイトル項目を親とする表示リレーションシップの内、
            # 最後がタイトル項目の実体を表す値。
            mcpt_to = pc_rels_from_tgt[len(pc_rels_from_tgt)-1].toModelObject

        # fact を取得
        # 【備考】1つの要素に対し、コンテキスト・ユニットの異なる複数のfactが存在し得る
        # - 当期のコンテキストID
        #   報告書インスタンス作成ガイドライン：5-4-5 コンテキストの設定例　参照
        #   - 連結財務情報:
        #     - 当期連結時点 = CurrentYearInstant
        #     - 当期連結期間 = CurrentYearDuration
        #   - 個別財務情報:
        #     - 当期個別時点 = CurrentYearInstant_NonConsolidatedMember
        #     - 当期個別期間 = CurrentYearDuration_NonConsolidatedMember
        contextid = f"CurrentYear{mcpt_to.periodType.capitalize()}"
        if is_consolidated == False:
            contextid += "_NonConsolidatedMember"
        localname = mcpt_to.qname.localName
        facts = model_xbrl.factsByQname[qname(
            ns, name=f"{qname_prefix}:{localname}")]
        for fact in facts:
            # 当年度の財務情報かつユニットが日本円のfactを取得する
            if (fact.contextID == contextid) and (fact.unitID == "JPY"):
                dict_yuho[mcpt_to.label()] = fact.value
                break
    return dict_yuho


def get_facts(model_xbrl, is_consolidated, has_consolidated):
    """有価証券報告書から取得対象の項目を取得する"""

    dict_facts = {}
    dict_facts[CONSOLIDATED_OR_NONCONSOLIDATED_COL] = "連結" if is_consolidated else "個別"
    dict_facts[HAS_CONSOLIDATED_ELM_NAME] = has_consolidated
    # リレーションシップの絞り込み用に指定するlinkrole
    if is_consolidated:
        link_role = "http://disclosure.edinet-fsa.go.jp/role/jppfs/rol_ConsolidatedStatementOfIncome"
    else:
        link_role = "http://disclosure.edinet-fsa.go.jp/role/jppfs/rol_StatementOfIncome"
    # 有価証券報告書xbrlから必要情報抽出
    for qname_prefix, localnames in YUHO_COLS_DICT.items():
        ns = model_xbrl.prefixedNamespaces[qname_prefix]
        if qname_prefix == "jpdei_cor":
            # 【備考】: Qname指定でfactを取得
            # ModelXbrlクラスのインスタンスのfactsBy*属性（辞書型）にfactが格納されている。
            # このうち、QnameをキーとするfactsByQnameを使用する。
            # 但し、factsByQnameのキーはQname文字列ではなく、Qnameクラスのインスタンス。
            # 文字列からQnameインスタンスを作成するために、qname関数を使用する。
            # qname関数の引数には名前空間uriが必要であるため、
            # ModelXbrlクラスのprefixedNamespaces属性（辞書型）から取得。
            for localname in localnames:
                facts = model_xbrl.factsByQname[qname(
                    ns, name=f"{qname_prefix}:{localname}")]
                if not facts:
                    # （EDINETの仕様上ここは呼ばれないはずだが）
                    dict_facts[localname] = None
                else:
                    dict_facts[localname] = list(facts)[0].value
        elif qname_prefix == "jppfs_cor":
            # 表示、計算の親子関係を表すリレーションシップを取得
            # linkrole=で対象のリンクロールに絞り込み
            pc_rel_set = model_xbrl.relationshipSet(
                XbrlConst.parentChild,
                linkrole=link_role
            )
            dict_facts = get_pl_facts(
                model_xbrl, dict_facts, ns, qname_prefix, pc_rel_set, is_consolidated)
        else:
            pass
    return dict_facts


def get_yuho_data_with_link(xbrl_files, df_edinetcd_info):
    """有価証券報告書の対象項目を取得し、会社情報を追加する"""

    list_dict_facts = []
    # 有価証券報告書から対象項目を取得
    for index, xbrl_file in enumerate(xbrl_files):
        print(xbrl_file, ":", index + 1, "/", len(xbrl_files))
        ctrl = Cntlr.Cntlr()
        model_manager = ModelManager.initialize(ctrl)
        model_xbrl = model_manager.load(xbrl_file)

        # 連結財務諸表ありかどうか
        ns = model_xbrl.prefixedNamespaces["jpdei_cor"]
        facts_has_consolidated = model_xbrl.factsByQname[qname(
            ns, name=f"jpdei_cor:{HAS_CONSOLIDATED_ELM_NAME}")]
        if list(facts_has_consolidated)[0].value == "true":
            has_consolidated = True
        elif list(facts_has_consolidated)[0].value == "false":
            has_consolidated = False
        else:
            print("連結決算の有無の項目の値が想定外です。")
            print(f"該当ファイル: {xbrl_file}")
        # 非連結または個別財務諸表はデフォルトで取得
        is_consolidated_list = [False]
        # 連結財務諸表ありの場合、追加
        if has_consolidated:
            is_consolidated_list.append(True)
        for is_consolidated in is_consolidated_list:
            dict_facts = get_facts(
                model_xbrl, is_consolidated, has_consolidated)
            list_dict_facts.append(dict_facts)

    df_yuho = pd.DataFrame(list_dict_facts)

    # 固定列のカラム名を日本語に変換
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
    if IS_TEST:
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
    xbrl_file_regrex = os.path.join(EDINET_ROOT_DIR, EDINET_XBRL_REGREX)
    xbrl_files = glob.glob(xbrl_file_regrex)
    # 有価証券報告書の情報を取得する
    df_yuho = get_yuho_data_with_link(xbrl_files, df_edinetcd_info)
    df_yuho.to_csv(
        os.path.join(EDINET_ROOT_DIR, OUTPUT_FILE_NAME),
        index=False,
        encoding="cp932"
    )
    print(f"{'-'*10} 情報抽出　完了 {'-'*10}")


if __name__ == "__main__":
    main()
