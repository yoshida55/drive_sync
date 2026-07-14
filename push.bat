@echo off
chcp 65001 >nul
cd /d %~dp0
echo === まず最新を取得（pull）===
git pull
echo.
echo === 変更をコミットして送信（push）===
git add -A
git commit -m "update %date% %time%"
git push
echo.
echo 完了しました。
pause
