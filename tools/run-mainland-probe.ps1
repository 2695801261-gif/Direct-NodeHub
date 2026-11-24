$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Version = "v1.19.34"
$WorkDir = Join-Path $env:TEMP "Direct-NodeHub-Mainland"
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

function Get-PythonCommand {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Command = "py"; Prefix = @("-3.12") }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Command = "python"; Prefix = @() }
    }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "未检测到 Python。是否使用 winget 安装 Python 3.12？输入 Y 确认"
        if ($answer -match "^[Yy]$") {
            winget install --id Python.Python.3.12 -e --scope user
            $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
            if (Test-Path $candidate) {
                return @{ Command = $candidate; Prefix = @() }
            }
        }
    }
    throw "需要 Python 3.12。请先从 https://www.python.org/downloads/windows/ 安装，再重新运行本脚本。"
}

$pyInfo = Get-PythonCommand
$pythonCommand = $pyInfo.Command
$pythonPrefix = $pyInfo.Prefix

function Invoke-ProjectPython {
    param([string[]]$Arguments)
        $allArgs = @()\n    if ($script:pythonPrefix) { $allArgs += $script:pythonPrefix }\n    $allArgs += $Arguments\n    & $script:pythonCommand @allArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python 命令失败，退出码：$LASTEXITCODE"
    }
}

if (-not (Test-Path (Join-Path $RepoRoot "public\candidates.json"))) {
    throw "未找到 public\candidates.json。请先把 Direct-NodeHub 仓库完整下载并解压，再运行 tools\run-mainland-probe.ps1。"
}

Write-Host "1/4 安装项目依赖…" -ForegroundColor Cyan
Invoke-ProjectPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $RepoRoot "requirements.txt"))

Write-Host "2/4 下载并校验官方 Mihomo…" -ForegroundColor Cyan
$releaseUrl = "https://api.github.com/repos/MetaCubeX/mihomo/releases/tags/$Version"
$release = Invoke-RestMethod -Uri $releaseUrl -Headers @{ "User-Agent" = "Direct-NodeHub-Mainland-Probe" }
$asset = $release.assets | Where-Object { $_.name -eq "mihomo-windows-amd64-compatible-$Version.zip" } | Select-Object -First 1
if (-not $asset) {
    $asset = $release.assets | Where-Object { $_.name -match "^mihomo-windows-amd64.*\.zip$" } | Select-Object -First 1
}
if (-not $asset -or -not $asset.digest -or $asset.digest -notmatch "^sha256:(.+)$") {
    throw "官方发布包缺少 SHA-256 摘要，拒绝下载未校验的 Mihomo。"
}
$zipPath = Join-Path $WorkDir "mihomo.zip"
$extractDir = Join-Path $WorkDir "mihomo"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
$expectedHash = $asset.digest.Substring(7).ToLowerInvariant()
$actualHash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash) {
    throw "Mihomo SHA-256 校验失败，已停止。"
}
if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
$mihomo = Get-ChildItem -Path $extractDir -Filter "mihomo.exe" -Recurse | Select-Object -First 1
if (-not $mihomo) { throw "压缩包中没有找到 mihomo.exe。" }
$env:MIHOMO_BIN = $mihomo.FullName
& $env:MIHOMO_BIN -v

Write-Host ""
Write-Host "请确认：电脑当前连接的是中国大陆本地网络，并已关闭所有 VPN、代理软件和系统代理。" -ForegroundColor Yellow
Write-Host "测试期间不要切换网络。该脚本只会测试仓库中已通过云端初筛的节点。"
$confirm = Read-Host "确认以上条件后输入 MAINLAND 开始测试"
if ($confirm -cne "MAINLAND") {
    throw "未确认大陆直连环境，已停止。"
}

Write-Host "3/4 执行大陆本地协议、延迟和双向速度测试（最多 30 个节点，每个节点 3 轮）…" -ForegroundColor Cyan
Push-Location $RepoRoot
try {
    Invoke-ProjectPython -Arguments @("-m", "direct_nodehub.mainland_probe", "--confirm-mainland", "--limit", "30", "--rounds", "3", "--probe-id", "windows-mainland")
    $report = Get-ChildItem -Path (Join-Path $RepoRoot "reports\mainland") -Filter "windows-mainland-*.json" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $report) { throw "大陆测试完成，但没有找到测试报告。" }

    Write-Host "4/4 只用大陆实测通过的节点生成订阅…" -ForegroundColor Cyan
    Invoke-ProjectPython -Arguments @("-m", "direct_nodehub.mainland_publish", "--report", $report.FullName)

    $outputDir = Join-Path $report.DirectoryName "output"
    $desktop = [Environment]::GetFolderPath("Desktop")
    $destination = Join-Path $desktop "Direct-NodeHub-Mainland"
    if (Test-Path $destination) { Remove-Item $destination -Recurse -Force }
    Copy-Item -Path $outputDir -Destination $destination -Recurse -Force

    Write-Host ""
    Write-Host "完成。大陆实测订阅已放到桌面：" -ForegroundColor Green
    Write-Host $destination
    Write-Host "clash-mainland.yaml = 大陆实测稳定池"
    Write-Host "fast-mainland.yaml  = 大陆实测高速池"
    Write-Host "如果结果为 0 个节点，代表本轮没有节点通过大陆实测，不会用云端结果冒充可用节点。"
}
finally {
    Pop-Location
}
