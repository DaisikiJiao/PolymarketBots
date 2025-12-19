@echo off
setlocal enabledelayedexpansion
set "PROXY_VALUE="

REM 1. 使用 findstr 找到以 LOCAL_HTTPS_PROXY 开头的行，并用 for 分割
for /f "tokens=2 delims==" %%i in ('findstr /b "LOCAL_HTTPS_PROXY" .env') do (
    set "PROXY_VALUE=%%i"
)

REM 2. 检查是否成功获取到值
if defined PROXY_VALUE (
    echo 找到代理配置: !PROXY_VALUE!
    REM 3. 使用获取到的值设置系统代理变量
    set http_proxy=!PROXY_VALUE!
    set https_proxy=!PROXY_VALUE!
    echo 已设置 http_proxy 和 https_proxy。
) else (
    echo 未在 .env 文件中找到 LOCAL_HTTPS_PROXY 配置。
)

REM 4. 在此处继续执行你的其他命令，启动Python脚本
.\.venv\Scripts\python.exe .\actuator.py

endlocal
pause