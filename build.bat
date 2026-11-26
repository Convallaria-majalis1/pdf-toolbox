@echo off
chcp 65001 >nul
title 打包PDF批处理器

echo ==========================================
echo  第 1 步：安装依赖
echo ==========================================
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error

echo.
echo ==========================================
echo  第 2 步：打包成单个 exe
echo ==========================================
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PdfToolbox main.py
if errorlevel 1 goto :error

echo.
echo ==========================================
echo  完成！exe 在 dist\PdfToolbox.exe
echo ==========================================
pause
exit /b 0

:error
echo.
echo 出错了，把上面的报错信息发给我。
pause
exit /b 1
