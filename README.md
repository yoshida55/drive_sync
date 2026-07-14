# Google Drive → VS Code オープナー

Google Drive（ドライブとしてマウント済み・例 `G:\`）の中から、名前の一部を入力するだけで
プロジェクトをローカルにコピーして VS Code で開くツールです。

## しくみ（安全設計）

- Google Drive 側は **読むだけ**（コピー元）。編集はローカルのコピーで行う。
- **Drive へ書き戻す機能はありません**（人のフォルダを上書きする事故を防ぐため）。
- Google Drive API・認証は不要。ドライブ文字（G: など）越しの普通のフォルダ操作だけで動きます。

## 使い方

```
名前の一部を入力（例「栗」「共通」）
  ↓ 親フォルダ直下のフォルダを部分一致で検索
ヒットが複数 → 一覧から選ぶ
  ↓
選んだフォルダの中のフォルダが
  1個 → そのままコピー＆VS Codeで開く
  複数 → 「どれを持ってきますか？」と警告 → 選んでから開く
```

## 起動

```powershell
# 初回だけ：仮想環境を作る（任意。標準ライブラリのみなので無くても動く）
python -m venv venv
venv\Scripts\activate

# 起動
python main.py
```

> tkinter は Python 標準搭載なので追加インストールは不要です。

## 設定（config.json）

画面右上の「設定」ボタンから変更できます（`config.json` に保存）。

| キー | 意味 |
|---|---|
| `parent_folder` | 検索元。Google Drive 上の親フォルダ |
| `copy_dest` | コピー先。ローカルの好きな場所 |
| `ignore` | コピー時に無視するファイル名（`desktop.ini` 等） |

例：
```json
{
  "parent_folder": "G:\\マイドライブ\\00_リンクワークス\\test",
  "copy_dest": "D:\\work",
  "ignore": ["desktop.ini", "Thumbs.db"]
}
```

## ファイル構成

| ファイル | 役割 |
|---|---|
| `main.py` | GUI（画面・ボタン） |
| `core.py` | 検索・コピー・VS Code起動のロジック |
| `config.json` | 設定 |

## 補足

- VS Code を開くのに `code` コマンドを使います。もし起動しない場合は VS Code で
  `Ctrl+Shift+P` → `Shell Command: Install 'code' command in PATH` を実行してください。
