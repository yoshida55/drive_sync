@echo off
chcp 65001 >nul
cd /d %~dp0
echo === GitHub から最新を取得（pull）===
git pull
echo.
echo 完了しました。
pause
