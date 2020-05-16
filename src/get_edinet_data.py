import csv
import json
import os
import zipfile
from datetime import datetime, timedelta

import requests

from edinetcd_info import EDINETCD_COL, get_edinetcd_info

# TODO: 訂正有価証券報告書が出ている場合、更新する

# 取得したEDINET文書の保存先
EDINET_DOC_SAVE_DIR = "D:\\EDINET\\test\\zip"
# EDINET文書の保存ファイルの命名規則
EDINET_DOC_SAVE_FILE = "{gyoshu}_{doctype}_{edinetcd}_{docid}.zip"
# 取得対象の開始日、終了日 (yyyy-mm-dd)
TARGET_DATE_START = "2020-04-20"
TARGET_DATE_END = "2020-04-21"
# 取得対象の文書タイプ （値はEDINET API仕様書参照）
TGT_DOCTYPE_LIST = ["120"]
# 取得対象の業種名（指定なしの場合空のリスト[]）
TGT_GYOSHU_LIST = ["サービス業", "情報・通信業"]

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
TEISHUTUSHA_GYOSHU_COL = "提出者業種"
EDINETCDDLINFO_COLS = [
    EDINETCD_COL,
    TEISHUTUSHA_GYOSHU_COL
]


def extract_tgt_type_docs(res_from_edinet):
    """指定したタイプの文書情報を抽出する"""

    doc_info_list = json.loads(res_from_edinet.text)["results"]
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
    if res.headers["Content-Type"] == "application/octet-stream":
        with open(save_zfile_path, "wb") as f:
            for chunk in res.iter_content(chunk_size=1024):
                f.write(chunk)
                f.flush()
            return True
    return False


def main():
    date_start = datetime.strptime(TARGET_DATE_START, DATE_FORMAT)
    date_end = datetime.strptime(TARGET_DATE_END, DATE_FORMAT)
    days_num = (date_end - date_start).days + 1
    tgt_dates = [
        datetime.strftime(date_start + timedelta(n_days), DATE_FORMAT)
        for n_days in range(days_num)
    ]
    # EDINETコードリストから企業情報を取得
    df_edinetcd_info = get_edinetcd_info(EDINETCDDLINFO_COLS)
    # 対象日ごとの処理
    for str_tgt_date in tgt_dates:
        print(f"{'-'*10} {str_tgt_date} {'-'*10}")
        # ファイル日付が対象日、かつ指定した種類の文書情報一覧を取得
        doc_list = get_doc_list(str_tgt_date)
        # 指定した業種の文書を取得
        failed_docs = []
        for doc in doc_list:
            gyoshu = df_edinetcd_info.loc[
                df_edinetcd_info[EDINETCD_COL] == doc["edinetCode"],
                TEISHUTUSHA_GYOSHU_COL].values[0]
            if TGT_GYOSHU_LIST:
                if not gyoshu in TGT_GYOSHU_LIST:
                    continue
            edinet_cd = doc["edinetCode"]
            has_successed = download_zipfile(
                doc["docID"], doc["docTypeCode"], edinet_cd, gyoshu)
            if has_successed == False:
                print(f"取得失敗: docID {doc['docID']}")
                failed_docs.append([doc["docID"]])
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
