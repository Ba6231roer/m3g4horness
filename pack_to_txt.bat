@echo off
setlocal
chcp 65001 >nul
title m3g4horness pack zip-to-txt
cd /d "%~dp0"

set "TAG=megahorness"

echo ==================================================
echo  打包项目为 yyyymmdd_NN_%TAG%.txt
echo  排除: .codegraph .git .claude .obsidian .pytest_cache
echo        .validate-webgoat .venv node_modules __pycache__
echo        根目录 docs^、new_issue*、task.NNNN.md、历史产物
echo ==================================================
echo.

REM ---- 1) 计算目标名 yyyymmdd_序号_%TAG% (PowerShell 生成,避免 %DATE% 区域差异) ----
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=(Get-Date).ToString('yyyyMMdd');$max=0;foreach($f in Get-ChildItem -File){if($f.Name -match ('^'+$d+'_(\d{2})_%TAG%\.(zip|txt)$')){$n=[int]$Matches[1];if($n -gt $max){$max=$n}}};$next=$max+1;Write-Output ($d+'_'+$next.ToString('00')+'_%TAG%')" > "%TEMP%\mgh_pack_name.txt"
set /p NAME=<"%TEMP%\mgh_pack_name.txt"
del "%TEMP%\mgh_pack_name.txt" >nul 2>&1

if "%NAME%"=="" (
  echo [错误] 无法生成包名,请确认 PowerShell 可用。
  pause
  exit /b 1
)

set "ZIP=%NAME%.zip"
set "TXT=%NAME%.txt"

echo 目标文件: %TXT%
echo.

REM ---- 2) 打包 (tar 为 Win10/11 内置;cwd 已是项目根,不用 -C) ----
REM bsdtar notes (verified via cmd-channel matrix on Win11 System32 tar):
REM  - pattern without "/" (e.g. "task*.md") matches basename at ANY depth -> killed openspec/**/tasks.md
REM  - "./name/" (trailing slash) matches NOTHING -> whole tree leaks; use "./name" + "./name/*"
REM  - "./task.[0-9]*.md" kills root task.NNNN.md but keeps openspec/**/tasks.md
tar -a -c -f "%ZIP%" ^
  --exclude="./.codegraph" ^
  --exclude="./.git" ^
  --exclude="./.pytest_cache" ^
  --exclude="./.obsidian" ^
  --exclude="./.validate-webgoat" ^
  --exclude="./.claude" ^
  --exclude="./.venv" ^
  --exclude="./node_modules" ^
  --exclude="./docs" ^
  --exclude="./docs/*" ^
  --exclude="./new_issue[0-9]*" ^
  --exclude="./task.[0-9]*.md" ^
  --exclude="__pycache__" ^
  --exclude="./*_%TAG%.txt" ^
  --exclude="./*_%TAG%.zip" ^
  .

if errorlevel 1 (
  echo [错误] tar 打包失败。
  pause
  exit /b 1
)

REM ---- 3) 改名 .zip -> .txt ----
move /y "%ZIP%" "%TXT%" >nul
if errorlevel 1 (
  echo [错误] 重命名为 .txt 失败。
  pause
  exit /b 1
)

REM ---- 4) 校验产物可正常读回 ----
tar -tf "%TXT%" >nul 2>&1
if errorlevel 1 (
  echo [错误] 产物校验失败。
  pause
  exit /b 1
)

powershell -NoProfile -Command "Write-Output ([math]::Round((Get-Item ('%TXT%')).Length/1KB,1).ToString()+' KB')" > "%TEMP%\mgh_size.txt"
set /p SIZE=<"%TEMP%\mgh_size.txt"
del "%TEMP%\mgh_size.txt" >nul 2>&1

echo.
echo 完成: %TXT%  ( %SIZE% )
echo ==================================================
pause
