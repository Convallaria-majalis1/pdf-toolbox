@echo off
chcp 65001 >nul
cd /d "%~dp0"
title PDF 批处理器
python -m pip install -r requirements.txt -q
python main.py
if errorlevel 1 pause
