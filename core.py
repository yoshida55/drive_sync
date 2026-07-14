# -*- coding: utf-8 -*-
"""
core.py … 検索・コピー・VS Code起動のロジック（GUIから呼ばれる裏方）

【安全方針】
- Google Drive 側（parent_folder）は「読むだけ」。コピー元として参照するだけで書き込まない。
- 編集はローカルのコピー（copy_dest）上で行う。Drive へ書き戻す機能は持たない。

プロトタイプ段階なのでログは多め（logging.INFO / DEBUG）。
"""

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime

# --- ログ設定（何が起きているか全部出す） ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gdrive_opener")

# config.json を置く場所。
# exe化（PyInstaller）したときは exe と同じフォルダ、
# 普通に python 実行のときはこのソースと同じフォルダに置く。
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)   # 例: dist\gdrive_opener.exe の隣
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# config.json が無いとき用のデフォルト
DEFAULT_CONFIG = {
    "parent_folder": "G:\\マイドライブ\\00_リンクワークス\\test",
    "copy_dest": "D:\\work",
    "ignore": ["desktop.ini", "Thumbs.db"],
    "clean_before_open": False,  # 開く前にコピー先の古いフォルダを消すか
}


# =====================================================================
# 設定（config.json）まわり
# =====================================================================
def load_config():
    """config.json を読み込む。無ければデフォルトを作って返す。"""
    if not os.path.exists(CONFIG_PATH):
        log.warning("config.json が見つからないのでデフォルトを作成します: %s", CONFIG_PATH)
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # 足りないキーはデフォルトで補う（壊れた設定でも落ちないように）
    for key, val in DEFAULT_CONFIG.items():
        cfg.setdefault(key, val)
    log.info("設定を読み込みました: parent=%s / dest=%s", cfg["parent_folder"], cfg["copy_dest"])
    return cfg


def save_config(cfg):
    """config.json に書き戻す（設定画面から呼ぶ）。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    log.info("設定を保存しました: %s", CONFIG_PATH)


# =====================================================================
# 検索・一覧
# =====================================================================
# 表示するときに頭から外す接頭辞（あれば外す・無ければそのまま）
_DISPLAY_PREFIXES = ("00_", "PJ_")


def display_name(folder_name):
    """フォルダ名から '00_' や 'PJ_' の接頭辞を外して見やすくする。"""
    for pre in _DISPLAY_PREFIXES:
        if folder_name.startswith(pre):
            return folder_name[len(pre):]
    return folder_name


def _list_dirs(path):
    """path 直下のサブフォルダ名だけを返す（ファイルは無視）。"""
    if not os.path.isdir(path):
        log.error("フォルダが存在しません: %s", path)
        return []
    dirs = [name for name in os.listdir(path)
            if os.path.isdir(os.path.join(path, name))]
    log.debug("直下のフォルダ %d 件: %s", len(dirs), dirs)
    return dirs


def find_folders(parent, keyword):
    """
    親フォルダ直下のフォルダ全部（人・共通・結合など何でも）から
    keyword を部分一致で探す。

    戻り値: [{"name": 実フォルダ名, "display": 表示名, "path": フルパス}, ...]
    keyword が空なら全部返す。マッチは実名・表示名どちらに含まれてもOK。
    """
    keyword = (keyword or "").strip()
    log.info("検索: parent=%s / keyword='%s'", parent, keyword)

    results = []
    for name in _list_dirs(parent):
        disp = display_name(name)
        if keyword == "" or (keyword in name) or (keyword in disp):
            results.append({
                "name": name,
                "display": disp,
                "path": os.path.join(parent, name),
            })
    log.info("検索ヒット: %d 件 → %s", len(results), [r["display"] for r in results])
    return results


def list_subfolders(target_dir):
    """
    選んだフォルダの直下にあるサブフォルダ一覧を返す（PJ以外も全部数える）。

    戻り値: [{"name": 実フォルダ名, "display": 表示名, "path": フルパス}, ...]
    """
    log.info("サブフォルダ一覧: %s", target_dir)
    results = []
    for name in _list_dirs(target_dir):
        results.append({
            "name": name,
            "display": display_name(name),
            "path": os.path.join(target_dir, name),
        })
    log.info("サブフォルダ %d 件 → %s", len(results), [r["display"] for r in results])
    return results


# =====================================================================
# コピー & VS Code 起動
# =====================================================================
def copy_project(src, copy_dest, ignore=None, overwrite=False):
    """
    src フォルダを copy_dest の下にコピーする（コピー先はローカル）。

    - ignore に入っているファイル名（desktop.ini 等）は除外
    - コピー先に同名フォルダが既にある場合:
        overwrite=False → False を返す（呼び出し側で確認ダイアログを出す想定）
        overwrite=True  → 一度消してからコピー
    戻り値: コピー先のフルパス（成功時） / False（上書き確認が必要なとき）
    """
    ignore = ignore or []
    folder_name = os.path.basename(src.rstrip("\\/"))
    dest = os.path.join(copy_dest, folder_name)
    log.info("コピー開始: %s → %s", src, dest)

    # コピー先フォルダ自体が無ければ作る
    os.makedirs(copy_dest, exist_ok=True)

    if os.path.exists(dest):
        if not overwrite:
            log.warning("コピー先に同名フォルダが既にあります（上書き確認が必要）: %s", dest)
            return False
        log.warning("上書きするため既存フォルダを削除します: %s", dest)
        shutil.rmtree(dest)

    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*ignore))
    log.info("コピー完了: %s", dest)
    return dest


def clean_dest(copy_dest):
    """
    コピー先の中にある「古いコピー（サブフォルダ）」を全部消す。

    - 消すのは直下のフォルダだけ。ファイルは残す（安全側）。
    - コピー先は専用フォルダである前提。他の物を置かないこと。
    - VS Code で開いている等で使用中のフォルダは消せない。その場合は
      握りつぶさず「消せなかった一覧」として返す（呼び出し側で案内する）。
    戻り値: (削除できた数, 消せなかったフォルダ名のリスト)
    """
    if not os.path.isdir(copy_dest):
        log.info("コピー先がまだ無いので掃除不要: %s", copy_dest)
        return 0, []

    removed = 0
    failed = []
    for name in os.listdir(copy_dest):
        p = os.path.join(copy_dest, name)
        if os.path.isdir(p):
            try:
                shutil.rmtree(p)  # 使用中なら例外が出る（ignore_errorsにしない）
                log.warning("古いコピーを削除: %s", p)
                removed += 1
            except OSError as e:
                log.error("古いコピーを削除できません（使用中かも）: %s (%s)", p, e)
                failed.append(name)
    log.info("古いコピー削除: 成功 %d 件 / 失敗 %d 件", removed, len(failed))
    return removed, failed


def open_in_vscode(path):
    """VS Code でフォルダを開く。Windows の code は code.cmd なので shell=True。"""
    log.info("VS Code で開きます: %s", path)
    try:
        subprocess.run(["code", path], shell=True, check=True)
        return True
    except Exception as e:  # noqa: BLE001  プロトタイプなので握って表示
        log.error("VS Code 起動に失敗: %s", e)
        return False


def open_in_explorer(path):
    """フォルダをエクスプローラーで開く（Windows）。os.startfile がフォルダを既定で開く。"""
    log.info("エクスプローラーで開きます: %s", path)
    try:
        os.startfile(path)  # noqa: S606  Windows専用。フォルダを開く
        return True
    except Exception as e:  # noqa: BLE001
        log.error("エクスプローラー起動に失敗: %s", e)
        return False


# =====================================================================
# 単体動作チェック（python core.py で実行）
# =====================================================================
if __name__ == "__main__":
    log.info("=== core.py 単体テスト ===")
    cfg = load_config()
    hits = find_folders(cfg["parent_folder"], "")
    for h in hits:
        subs = list_subfolders(h["path"])
        print(f"[{h['display']}] サブフォルダ {len(subs)}件: {[s['display'] for s in subs]}")
