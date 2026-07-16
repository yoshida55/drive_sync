# -*- coding: utf-8 -*-
"""
main.py … GUI（tkinter）

使い方：
  1) 入力欄に名前の一部を入れて「検索」（例「栗」「共通」）
  2) 親フォルダ直下のヒットが複数なら一覧から選ぶ
  3) 選んだフォルダの中のサブフォルダが
       0件 → 中身がテキスト等だけなので、そのフォルダ自体を丸ごと持ってくる
       1件 → 有無を言わさずコピー＆VS Codeで開く
       複数 → 「どれを持ってきますか？」と一覧で選ばせる
  4) 編集したら「Drive へ送る」で書き戻す。送り先は持ってきた元が既定（変更もできる）。
  「設定」ボタンで 親フォルダ・コピー先・送り先 を変更できる。
"""

import os
import shutil
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

        # 一番下：開くボタン（2種類）
        bottom = tk.Frame(self)
        bottom.pack(fill="x", **pad)
        tk.Button(bottom, text="コピーして VS Code で開く（ダブルクリックと同じ）",
                  command=lambda: self.bring_selected_sub("vscode")).pack(fill="x", pady=(0, 3))
        tk.Button(bottom, text="コピーしてフォルダを開く（エクスプローラー）",
                  command=lambda: self.bring_selected_sub("explorer")).pack(fill="x")

        # 送信ボタンだけ Drive に書き込む＝押し間違えると困るので、離して赤字にする
        tk.Button(bottom, text="▲ Drive へ送る（上書き）", fg="#b00020",
                  command=self.push_selected_sub).pack(fill="x", pady=(10, 0))

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
            # 中にフォルダが無い＝このフォルダ自体が中身（テキストだけ等）→ 丸ごと持ってくる
            log.info("「%s」の中にフォルダが無いので、フォルダごと持ってきます", target["display"])
            self._bring(target)
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
    def bring_selected_sub(self, opener="vscode"):
        idx = self._selected_index(self.sub_list)
        if idx is None:
            messagebox.showinfo("お知らせ", "中のフォルダを選んでください。")
            return
        self._bring(self._sub_hits[idx], opener=opener)

    _LOCK_HINT = (
        "同じフォルダを VS Code で開いていると、使用中で上書き・削除ができません。\n"
        "そのフォルダを開いている VS Code を閉じてから、もう一度お試しください。"
    )

    def _bring(self, sub, opener="vscode"):
        """1つのサブフォルダをコピー先へコピーして開く。
        opener="vscode" … VS Code で開く / opener="explorer" … エクスプローラーで開く。
        """
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

        except shutil.Error as e:
            # 一部のファイルだけ失敗した場合。フォルダ自体はできているので、
            # 何が来なかったかを正直に見せる（ロックのせいだと決めつけない）
            log.error("一部のファイルをコピーできませんでした: %s", e)
            messagebox.showwarning(
                "一部のファイルが来ませんでした",
                f"「{folder_name}」は持ってきましたが、次のファイルはコピーできませんでした：\n\n"
                + self._failed_names(e) + "\n\n"
                "そのファイル以外は揃っています。",
            )
            return
        except OSError as e:
            # WinError 32 など「使用中で消せない」系はここで優しく案内（落とさない）
            log.error("コピー処理でエラー: %s", e)
            messagebox.showerror(
                "コピーできませんでした",
                f"「{folder_name}」をコピーできませんでした。\n\n{e}\n\n" + self._LOCK_HINT,
            )
            return

        if not result:
            messagebox.showerror("エラー", "コピーに失敗しました。ログを確認してください。")
            return

        # 持ってきた元を覚えておく。Drive へ送るときは、ここが戻し先になる
        core.remember_origin(self.cfg, folder_name, src)

        # Google書類は中身がネット上にあるので持ってこられない。黙って消えると混乱するので伝える
        skipped = core.find_google_docs(src)
        if skipped:
            messagebox.showinfo(
                "Google の書類は持ってこられません",
                "次のファイルは Google ドキュメント系なので、持ってこられませんでした：\n\n"
                + "\n".join("・" + s for s in skipped) + "\n\n"
                "中身が Google のサーバー上にあり、パソコン側にはリンクだけがあるためです。\n"
                "編集したいときはブラウザで開いてください。\n\n"
                "※ Drive 側には残っているので、消えたわけではありません。",
            )

        # コピー後、指定された方法で開く
        if opener == "explorer":
            if core.open_in_explorer(result):
                messagebox.showinfo("完了", f"コピーしてフォルダを開きました：\n{result}")
            else:
                messagebox.showwarning(
                    "フォルダを開けません",
                    f"コピーは完了しました：\n{result}\n\n"
                    "エクスプローラーの起動に失敗しました。手動で開いてください。",
                )
        else:
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
    # ④ ローカルで編集したものを Drive へ送る（上書き）
    # ---------------------------------------------------------------
    def push_selected_sub(self):
        """ローカル（copy_dest）のプロジェクトを選んで、送り先（push_dest）へ書き戻す。

        送るものはローカルにしかないので、選ぶ一覧も Drive 側（①②）ではなくローカルから作る。
        （Drive 側から選ぶ作りにすると、Drive がまだ空のときに一生送れなくなる）
        """
        copy_dest = self.cfg["copy_dest"]
        keep = self.cfg.get("push_backup_keep", 3)
        ignore = self.cfg.get("push_ignore", self.cfg.get("ignore", []))

        if not os.path.isdir(copy_dest):
            messagebox.showerror(
                "送るものがありません",
                f"ローカルのコピー先がありません：\n{copy_dest}\n\n"
                "先に『コピーして VS Code で開く』で持ってきてください。",
            )
            return

        name = self._choose_local_project(copy_dest)
        if name is None:
            return
        src = os.path.join(copy_dest, name)

        # 戻し先は「持ってきた元」を既定にする。記録が無ければ設定の送り先を出しておく
        origin = core.get_origin(self.cfg, name)
        default_parent = os.path.dirname(origin) if origin else self.cfg.get("push_dest", "")

        dest_parent = self._ask_push_dest(name, src, default_parent, origin)
        if dest_parent is None:
            return

        try:
            result = core.push_project(src, dest_parent, ignore=ignore, overwrite=True, backup_keep=keep)
        except OSError as e:
            log.error("送信でエラー: %s", e)
            messagebox.showerror(
                "送れませんでした",
                f"「{name}」を送れませんでした。\n\n{e}\n\n" + self._LOCK_HINT,
            )
            return

        dest, backup = result
        # 「今この場所へ送った」を記録。次に開いたとき、この更新を他人の編集と誤解しないため
        core.remember_origin(self.cfg, name, dest)

        msg = f"Drive へ送りました：\n{dest}"
        if backup:
            msg += (f"\n\n上書き前の控えを残しています：\n{os.path.basename(backup)}\n"
                    "おかしくなったら、この控えを元の名前にリネームすれば戻せます。")
        messagebox.showinfo("送信完了", msg)

    def _choose_local_project(self, copy_dest):
        """ローカルのプロジェクトを1つ選ばせる。戻り値: 実フォルダ名 / None（やめた）。"""
        projects = core.list_subfolders(copy_dest)
        if not projects:
            messagebox.showinfo(
                "送るものがありません",
                f"ローカルにプロジェクトがありません：\n{copy_dest}",
            )
            return None
        if len(projects) == 1:
            return projects[0]["name"]  # 1つだけなら選ぶ手間はいらない（確認は次で出る）

        win = tk.Toplevel(self)
        win.title("どれを Drive へ送りますか？")
        win.geometry("420x300")
        win.transient(self)
        win.grab_set()

        tk.Label(win, text=f"送るプロジェクトを選んでください（{copy_dest}）",
                 anchor="w").pack(fill="x", padx=8, pady=6)
        box = tk.Listbox(win)
        box.pack(fill="both", expand=True, padx=8)
        for p in projects:
            box.insert(tk.END, p["display"])
        box.selection_set(0)

        picked = {"name": None}

        def ok():
            i = self._selected_index(box)
            if i is not None:
                picked["name"] = projects[i]["name"]
            win.destroy()

        btns = tk.Frame(win)
        btns.pack(fill="x", padx=8, pady=8)
        tk.Button(btns, text="この中身を送る", command=ok).pack(side="right")
        tk.Button(btns, text="やめる", command=win.destroy).pack(side="right", padx=6)
        box.bind("<Double-Button-1>", lambda e: ok())

        self.wait_window(win)  # 選び終わるまで待つ
        return picked["name"]

    def _ask_push_dest(self, name, src, default_parent, origin):
        """
        送る前の最終確認。戻し先（持ってきた元）を最初から入れておき、必要なら変更させる。

        戻り値: 送り先の親フォルダ / None（やめた）
        """
        win = tk.Toplevel(self)
        win.title("Drive へ送る確認")
        win.geometry("660x360")
        win.transient(self)
        win.grab_set()

        parent_var = tk.StringVar(value=default_parent)
        picked = {"parent": None}

        tk.Label(win, text=f"「{name}」を Drive へ送ります", font=("", 11, "bold"),
                 anchor="w").pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(win, text=f"送るもの： {src}", anchor="w", fg="#555").pack(fill="x", padx=12)

        # 送り先の行（既定は持ってきた元。変更ボタンで別のフォルダにもできる）
        row = tk.Frame(win)
        row.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(row, text="送り先：").pack(side="left")
        dest_label = tk.Label(row, text="", anchor="w", fg="#1565c0")
        dest_label.pack(side="left", fill="x", expand=True)
        tk.Button(row, text="変更", command=lambda: pick()).pack(side="right")

        status = tk.Label(win, text="", justify="left", anchor="nw")
        status.pack(fill="both", expand=True, padx=12, pady=8)

        def refresh():
            """送り先が変わるたびに、行き先と Drive 側の状態を出し直す。"""
            parent = parent_var.get()
            dest = os.path.join(parent, name)
            dest_label.config(text=dest)

            lines = []
            if not os.path.isdir(parent):
                status.config(text="⚠ この送り先が見つかりません。「変更」で選び直してください。", fg="#b00020")
                send_btn.config(state="disabled")
                return
            send_btn.config(state="normal")

            # 元の場所から外れていないか（案C の肝。外れているときだけ強く出す）
            if origin and not core.same_path(parent, os.path.dirname(origin)):
                lines.append("⚠ 持ってきた元とは違う場所です。")
                lines.append(f"　 元の場所： {os.path.dirname(origin)}")
                lines.append("")
            elif not origin:
                lines.append("⚠ 持ってきた記録がありません（このPCでコピーしていない）。")
                lines.append("　 送り先が合っているか、よく確かめてください。")
                lines.append("")

            # 「Drive とローカル、どっちが新しいか」では判定しない。
            # 自分が送れば Drive は必ず新しくなるので、毎回オオカミ少年になるため。
            others, dest_time = core.touched_by_others(self.cfg, name, dest)
            last_sync = core.get_last_sync(self.cfg, name)

            if dest_time is None:
                lines.append("Drive側　： まだありません（新規で置きます）")
            else:
                lines.append(f"Drive側　： 既にあります（最終更新 {dest_time:%Y-%m-%d %H:%M}）")
                if last_sync:
                    lines.append(f"最後の同期： {last_sync:%Y-%m-%d %H:%M}（あなたが持ってきた／送った時刻）")
                lines.append("")
                lines.append("上書きしますが、今の Drive の中身は控えとして残します。")
                if others:
                    lines.append("")
                    lines.append("⚠ あなたが最後に触ったあとに、Drive側が更新されています。")
                    lines.append("　 他のPC・他の人の編集を消してしまうかもしれません。")

                # Google書類は持ってこられない＝ローカルに無い。このまま送ると本体から消える
                docs = core.find_google_docs(dest)
                if docs:
                    lines.append("")
                    lines.append(f"⚠ 送り先に Google の書類が {len(docs)} 件あります。")
                    lines.append("　 これは持ってこられないファイルなので、送ると本体から消えます。")
                    lines.append("　 （控えの中には残るので、あとで戻せます）")
                    for d in docs[:5]:
                        lines.append("　 ・" + d)

            lines.append("")
            lines.append("送信すると Google Drive の同期で他の人にも反映されます。")

            warn = any(ln.startswith("⚠") for ln in lines)
            status.config(text="\n".join(lines), fg="#b00020" if warn else "#333")

        def pick():
            d = filedialog.askdirectory(initialdir=parent_var.get() or "/")
            if d:
                parent_var.set(os.path.normpath(d))
                refresh()

        def send():
            parent = parent_var.get()
            # 元の場所から外れているときだけ、もう一段確認する
            if origin and not core.same_path(parent, os.path.dirname(origin)):
                ok = messagebox.askyesno(
                    "元の場所と違います",
                    f"「{name}」は本来ここから来ました：\n{os.path.dirname(origin)}\n\n"
                    f"でも、今の送り先はここです：\n{parent}\n\n"
                    "別の場所に置くことになります（元の場所のフォルダはそのまま残ります）。\n"
                    "本当にここへ送りますか？",
                    parent=win,
                )
                if not ok:
                    return
            picked["parent"] = parent
            win.destroy()

        btns = tk.Frame(win)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        send_btn = tk.Button(btns, text="この場所へ送る", fg="#b00020", command=send)
        send_btn.pack(side="right")
        tk.Button(btns, text="やめる", command=win.destroy).pack(side="right", padx=6)

        refresh()
        self.wait_window(win)
        return picked["parent"]

    # ---------------------------------------------------------------
    # 設定画面
    # ---------------------------------------------------------------
    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("設定")
        win.geometry("640x480")
        win.transient(self)
        win.grab_set()

        parent_var = tk.StringVar(value=self.cfg["parent_folder"])
        dest_var = tk.StringVar(value=self.cfg["copy_dest"])
        push_var = tk.StringVar(value=self.cfg.get("push_dest", ""))
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
        row("送り先（Drive・上書き）：", push_var, 2)

        # 掃除トグル（コピー先は専用フォルダ前提の注意つき）
        tk.Checkbutton(
            win, variable=clean_var,
            text="開く前にコピー先の古いフォルダを削除する（コピー先は専用フォルダにすること）",
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=4)

        # 3つの設定が何をするのか、文字だけだと頭に入らないので図で見せる
        self._draw_settings_diagram(win).grid(row=4, column=0, columnspan=3, padx=8, pady=8)
        tk.Label(
            win, fg="#666", justify="left", anchor="w",
            text="※ 送り先は、送るときに1件ずつ変えられます（持ってきた元が最初から入ります）",
        ).grid(row=5, column=0, columnspan=3, sticky="w", padx=10)

        def save():
            self.cfg["parent_folder"] = parent_var.get().strip()
            self.cfg["copy_dest"] = dest_var.get().strip()
            self.cfg["push_dest"] = push_var.get().strip()
            self.cfg["clean_before_open"] = clean_var.get()
            core.save_config(self.cfg)
            self._refresh_parent_label()
            win.destroy()
            messagebox.showinfo("保存しました", "設定を保存しました。")

        tk.Button(win, text="保存", command=save).grid(row=6, column=1, sticky="e", pady=12)

    @staticmethod
    def _draw_settings_diagram(win):
        """
        設定3つの関係を図にする（Canvas に直接描く）。

        tkinter は SVG を表示できないので、線と四角で同じ絵を描いている。
        追加ライブラリが要らないので、exe にしても崩れない。
        """
        c = tk.Canvas(win, width=600, height=190, bg="#fbfbfb",
                      highlightthickness=1, highlightbackground="#dddddd")

        # 左：Google ドライブ側
        c.create_rectangle(15, 28, 240, 168, outline="#c9d4e5", fill="#f2f7fd")
        c.create_text(127, 43, text="Google ドライブ（G:）", fill="#3a5a8c", font=("", 9, "bold"))
        c.create_rectangle(30, 60, 225, 92, outline="#d9a406", fill="#fff8e1")
        c.create_text(127, 70, text="親フォルダ（検索元）", font=("", 9))
        c.create_text(127, 84, text="ここを名前で探す", fill="#777", font=("", 8))
        c.create_rectangle(30, 120, 225, 152, outline="#b00020", fill="#fdeef1")
        c.create_text(127, 130, text="送り先（Drive・上書き）", font=("", 9))
        c.create_text(127, 144, text="ここへ書き戻す", fill="#777", font=("", 8))

        # 右：パソコン側
        c.create_rectangle(375, 28, 585, 168, outline="#c9d4e5", fill="#f2f7fd")
        c.create_text(480, 43, text="パソコン", fill="#3a5a8c", font=("", 9, "bold"))
        c.create_rectangle(390, 90, 570, 122, outline="#d9a406", fill="#fff8e1")
        c.create_text(480, 100, text="コピー先（ローカル）", font=("", 9))
        c.create_text(480, 114, text="ここで編集する", fill="#777", font=("", 8))

        # 取ってくる（青）
        c.create_line(228, 76, 388, 96, arrow="last", fill="#1565c0", width=2)
        c.create_text(307, 60, text="① 探す → ② 持ってくる", fill="#1565c0", font=("", 9, "bold"))

        # 送る（赤）
        c.create_line(388, 116, 228, 136, arrow="last", fill="#b00020", width=2)
        c.create_text(307, 152, text="③ 送る（上書き）", fill="#b00020", font=("", 9, "bold"))
        return c

    # ---------------------------------------------------------------
    # 小道具
    # ---------------------------------------------------------------
    @staticmethod
    def _selected_index(listbox):
        sel = listbox.curselection()
        return sel[0] if sel else None

    @staticmethod
    def _failed_names(err):
        """shutil.Error の中身（[(元, 先, 理由), ...]）を読める形にする。"""
        try:
            return "\n".join(f"・{os.path.basename(src)}（{why}）"
                             for src, _dst, why in err.args[0])
        except Exception:  # noqa: BLE001  形が違っても落とさない
            return str(err)


if __name__ == "__main__":
    App().mainloop()
