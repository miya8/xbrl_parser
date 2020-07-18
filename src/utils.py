import glob
import os
import re
import zipfile


def extract_files_from_zip(zip_dir, tgt_zfile_names=None, dest_dir_root=None, dest_dirname=None, unzip_members_regrep=None):
    """zipファイルからファイルを抽出する"""

    if tgt_zfile_names is None:
        zip_files = glob.glob(os.path.join(zip_dir, "*.zip"))
    else:
        zip_files = [os.path.join(zip_dir, fname) for fname in tgt_zfile_names]
    zip_file_num = len(zip_files)
    for index, zip_file in enumerate(zip_files):
        zfile_name = os.path.splitext(os.path.basename(zip_file))[0]
        print(f"{zfile_name}: {index + 1} / {zip_file_num}")
        if dest_dirname is None:
            dest_last_dir = zfile_name
        else:
            dest_last_dir = dest_dirname
        if dest_dir_root is None:
            dest_dir_path = os.path.join(zip_dir, dest_last_dir)
        else:
            dest_dir_path = os.path.join(dest_dir_root, dest_last_dir)
        with zipfile.ZipFile(zip_file) as zf:
            if unzip_members_regrep is None:
                tgt_members_names = None
            else:
                tgt_members_names = []
                for filename in zf.namelist():
                    if re.findall(unzip_members_regrep, filename):
                        tgt_members_names.append(filename)
            zf.extractall(
                path=dest_dir_path,
                members=tgt_members_names
            )
            zf.close()
