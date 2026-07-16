# -*- coding: utf-8 -*-
"""
core.py … 検索・コピー・VS Code起動のロジック（GUIから呼ばれる裏方）

【安全方針】
- 検索元の Google Drive（parent_folder）は「読むだけ」。コピー元として参照するだけで書き込まない。
- 編集はローカルのコピー（copy_dest）上で行う。
- Drive へ書き戻すのは push_project() だけ。書き戻し先は push_dest に限定し、
  上書きするときも既存フォルダは削除せず `_bkup_日時` にリネームして残す（戻せるようにする）。

プロトタイプ段階なのでログは多め（logging.INFO / DEBUG）。
"""

import fnmatch
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

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
    # --- Drive へ送る（プッシュ）用 ---
    "push_dest": "G:\\マイドライブ\\00_リンクワークス\\test",
    # 送るときだけ余分に除外するもの。.git や node_modules を Drive に上げると
    # ファイル数が爆発して同期が終わらなくなるので必ず外す。
    "push_ignore": ["desktop.ini", "Thumbs.db", ".git", "node_modules",
                    "venv", ".venv", "__pycache__"],
    "push_backup_keep": 2,  # 上書き前の控えを何世代残すか
}

# 送信時に作る控えフォルダの名前（例: PJ_sample_bkup_20260716_210341）
_BKUP_MARK = "_bkup_"
_STAMP_FMT = "%Y%m%d_%H%M%S"  # 名前順に並べると古い順になる形式

# Google ドキュメント類。中身はネット上にあり、Gドライブに見えているのは「入口」だけ。
# Python から開こうとすると [Errno 22] で読めない（copy2 も copyfile も手書きも全滅）ので、
# 設定に関係なく必ずコピー対象から外す。持ってきても中身は入らないため実害はない。
GOOGLE_DOC_PATTERNS = ["*.gdoc", "*.gsheet", "*.gslides", "*.gform",
                       "*.gdraw", "*.gmap", "*.gsite", "*.glink", "*.gtable"]


def _with_google_docs(ignore):
    """設定の除外リストに、コピー不可の Google 書類を必ず足す。"""
    return list(ignore or []) + GOOGLE_DOC_PATTERNS


def find_google_docs(path):
    """
    path の中にある Google 書類（.gdoc 等）を探して、相対パスのリストで返す。
    コピーを飛ばしたことをユーザーに伝えるのに使う。
    """
    if not os.path.isdir(path):
        return []
    found = []
    for root, _dirs, files in os.walk(path):
        for name in files:
            if any(fnmatch.fnmatch(name, pat) for pat in GOOGLE_DOC_PATTERNS):
                found.append(os.path.relpath(os.path.join(root, name), path))
    if found:
        log.info("Google書類 %d 件（コピー不可なので飛ばす）: %s", len(found), found)
    return found


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
# 「どこから持ってきたか・最後にいつ触ったか」の記録
#   例: origins["PJ_高橋"] = {"path": "G:\\...\\高橋さん\\PJ_高橋",
#                             "synced_at": "2026-07-16 22:11:03"}
#   - path     … 送るときの戻し先
#   - synced_at … 自分が最後に「持ってきた or 送った」時刻。
#                 Drive の更新が「自分の仕業か、他人の編集か」を見分けるのに使う。
#   Drive 側にメモファイルを置くと送信時に紛れ込むので、記録はローカルの config だけに持つ。
# =====================================================================
_SYNC_FMT = "%Y-%m-%d %H:%M:%S"

# Drive の日付は同期の都合で少しズレる。この範囲内なら「自分が送った分」とみなす。
SYNC_GRACE_MINUTES = 5


def remember_origin(cfg, folder_name, src, synced_at=None):
    """持ってきた／送ったときに、元のフルパスと「今触った」時刻を覚える。"""
    origins = cfg.setdefault("origins", {})
    origins[folder_name] = {
        "path": src,
        "synced_at": (synced_at or datetime.now()).strftime(_SYNC_FMT),
    }
    save_config(cfg)
    log.info("戻し先を覚えました: %s → %s（同期 %s）",
             folder_name, src, origins[folder_name]["synced_at"])


def _origin_record(cfg, folder_name):
    """記録を取り出す。昔の形式（パスの文字列だけ）でも読めるようにする。"""
    rec = cfg.get("origins", {}).get(folder_name)
    if isinstance(rec, str):
        return {"path": rec, "synced_at": None}  # 旧形式：時刻は分からない
    return rec


def get_origin(cfg, folder_name):
    """覚えている元のフルパスを返す。無ければ None（＝まだ持ってきていない）。"""
    rec = _origin_record(cfg, folder_name)
    origin = rec["path"] if rec else None
    log.debug("戻し先の記録: %s → %s", folder_name, origin)
    return origin


def get_last_sync(cfg, folder_name):
    """自分が最後に持ってきた／送った時刻（datetime）。分からなければ None。"""
    rec = _origin_record(cfg, folder_name)
    if not rec or not rec.get("synced_at"):
        return None
    try:
        return datetime.strptime(rec["synced_at"], _SYNC_FMT)
    except ValueError:
        return None


def touched_by_others(cfg, folder_name, dest):
    """
    Drive 側が「自分が最後に触ったあと」に更新されているか＝他の人が触ったかを見る。

    自分が送れば Drive の日付は必ず新しくなる。そこで「ローカルより新しいか」ではなく
    「自分が最後に同期した時刻より、さらに後に更新されているか」で判定する。
    戻り値: (他人が触ったか, Drive側の最終更新)
    """
    dest_time = latest_mtime(dest)
    if dest_time is None:
        return False, None

    last_sync = get_last_sync(cfg, folder_name)
    if last_sync is None:
        return False, dest_time  # 記録が無いので判断できない（別の警告を出す側で扱う）

    # 同期のズレぶんは自分の仕業とみなす
    limit = last_sync + timedelta(minutes=SYNC_GRACE_MINUTES)
    others = dest_time > limit
    log.info("他人の編集チェック: Drive=%s / 自分の最終同期=%s → %s",
             dest_time.strftime(_SYNC_FMT), last_sync.strftime(_SYNC_FMT),
             "他人が触った可能性あり" if others else "自分の分")
    return others, dest_time


def same_path(a, b):
    """2つのパスが同じ場所を指すか（Windows は大文字小文字を区別しないので揃えて比べる）。"""
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


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


def _without_backups(names):
    """送信の控え（〇〇_bkup_日時）を一覧から外す。検索結果に混ざると邪魔なので。"""
    keep = [n for n in names if _BKUP_MARK not in n]
    if len(keep) != len(names):
        log.debug("控えフォルダ %d 件を一覧から除外", len(names) - len(keep))
    return keep


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
    for name in _without_backups(_list_dirs(parent)):
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
    for name in _without_backups(_list_dirs(target_dir)):
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
    ignore = _with_google_docs(ignore)
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


# =====================================================================
# Drive へ送る（プッシュ）
#   ここだけが Drive に書き込む処理。他はすべて読むだけ。
# =====================================================================
def latest_mtime(path):
    """
    フォルダの中で一番新しい更新日時を返す（datetime）。中身が無ければフォルダ自身の日時。
    「Drive 側が自分より新しくないか（＝他所で編集されていないか）」の判定に使う。
    """
    if not os.path.exists(path):
        return None

    newest = os.path.getmtime(path)
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, name)))
            except OSError:
                continue  # 同期中などで読めないファイルは飛ばす
    return datetime.fromtimestamp(newest)


def _backup_dirs(push_dest, folder_name):
    """push_dest の中にある「folder_name の控え」を古い順に返す。"""
    prefix = folder_name + _BKUP_MARK
    names = [n for n in _list_dirs(push_dest) if n.startswith(prefix)]
    return sorted(names)  # 日時が名前に入っているので名前順＝古い順


def _trim_backups(push_dest, folder_name, keep):
    """控えを keep 世代だけ残して古いものを消す（Drive を控えだらけにしないため）。"""
    backups = _backup_dirs(push_dest, folder_name)
    for name in backups[:max(0, len(backups) - keep)]:
        p = os.path.join(push_dest, name)
        try:
            shutil.rmtree(p)
            log.info("古い控えを削除: %s", p)
        except OSError as e:
            log.error("古い控えを削除できません: %s (%s)", p, e)


def push_project(src, push_dest, ignore=None, overwrite=False, backup_keep=3):
    """
    ローカルの src フォルダを push_dest の下へ送る（＝Google Drive へ書き戻す）。

    上書きするときも既存フォルダは削除しない。`名前_bkup_日時` にリネームして退避してから
    新しいものをコピーする。事故ってもリネームを戻せば元に戻せる。

    - overwrite=False で送り先に同名フォルダがある → False を返す
      （呼び出し側で確認ダイアログを出す想定）
    - overwrite=True → 退避してからコピーし、控えは backup_keep 世代だけ残す

    戻り値: (送り先パス, 退避先パス or None) / False（上書き確認が必要なとき）
    """
    ignore = _with_google_docs(ignore)
    folder_name = os.path.basename(src.rstrip("\\/"))
    dest = os.path.join(push_dest, folder_name)
    log.info("Drive へ送る: %s → %s", src, dest)

    if not os.path.isdir(src):
        raise OSError(f"送るフォルダがありません: {src}")

    os.makedirs(push_dest, exist_ok=True)

    backup = None
    if os.path.exists(dest):
        if not overwrite:
            log.warning("送り先に同名フォルダが既にあります（上書き確認が必要）: %s", dest)
            return False
        # 消さずにリネームで退避（ここが「怖くない」の要）
        backup = os.path.join(push_dest, folder_name + _BKUP_MARK + datetime.now().strftime(_STAMP_FMT))
        os.rename(dest, backup)
        log.warning("上書き前に控えを作りました: %s", backup)

    try:
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*ignore))
    except Exception:
        # コピーに失敗したら控えを元の名前に戻す（中途半端な状態を残さない）
        if backup and not os.path.exists(dest):
            os.rename(backup, dest)
            log.error("コピーに失敗したので控えを元に戻しました: %s", dest)
        raise

    log.info("送信完了: %s", dest)
    if backup:
        _trim_backups(push_dest, folder_name, backup_keep)
    return dest, backup


def restore_backup(push_dest, folder_name):
    """
    一番新しい控えで送り先を元に戻す（送ったあと「やっぱり戻したい」用）。

    今の folder_name を捨てて、最新の `名前_bkup_日時` を folder_name にリネームし直す。
    戻り値: 戻した控えの名前 / None（控えが無い）
    """
    backups = _backup_dirs(push_dest, folder_name)
    if not backups:
        log.warning("控えがありません: %s の中に %s%s* が無い", push_dest, folder_name, _BKUP_MARK)
        return None

    newest = backups[-1]
    dest = os.path.join(push_dest, folder_name)
    if os.path.exists(dest):
        shutil.rmtree(dest)  # 送った直後の物を捨てる
        log.warning("送信後のフォルダを削除: %s", dest)
    os.rename(os.path.join(push_dest, newest), dest)
    log.info("控えから復元しました: %s → %s", newest, folder_name)
    return newest


# =====================================================================
# 開く
# =====================================================================
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
