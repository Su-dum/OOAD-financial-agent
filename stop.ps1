#!/usr/bin/env pwsh
#Requires -Version 5.1
# 本文件必须以 UTF-8 BOM 保存，否则 Windows PowerShell 5.1 会按 GBK 解码导致中文乱码。
<#
.SYNOPSIS
    关闭 start.ps1 拉起的后端 / 前端进程。

.DESCRIPTION
    优先读 logs\dev-servers.json 里的 PID 精确关闭（只杀自己起的进程）；
    文件不存在时按端口兜底（--ByPort）。
    注意：无论哪种方式，只处理本项目的 8000 / 5173，不会碰 19387 等其它服务。

.EXAMPLE
    .\stop.ps1

.EXAMPLE
    .\stop.ps1 -ByPort
        # PID 文件丢了（比如重开终端），按端口查占用者再关
#>
[CmdletBinding()]
param(
    [int]$BackendPort  = 8000,
    [int]$FrontendPort = 5173,
    [switch]$ByPort
)

$ErrorActionPreference = 'Continue'
$Root    = $PSScriptRoot
$PidFile = Join-Path $Root 'logs\dev-servers.json'

function Write-Step($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[+] $m" -ForegroundColor Green }
function Write-Warn2($m){ Write-Host "[!] $m" -ForegroundColor Yellow }

function Stop-Tree([int]$Id, [string]$Label) {
    if (-not $Id) { return }
    $p = Get-Process -Id $Id -ErrorAction SilentlyContinue
    if (-not $p) { Write-Warn2 "$Label pid=$Id 已不在运行"; return }
    # 先杀子进程（vite / uvicorn 可能再 fork）
    try {
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$Id" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    } catch { }
    Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue
    Write-Ok "$Label 已关闭  pid=$Id"
}

function Get-PortOwner([int]$Port) {
    try {
        (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -First 1).OwningProcess
    } catch { $null }
}

Write-Host ''
Write-Host '关闭金融分析与监控智能体' -ForegroundColor White
Write-Host ('=' * 50) -ForegroundColor DarkGray

if (-not $ByPort -and (Test-Path $PidFile)) {
    Write-Step "读取 $PidFile"
    $state = Get-Content $PidFile -Raw | ConvertFrom-Json
    Stop-Tree $state.backend_pid  'backend '
    Stop-Tree $state.frontend_pid 'frontend'
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    Write-Ok 'PID 文件已删除'
} else {
    if (-not $ByPort) { Write-Warn2 '没有 PID 文件，改用按端口关闭' }
    foreach ($pair in @(@{P=$BackendPort;L='backend '}, @{P=$FrontendPort;L='frontend'})) {
        $owner = Get-PortOwner $pair.P
        if ($owner) { Stop-Tree $owner $pair.L }
        else        { Write-Warn2 "$($pair.L) 端口 $($pair.P) 无监听进程" }
    }
}

Write-Host ''
Write-Ok '完成'
Write-Host ''
exit 0
