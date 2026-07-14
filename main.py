# -*- coding: utf-8 -*-
"""
main.py … GUI（tkinter）

使い方：
  1) 入力欄に名前の一部を入れて「検索」（例「栗」「共通」）
  2) 親フォルダ直下のヒットが複数なら一覧から選ぶ
  3) 選んだフォルダの中のサブフォルダが
       1件 → 有無を言わさずコピー＆VS Codeで開く
       複数 → 「どれを持ってきますか？」と一覧で選ばせる
  「設定」ボタンで 親フォルダ と コピー先 を変更できる。
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import core

log = core.log


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Google Drive → VS Code オープナー")
        self.geometry("560x460")

        self.cfg = core.load_config()

        # 現在の検索ヒット・サブフォルダ候補を覚えておく入れ物
        self._folder_hits = []   # 親直下のヒット
        self._sub_hits = []      # 選んだフォルダ内のサブフォルダ

        self._build_ui()
        self._refresh_parent_label()

    # ---------------------------------------------------------------
    # 画面の組み立て
    # ---------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # 上：親フォルダ表示 ＋ 設定ボタン
        top = tk.Frame(self)
        top.pack(fill="x", **pad)
        self.parent_label = tk.Label(top, text="", anchor="w", fg="#555")
        self.parent_label.pack(side="left", fill="x", expand=True)
        tk.Button(top, text="設定", command=self.open_settings).pack(side="right")

        # 検索欄
        search = tk.Frame(self)
        search.pack(fill="x", **pad)
        tk.Label(search, text="名前の一部：").pack(side="left")
        self.entry = tk.Entry(search)
        self.entry.pack(side="left", fill="x", expand=True, padx=4)
        self.entry.bind("<Return>", lambda e: self.do_search())
        tk.Button(search, text="検索", command=self.do_search).pack(side="left")

        # 検索結果（親直下フォルダ）
        tk.Label(self, text="① 見つかったフォルダ（ダブルクリックで中を見る）",
                 anchor="w").pack(fill="x", padx=8)
        self.folder_list = tk.Listbox(self, height=6)
        self.folder_list.pack(fill="both", expand=True, padx=8)
        self.folder_list.bind("<Double-Button-1>", lambda e: self.open_folder())

        # サブフォルダ（プロジェクト候補）
        tk.Label(self, text="② 中のフォルダ（複数あるときはここで選ぶ）",
                 anchor="w").pack(fill="x", padx=8, pady=(8, 0))
        self.sub_list = tk.Listbox(self, height=6)
        self.sub_list.pack(fill="both", expand=True, padx=8)
        self.sub_list.bind("<Double-Button-1>", lambda e: self.bring_selected_sub())

        # 一番下：開くボタン
        bottom = tk.Frame(self)
        bottom.pack(fill="x", **pad)
        tk.Button(bottom, text="選んだフォルダをコピーして VS Code で開く",
                  command=self.bring_selected_sub).pack(fill="x")

    def _refresh_parent_label(self):
        self.parent_label.config(text=f"親フォルダ： {self.cfg['parent_folder']}")

    # ---------------------------------------------------------------
    # ① 検索
    # ---------------------------------------------------------------
    def do_search(self):
        keyword = self.entry.get()
        parent = self.cfg["parent_folder"]
        if not os.path.isdir(parent):
            messagebox.showerror("エラー", f"親フォルダが見つかりません：\n{parent}\n\n「設定」で見直してください。")
            return

        self._folder_hits = core.find_folders(parent, keyword)
        self.folder_list.delete(0, tk.END)
        self.sub_list.delete(0, tk.END)
        self._sub_hits = []

        if not self._folder_hits:
            messagebox.showinfo("検索結果", "見つかりませんでした。")
            return

        for h in self._folder_hits:
            self.folder_list.insert(tk.END, h["display"])

        # 1件だけならそのまま中を見る（自動で②へ進む）
        if len(self._folder_hits) == 1:
            self.folder_list.selection_set(0)
            self.open_folder()

    # ---------------------------------------------------------------
    # ② 選んだフォルダの中を見る → サブフォルダ数で分岐
    # ---------------------------------------------------------------
    def open_folder(self):
        idx = self._selected_index(self.folder_list)
        if idx is None:
            messagebox.showinfo("お知らせ", "フォルダを選んでください。")
            return

        target = self._folder_hits[idx]
        self._sub_hits = core.list_subfolders(target["path"])
        self.sub_list.delete(0, tk.END)

        if not self._sub_hits:
            messagebox.showinfo("お知らせ", f"「{target['display']}」の中に開けるフォルダがありません。")
            return

        for s in self._sub_hits:
            self.sub_list.insert(tk.END, s["display"])

        if len(self._sub_hits) == 1:
            # 1件 → 有無を言わさず開く
            self._bring(self._sub_hits[0])
        else:
            # 複数 → 警告して選ばせる
            self.sub_list.selection_set(0)
            messagebox.showwarning(
                "複数フォルダあり",
                f"「{target['display']}」の中にフォルダが {len(self._sub_hits)} 個あります。\n"
                "下の一覧からどれを持ってくるか選んで、\n"
                "『コピーして VS Code で開く』を押してください。",
            )

    # ---------------------------------------------------------------
    # ③ 選んだサブフォルダをコピーして開く
    # ---------------------------------------------------------------
    def bring_selected_sub(self):
        idx = self._selected_index(self.sub_list)
        if idx is None:
            messagebox.showinfo("お知らせ", "中のフォルダを選んでください。")
            return
        self._bring(self._sub_hits[idx])

    _LOCK_HINT = (
        "同じフォルダを VS Code で開いていると、使用中で上書き・削除ができません。\n"
        "そのフォルダを開いている VS Code を閉じてから、もう一度お試しください。"
    )

    def _bring(self, sub):
        """1つのサブフォルダをコピー先へコピーして VS Code で開く。"""
        src = sub["path"]
        dest_root = self.cfg["copy_dest"]
        ignore = self.cfg.get("ignore", [])
        folder_name = os.path.basename(src.rstrip("\\/"))

        try:
            # 設定がONなら、コピー先の古いフォルダを先に掃除する
            if self.cfg.get("clean_before_open"):
                removed, failed = core.clean_dest(dest_root)
                if failed:
                    messagebox.showwarning(
                        "使用中で削除できないフォルダがあります",
                        "次のフォルダは使用中のため削除できませんでした：\n"
                        + "、".join(failed) + "\n\n" + self._LOCK_HINT,
                    )

            # コピー（既存なら上書き確認）
            result = core.copy_project(src, dest_root, ignore=ignore, overwrite=False)
            if result is False:
                ans = messagebox.askyesno(
                    "上書き確認",
                    f"コピー先に「{folder_name}」が既にあります。\n上書きしますか？\n\n"
                    f"（コピー先：{dest_root}）",
                )
                if not ans:
                    return
                result = core.copy_project(src, dest_root, ignore=ignore, overwrite=True)

        except OSError as e:
            # WinError 32 など「使用中で消せない」系はここで優しく案内（落とさない）
            log.error("コピー処理でエラー: %s", e)
            messagebox.showerror(
                "コピーできませんでした",
                f"「{folder_name}」をコピーできませんでした。\n\n" + self._LOCK_HINT,
            )
            return

        if not result:
            messagebox.showerror("エラー", "コピーに失敗しました。ログを確認してください。")
            return

        # VS Code で開く
        if core.open_in_vscode(result):
            messagebox.showinfo("完了", f"コピーして VS Code で開きました：\n{result}")
        else:
            messagebox.showwarning(
                "VS Code が起動できません",
                f"コピーは完了しました：\n{result}\n\n"
                "VS Code の `code` コマンドが使えない可能性があります。\n"
                "（VS Code で Ctrl+Shift+P → 'Shell Command: Install code command in PATH'）",
            )

    # ---------------------------------------------------------------
    # 設定画面
    # ---------------------------------------------------------------
    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("設定")
        win.geometry("560x230")
        win.transient(self)
        win.grab_set()

        parent_var = tk.StringVar(value=self.cfg["parent_folder"])
        dest_var = tk.StringVar(value=self.cfg["copy_dest"])
        clean_var = tk.BooleanVar(value=self.cfg.get("clean_before_open", False))

        def row(label, var, r):
            tk.Label(win, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=8)
            ent = tk.Entry(win, textvariable=var, width=48)
            ent.grid(row=r, column=1, padx=4)

            def pick():
                d = filedialog.askdirectory(initialdir=var.get() or "/")
                if d:
                    var.set(os.path.normpath(d))
            tk.Button(win, text="参照", command=pick).grid(row=r, column=2, padx=4)

        row("親フォルダ（検索元）：", parent_var, 0)
        row("コピー先（ローカル）：", dest_var, 1)

        # 掃除トグル（コピー先は専用フォルダ前提の注意つき）
        tk.Checkbutton(
            win, variable=clean_var,
            text="開く前にコピー先の古いフォルダを削除する（コピー先は専用フォルダにすること）",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=4)

        def save():
            self.cfg["parent_folder"] = parent_var.get().strip()
            self.cfg["copy_dest"] = dest_var.get().strip()
            self.cfg["clean_before_open"] = clean_var.get()
            core.save_config(self.cfg)
            self._refresh_parent_label()
            win.destroy()
            messagebox.showinfo("保存しました", "設定を保存しました。")

        tk.Button(win, text="保存", command=save).grid(row=3, column=1, sticky="e", pady=12)

    # ---------------------------------------------------------------
    # 小道具
    # ---------------------------------------------------------------
    @staticmethod
    def _selected_index(listbox):
        sel = listbox.curselection()
        return sel[0] if sel else None


if __name__ == "__main__":
    App().mainloop()
