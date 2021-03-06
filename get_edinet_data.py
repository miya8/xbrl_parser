import csv
import json
import os
import sys
from datetime import datetime

import requests
from pandas import date_range

from edinetcd_info import get_edinetcd_info

# TODO: 訂正有価証券報告書が出ている場合、更新する

# 取得したEDINET文書の保存先
EDINET_DOC_SAVE_DIR = "D:\\EDINET\\120_yuho_20200101_20200630\\zip"
# EDINET文書の保存ファイルの命名規則
EDINET_DOC_SAVE_FILE = "{gyoshu}_{doctype}_{edinetcd}_{docid}.zip"
# 取得対象の開始日、終了日 (yyyy-mm-dd)
TARGET_DATE_START = "2020-01-01"
TARGET_DATE_END = "2020-06-30"
# 取得対象の文書タイプ （値はEDINET API仕様書参照）
TGT_DOCTYPE_LIST = ["120"]
# 取得対象の業種名（指定なしの場合、空のリスト[]）
TGT_GYOSHU_LIST = ["サービス業", "情報・通信業"]
# 取得対象のEDINETコード（指定なしの場合、空のリスト[]）
TGT_EDINETCD_LIST = []

# EDINET から取得失敗したdocIDの出力先ファイル名
FAILED_DOCID_OUTPUT_FILE = "取得失敗docID_ファイル日付{}_処理日時{}.csv"
# 日付フォーマット  書類一覧APIで使用するフォーマットに合わせる
DATE_FORMAT = "%Y-%m-%d"
# 書類一覧APIのエンドポイント
EDINET_DOCLIST_API_URL = "https://disclosure.edinet-fsa.go.jp/api/v1/documents.json"
# 書類一覧APIで取得する情報　1:メタデータのみ 2:メタデータと提出書類一覧
EDINET_API_INFO_TYPE = 2
# 書類取得APIのエンドポイント
EDINET_GETDOC_API_URL = "https://disclosure.edinet-fsa.go.jp/api/v1/documents/{}"

# EdinetcodeDlInfo.csv から取得する列
EDINETCD_COL = "ＥＤＩＮＥＴコード"
TEISHUTUSHA_GYOSHU_COL = "提出者業種"
EDINETCDDLINFO_COLS = [
    EDINETCD_COL,
    TEISHUTUSHA_GYOSHU_COL
]


def extract_tgt_type_docs(res_from_edinet):
    """指定したタイプの文書情報を抽出する"""

    json_res = json.loads(res_from_edinet.text)
    # 開示期間が過ぎている場合など取得失敗するケースあり
    if json_res["metadata"]["status"] != "200":
        return []
    # 指定した日の一覧を取得
    # 【備考】指定した日の文書がない場合、resultsは空のリスト
    doc_info_list = json_res["results"]
    doc_info_list = [
        doc_info for doc_info in doc_info_list if doc_info["docTypeCode"] in TGT_DOCTYPE_LIST
    ]
    return doc_info_list


def get_doc_list(str_tgt_date):
    """EDINET API で対象日の提出書類一覧を取得する"""

    params = {
        "date": str_tgt_date,
        "type": EDINET_API_INFO_TYPE
    }
    res = requests.get(EDINET_DOCLIST_API_URL, params=params)
    return extract_tgt_type_docs(res)


def download_zipfile(docid, doctype, edinetcd, gyoshu):
    """指定した文書をダウンロードして保存する"""

    url_doc = EDINET_GETDOC_API_URL.format(docid)
    save_zfile_path = os.path.join(
        EDINET_DOC_SAVE_DIR,
        EDINET_DOC_SAVE_FILE.format(
            gyoshu=gyoshu,
            doctype=doctype,
            edinetcd=edinetcd,
            docid=docid
        )
    )

    res = requests.get(url_doc, params={"type": 1})
    # zip形式のファイル取得成功時、zipファイルを保存
    # （"Content-Type"の値は EDINET API仕様書より）
    # TODO: 取得失敗した場合、リトライ
    if res.headers["Content-Type"] == "application/octet-stream":
        with open(save_zfile_path, "wb") as f:
            for chunk in res.iter_content(chunk_size=1024):
                f.write(chunk)
                f.flush()
            return True
    return False


def main():
    tgt_dates = date_range(
        TARGET_DATE_START,
        TARGET_DATE_END,
        freq="D"
    ).strftime(DATE_FORMAT)
    # EDINETコードリストから企業情報を取得
    df_edinetcd_info = get_edinetcd_info(EDINETCDDLINFO_COLS)
    # 対象日ごとの処理
    for str_tgt_date in tgt_dates:
        print(f"{'-'*10} {str_tgt_date} {'-'*10}")
        # ファイル日付が対象日、かつ指定した種類の文書情報一覧を取得
        doc_list = get_doc_list(str_tgt_date)
        # 指定した業種の文書を取得
        os.makedirs(EDINET_DOC_SAVE_DIR, exist_ok=True)
        get_num = 0
        failed_docs = []
        for doc in doc_list:
            # 縦覧首相・書類取下げによりEDINETコード（他データも）が欠損となる
            if doc["edinetCode"] is None:
                continue
            # EDINETコードの集約により
            # 最新のEDINETコードリストとマッチしないケースがある
            # TODO: ファンドコードを基に変更後のEDINET コードを把握する
            # EDINET API仕様書: EDINET コード自体の変更　参照
            df_tgt = df_edinetcd_info[
                df_edinetcd_info[EDINETCD_COL] == doc["edinetCode"]
            ]
            if df_tgt.shape[0] < 1:
                continue
            elif df_tgt.shape[0] > 1:
                print("【想定外】EDINETコードコードリストのEDINETコードに重複があります。")
                sys.exit()
            gyoshu = df_tgt[TEISHUTUSHA_GYOSHU_COL].values[0]
            if TGT_GYOSHU_LIST:
                if gyoshu not in TGT_GYOSHU_LIST:
                    continue
            edinet_cd = doc["edinetCode"]
            if TGT_EDINETCD_LIST and (edinet_cd not in TGT_EDINETCD_LIST):
                continue
            has_successed = download_zipfile(
                doc["docID"], doc["docTypeCode"], edinet_cd, gyoshu)
            if has_successed == False:
                print(f"取得失敗: docID {doc['docID']}")
                failed_docs.append([doc["docID"]])
            get_num += 1
        print(f"ダウンロード数: {get_num}")
        # EDINETから取得失敗した文書がある場合、docidを出力しておく
        if failed_docs:
            output_path = os.path.join(
                EDINET_DOC_SAVE_DIR,
                FAILED_DOCID_OUTPUT_FILE.format(
                    str_tgt_date, datetime.now().strftime("%Y%m%d%H%M"))
            )
            with open(output_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerows(failed_docs)
            print(f"""
                EDINETから取得失敗した文書が{len(failed_docs)}件あります。
                 {output_path} を確認してください。
                """)
    print(f"{'-'*10} 処理終了 {'-'*10}")


if __name__ == "__main__":
    main()
