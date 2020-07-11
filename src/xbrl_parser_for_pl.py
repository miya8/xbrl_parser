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
# "jpdei_cor"（会社・書類情報）: 以下に記載した項目は登録必須のためqname指定で取得する
# "jppfs_cor"（財務諸表本表）: 企業ごとに項目が異なるため、リンクベースに沿って情報を取得する
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

def get_pl_facts(model_xbrl, dict_yuho, ns, qname_prefix, pc_rel_set, cal_rel_set, dim_rel_set, is_consolidated):
    """
    損益計算書LineItemsをfrom(親)とする表示リレーションシップのto(子)となる各ModelConceptのfactの値を取得する
    但しto(子)が抽象項目の場合は、更にそのto(子)達の内、集計結果を表すModelConceptのfactの値を取得する
    """

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
        print()
        mcpt_to = rel_from_tgt.toModelObject
        print("modelConcept_to: ", mcpt_to)
        # -> modelConcept_to:  modelConcept[5284, qname: jppfs_cor:NetSales, type: xbrli:monetaryItemType, abstract: false, jppfs_cor_2018-03-31.xsd, line 251]

        # abstract == True の場合、タイトル項目なので金額情報なし。その表示子要素の内、合計金額を表す要素のfactを取得する
        # 【備考】：以下の処理を行う
        # 1. タイトル項目をfrom(親)とする表示リレーションシップを取得
        # 2. 1のリレーションシップのto(子)のModelObjectを取得
        # 3. 2の子達をfrom(親)とする計算リレーションシップを取得して確認　:　1つがfrom(親=算出結果)、他がto(子=親の算出に使われる要素)
        # 4. 3で得たfrom(親)のfactを取得する
        if mcpt_to.isAbstract:
            pc_rels_from_tgt = pc_rel_set.fromModelObject(mcpt_to)
            if len(pc_rels_from_tgt) == 1:
                print(f"【想定外】勘定科目_abstract の子が1件のみ　 Qname: {mcpt_to.qname}")
                sys.exit()
            mcpt_to_its_children = []
            for pc_rel in pc_rels_from_tgt:
                mcpt_to_its_children.append(pc_rel.toModelObject)
            mcpt_to_tmp = None
            for mcpt_to_its_child in mcpt_to_its_children:
                cal_rels_children = cal_rel_set.fromModelObject(
                    mcpt_to_its_child)
                if len(cal_rels_children) == len(pc_rels_from_tgt) - 1:
                    mc_children = set()
                    for cal_rel in cal_rels_children:
                        mc_children.add(cal_rel.toModelObject)
                    set_mcpt_to_its_children = set(mcpt_to_its_children)
                    set_mcpt_to_its_children.remove(mcpt_to_its_child)
                    if mc_children == set_mcpt_to_its_children:
                        mcpt_to_tmp = mcpt_to_its_child
                        break
            if mcpt_to_tmp is None:
                print("【想定外】勘定科目_abstractの子達の計算関係にfrom(親)が存在しません。")
                sys.exit()
            mcpt_to = mcpt_to_tmp

        # fact を取得
        # 【備考】1つの要素に対し、コンテキスト・ユニットの異なる複数のfactが存在し得る
        # 当期のコンテキストIDは、報告書インスタンス作成ガイドライン：5-4-5 コンテキストの設定例より
        # - 連結財務情報: 
        #   - 当期連結時点 = CurrentYearInstant
        #   - 当期連結期間 = CurrentYearDuration
        # - 個別財務情報: 
        #   - 当期個別時点 = CurrentYearInstant_NonConsolidatedMember
        #   - 当期個別期間 = CurrentYearDuration_NonConsolidatedMember
        contextid = f"CurrentYear{mcpt_to.periodType.capitalize()}"
        if is_consolidated == False:
            contextid += "_NonConsolidatedMember"
        localname = mcpt_to.qname.localName
        facts = model_xbrl.factsByQname[qname(
            ns, name=f"{qname_prefix}:{localname}")]
        for fact in facts:
            # 当年度の財務情報かつユニットが日本円のfactを取得する
            if (fact.contextID == contextid) and (fact.unitID == "JPY"):
                print("localname: ", localname)
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
    # 【備考】: 有価証券報告書xbrlから必要情報抽出（総なめしない）
    # 1. ModelXbrlクラスのfactsByQname属性（辞書型）に すべてのfactが格納されている
    # 2. 1のキーはQnameクラスオブジェクト。Prefix:要素名の文字列から
    #    Qname型オブジェクトを作成するために、ModelValue.py の qname関数を使用
    # 3. 2のvalue指定に名前空間uriが必要。ModelXbrlクラスのprefixedNamespaces属性（辞書型）から取得。
    for qname_prefix, localnames in YUHO_COLS_DICT.items():
        print("qname_prefix: ", qname_prefix)
        ns = model_xbrl.prefixedNamespaces[qname_prefix]
        if qname_prefix == "jpdei_cor":
            for localname in localnames:
                facts = model_xbrl.factsByQname[qname(
                    ns, name=f"{qname_prefix}:{localname}")]
                if not facts:
                    # YUHO_COLS_DICT["jpdei_cor"]に設定した要素はEDINETの入力必須項目のため
                    # ここは呼ばれないはず
                    dict_facts[localname] = None
                else:
                    dict_facts[localname] = list(facts)[0].value
        elif qname_prefix == "jppfs_cor":
            # 表示、計算の親子関係を表すリレーションシップを取得
            # linkrole=で対象のリンクロールに絞り込み
            pc_rel_set = model_xbrl.relationshipSet(XbrlConst.parentChild, linkrole=link_role)
            cal_rel_set = model_xbrl.relationshipSet(XbrlConst.summationItem, linkrole=link_role)
            dim_rel_set = model_xbrl.relationshipSet(XbrlConst.domainMember, linkrole=link_role)
            dict_facts = get_pl_facts(
                model_xbrl, dict_facts, ns, qname_prefix, pc_rel_set, cal_rel_set, dim_rel_set, is_consolidated)
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
        extract_files_from_zip(edinet_zip_dir)
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
