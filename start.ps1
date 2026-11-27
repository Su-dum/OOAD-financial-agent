#!/usr/bin/env pwsh
#Requires -Version 5.1
# 本文件必须以 UTF-8 BOM 保存，否则 Windows PowerShell 5.1 会按 GBK 解码导致中文乱码。
<#
.SYNOPSIS
    一键启动「金融分析与监控智能体」：后端 FastAPI + 前端 Vite。

.DESCRIPTION
    做四件事：
      1. 检查环境（.venv / frontend/node_modules / 端口占用）
      2. 后台拉起后端  scripts/run_api.py   -> http://127.0.0.1:8000
      3. 轮询 /api/health 直到就绪（默认最多等 90s）
      4. 后台拉起前端  vite                 -> http://127.0.0.1:5173
    日志写到 logs\backend.log / logs\frontend.log，
    PID 写到 logs\dev-servers.json，供 .\stop.ps1 精确关闭。

.EXAMPLE
    .\start.ps1
        # 启动前后端并自动打开浏览器

.EXAMPLE
    .\start.ps1 -BackendOnly
        # 只起后端（改后端/跑接口验收时用）

.EXAMPLE
    .\start.ps1 -BackendPort 9000 -FrontendPort 5273 -NoBrowser
        # 换端口、不弹浏览器
#>
[CmdletBinding()]
param(
    [int]$BackendPort    = 8000,
    [int]$FrontendPort   = 5173,
    [switch]$BackendOnly,
    [switch]$NoBrowser,
    [switch]$Reload,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root

$LogDir    = Join-Path $Root 'logs'
$PidFile   = Join-Path $LogDir 'dev-servers.json'
$BackendOut = Join-Path $LogDir 'backend.log'
$BackendErr = Join-Path $LogDir 'backend.err.log'
$FrontOut   = Join-Path $LogDir 'frontend.log'
$FrontErr   = Join-Path $LogDir 'frontend.err.log'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err2($msg) { Write-Host "[x] $msg" -ForegroundColor Red }

function Test-PortOpen([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return $task.Wait(400) -and $client.Connected
    } catch { return $false }
    finally { $client.Dispose() }
}

function Wait-Http([string]$Url, [int]$Seconds, [string]$Label) {
    for ($i = 1; $i -le $Seconds; $i++) {
        try {
            $null = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
            return $true
        } catch {
            if ($i % 5 -eq 0) { Write-Host "      等待 $Label … ${i}s" -ForegroundColor DarkGray }
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

Write-Host ''
Write-Host '金融分析与监控智能体 · 启动脚本' -ForegroundColor White
Write-Host ('=' * 60) -ForegroundColor DarkGray

# ---------------------------------------------------------------- 1. 环境检查
Write-Step '检查环境'

$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    Write-Warn2 '.venv 不存在，改用 PATH 上的 python'
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $Python) {
        Write-Err2 '找不到 Python。请先执行： python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt'
        exit 1
    }
} else {
    Write-Ok "Python  $Python"
}

$Vite = Join-Path $Root 'frontend\node_modules\vite\bin\vite.js'
if (-not $BackendOnly -and -not (Test-Path $Vite)) {
    Write-Err2 'frontend\node_modules 未安装。请先： cd frontend; pnpm install'
    exit 1
}

if (Test-Path (Join-Path $Root '.env')) {
    Write-Ok '.env 已存在（LLM 可按需配置；不配也能跑，会退回模板结论）'
} else {
    Write-Warn2 '.env 不存在，将使用默认配置（无 LLM，模板结论）'
}

# ---------------------------------------------------------------- 2. 端口检查
Write-Step "检查端口 $BackendPort / $FrontendPort"

$BackendAlready = Test-PortOpen $BackendPort
if ($BackendAlready) { Write-Warn2 "端口 $BackendPort 已被占用，跳过启动后端" }
if (-not $BackendOnly -and (Test-PortOpen $FrontendPort)) {
    Write-Warn2 "端口 $FrontendPort 已被占用，跳过启动前端"
    $FrontendAlready = $true
} else { $FrontendAlready = $false }

# ---------------------------------------------------------------- 3. 启动后端
$BackendPid = $null
if (-not $BackendAlready) {
    Write-Step "启动后端 (127.0.0.1:$BackendPort)"
    $argList = @('scripts/run_api.py', '--host', '127.0.0.1', '--port', "$BackendPort")
    if ($Reload) { $argList += '--reload' }

    $proc = Start-Process -FilePath $Python -ArgumentList $argList `
        -WorkingDirectory $Root -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $BackendOut -RedirectStandardError $BackendErr
    $BackendPid = $proc.Id

    $health = "http://127.0.0.1:$BackendPort/api/health"
    if (Wait-Http $health $TimeoutSeconds 'backend') {
        Write-Ok "后端就绪  pid=$BackendPid  $health"
    } else {
        Write-Err2 "后端 $TimeoutSeconds 秒内未就绪，看日志： $BackendErr"
        Get-Content $BackendErr -Tail 20 -ErrorAction SilentlyContinue
        exit 1
    }
} else {
    Write-Ok "后端复用已运行实例  http://127.0.0.1:$BackendPort"
}

# ---------------------------------------------------------------- 4. 启动前端
$FrontendPid = $null
if (-not $BackendOnly -and -not $FrontendAlready) {
    Write-Step "启动前端 (127.0.0.1:$FrontendPort)"
    $frontArgs = @('node_modules/vite/bin/vite.js', '--port', "$FrontendPort", '--strictPort')
    $fproc = Start-Process -FilePath 'node' -ArgumentList $frontArgs `
        -WorkingDirectory (Join-Path $Root 'frontend') -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $FrontOut -RedirectStandardError $FrontErr
    $FrontendPid = $fproc.Id

    $ui = "http://127.0.0.1:$FrontendPort/"
    if (Wait-Http $ui 60 'frontend') {
        Write-Ok "前端就绪  pid=$FrontendPid  $ui"
    } else {
        Write-Err2 '前端未就绪，看日志：'
        Get-Content $FrontErr -Tail 20 -ErrorAction SilentlyContinue
        exit 1
    }
}

# ---------------------------------------------------------------- 5. 记录 PID
$state = [ordered]@{
    started_at   = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    backend_pid  = $BackendPid
    backend_port = $BackendPort
    frontend_pid = $FrontendPid
    frontend_port= $FrontendPort
}
$state | ConvertTo-Json | Set-Content -Path $PidFile -Encoding utf8
Write-Ok "PID 记录： $PidFile"

# ---------------------------------------------------------------- 6. 汇总
$uiUrl = "http://127.0.0.1:$FrontendPort/"
Write-Host ''
Write-Host ('=' * 60) -ForegroundColor DarkGray
Write-Host ' 启动完成' -ForegroundColor Green
Write-Host ('=' * 60) -ForegroundColor DarkGray
Write-Host "  前端界面   $uiUrl"
Write-Host "  接口文档   http://127.0.0.1:$BackendPort/docs"
Write-Host "  健康检查   http://127.0.0.1:$BackendPort/api/health"
Write-Host ''
Write-Host "  后端日志   $BackendOut"
Write-Host "            $BackendErr"
if (-not $BackendOnly) { Write-Host "  前端日志   $FrontOut" }
Write-Host ''
Write-Host '  关闭服务   .\stop.ps1' -ForegroundColor DarkGray
Write-Host ''

if (-not $BackendOnly -and -not $NoBrowser) {
    Write-Step '打开浏览器'
    Start-Process $uiUrl
}

exit 0
