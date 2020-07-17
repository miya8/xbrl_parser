import sys
import time

import chromedriver_binary
import pandas as pd
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

EDINETCD_DOWNLOAD_PAGE_URL = "https://disclosure.edinet-fsa.go.jp/E01EW/BLMainController.jsp?uji.verb=W1E62071InitDisplay&uji.bean=ee.bean.W1E62071.EEW1E62071Bean&TID=W1E62071&PID=currentPage&SESSIONKEY=1594968624445&downloadFileName=&lgKbn=2&dflg=0&iflg=0&dispKbn=1"
EDINETCD_INFO_PATH = "D:\\EDINET\\Edinetcode"
EDINETCD_COL = "ＥＤＩＮＥＴコード"
CHROME_PATH = "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"

# EdinetcodeDlInfo.csv から取得する列
# 必須項目: https://disclosure.edinet-fsa.go.jp/download/ESE140119.pdf 参照
EDINETCDDLINFO_COLS = [
    EDINETCD_COL,
    "提出者業種",
    "上場区分",
    "提出者種別",
    "提出者名"
]


def enable_headless_download(driver):
    """ 
    ヘッドレスでダウンロード可能にする
    ダウンロード先のパスを指定する
    """

    driver.command_executor._commands["send_command"] = (
        "POST",
        '/session/$sessionId/chromium/send_command'
    )
    params = {
        'cmd': 'Page.setDownloadBehavior',
        'params': {
            'behavior': 'allow',
            'downloadPath': EDINETCD_INFO_PATH
        }
    }
    driver.execute("send_command", params=params)


def download_edinetcd():
    """EDINETサイトからEDINETコードリストを取得する"""

    # ダウンロードリンクが動的であるため、Seleniumで取得
    options = Options()
    options.binary_location = CHROME_PATH
    options.add_argument('--headless')
    driver = Chrome(options=options)
    enable_headless_download(driver)
    driver.get(EDINETCD_DOWNLOAD_PAGE_URL)
    elm_table1_trs = driver.find_elements_by_css_selector(".main_table_1 tr")
    msg = "EDINETサイト変更を確認してください。"
    is_tgt_tr = False
    for tr in elm_table1_trs:
        elm_tds = tr.find_elements_by_css_selector("td")
        for td in elm_tds:
            if is_tgt_tr:
                elms = td.find_elements_by_css_selector("a")
                if len(elms) != 1:
                    print(f"取得したEDINETコードリストのリンク数が想定外です。{msg}")
                    sys.exit()
                driver.execute_script(elms[0].get_property("href"))
                time.sleep(5)
                break
            if td.text == "EDINETコードリスト":
                is_tgt_tr = True
        if is_tgt_tr:
            break
    if is_tgt_tr == False:
        print(f"EDINETコードリストのリンク要素を取得できませんでした。{msg}")
        sys.exit()
    driver.quit()


def get_edinetcd_info(use_cols):
    """EDINETコードリストから企業情報を取得する"""

    df_edinetcd_info = pd.read_csv(
        EDINETCD_INFO_PATH,
        skiprows=1,
        usecols=use_cols,
        encoding='cp932'
    )
    return df_edinetcd_info
