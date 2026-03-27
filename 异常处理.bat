@echo off
setlocal

:: 确保在脚本所在目录执行
cd /d "%~dp0"

echo 正在处理可能发生的错误...

:: 删除 .git 文件夹
if exist ".git" (
    echo 正在清理 .git 文件夹 以解决更新错误...
    :: 清除可能存在的只读/隐藏属性，防止 rd 命令失败
    attrib -h -r -s ".git" /s /d >nul 2>&1
    rd /s /q ".git"
)

:: 结束所有 Python 相关进程
echo 正在结束 Python 相关进程 以解决卡死问题...
taskkill /f /im python.exe /t >nul 2>&1
taskkill /f /im pythonw.exe /t >nul 2>&1

:: 启动先安装我.exe并请求管理员权限
if exist "先安装我.exe" (
    echo 正在启动VC++运行库安装程序 请根据指示安装...
    powershell -Command "Start-Process '先安装我.exe' -Verb RunAs"
) else (
    echo 错误：未找到 "先安装我.exe"
    pause
)

echo 处理完毕。
exit
