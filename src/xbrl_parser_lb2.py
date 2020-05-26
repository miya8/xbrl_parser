import glob
import os
import re
import zipfile

import pandas as pd

from arelle import Cntlr, ModelManager, ModelValue, XbrlConst
from edinetcd_info import get_edinetcd_info, EDINETCD_COL
from xbrl_parser import *


def get_tgt_data_test(model_xbrl, yuho_cols, is_consolidated, has_consolidated):
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

            #TODO: jppfs_corは、定数で要素名定義NGなので、構造変える　★★★
            elif qname_prefix == "jppfs_cor":
                # 親子関係を示すリレーションシップを取得
                parentChild_rel_set = model_xbrl.relationshipSet(XbrlConst.parentChild)
                # 損益計算書LineItemsを親とするリレーションシップを抽出
                qname_from = ModelValue.qname(ns, name=f"{qname_prefix}:StatementOfIncomeLineItems")
                rel_from_tgt_list = parentChild_rel_set.fromModelObject(model_xbrl.qnameConcepts.get(qname_from))
                for rel_from_tgt in rel_from_tgt_list:
                    print()
                    print(rel_from_tgt)
                    print("type(qnameconcept_test): ", type(rel_from_tgt))
                    modelConcept_to = rel_from_tgt.toModelObject
                    print("modelConcept_to: ", modelConcept_to)
                    # modelConcept_to:  modelConcept[5284, qname: jppfs_cor:NetSales, type: xbrli:monetaryItemType, abstract: false, jppfs_cor_2018-03-31.xsd, line 251]
                    # abstract == True の場合、タイトル項目なので、その直下の表示要素を取得する
                    if modelConcept_to.abstract == "true":
                        # TODO: ★★実装する★★
                        qname_from_next = ModelValue.qname(ns, name=f"{qname_prefix}:{modelConcept_to.qname.localName}")
                        rel_from_tgt_list = parentChild_rel_set.fromModelObject(model_xbrl.qnameConcepts.get(qname_from_next))
                    else:
                        #qname_prefix = modelConcept_to.qname.prefix
                        localname = modelConcept_to.qname.localName
                        for fact in facts:
                            print("fact.context: ", fact.context)
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
                                print("localname: ", localname)
                                ser_yuho[localname] = fact.value
                                ser_yuho[f"{localname}_unitid"] = fact.unitID
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


# TODO: 特定の項目を要素名指定で取得する方法では、会社ごとの定義の違いにより取得できないケースがある。
# 学習対象として、どの会社でも「売上」を取得できるよう、タクソノミの仕様に沿った方法を調べる
# 【忘備】例として損益計算書の主要勘定科目を取得する
# 1. 表示リンクで、損益計算書の直下の勘定科目リストを取得する
# 2. 計算リンクで、1で取得したリストの計算関係を元に売上～当期純利益の勘定科目を求める
# ★これってlxmlでやった方が楽なのでは？

def get_yuho_data_with_link(xbrl_files, df_edinetcd_info):
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
        #print("model_manager.defaultLang: ", model_manager.defaultLang)
        #print("dir(model_manager.disclosureSystem): ", dir(model_manager.disclosureSystem))
        #print("model_manager.disclosureSystem.validationType: ", model_manager.disclosureSystem.validationType)
        #import sys
        #sys.exit()
        model_xbrl = model_manager.load(xbrl_file)
        #print("dir(model_xbrl): ", dir(model_xbrl))
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
            ser_yuho = get_tgt_data_test(
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
    '''★★テストのため無効中
    edinet_zip_dir = os.path.join(EDINET_ROOT_DIR, "zip")
    xbrl_parser.extract_files_from_zip(edinet_zip_dir)
    '''
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
