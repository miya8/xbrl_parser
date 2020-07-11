import glob
import os
import re
import zipfile

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