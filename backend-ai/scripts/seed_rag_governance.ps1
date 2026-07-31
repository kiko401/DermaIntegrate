param(
  [string]$DatabaseUrl = "",
  [string]$SqlFile = "backend-ai/sql/seeds/seed_rag_governance.sql"
)

$ErrorActionPreference = "Stop"

function Read-EnvValue([string]$path, [string]$key) {
  if (-not (Test-Path $path)) { return "" }
  foreach ($line in Get-Content -Encoding UTF8 $path) {
    $trim = $line.Trim()
    if ($trim -eq "" -or $trim.StartsWith("#")) { continue }
    if ($trim -match "^$([regex]::Escape($key))=(.*)$") {
      return $Matches[1].Trim().Trim('"').Trim("'")
    }
  }
  return ""
}

if (-not $DatabaseUrl) {
  $DatabaseUrl = Read-EnvValue "backend-ai/.env" "DATABASE_URL"
}
if (-not $DatabaseUrl) {
  throw "未找到 DATABASE_URL。请确认 backend-ai/.env 存在 DATABASE_URL，或用 -DatabaseUrl 传入。"
}
if (-not (Test-Path $SqlFile)) {
  throw "SQL 文件不存在：$SqlFile"
}
if (-not (Get-Command mysql -ErrorAction SilentlyContinue)) {
  throw "未找到 mysql 命令。请先安装 MySQL Client，或手动在数据库工具中执行 $SqlFile。"
}

# 支持 mysql://user:pass@host:port/db、mysql+pymysql://、mysql+aiomysql://
$normalized = $DatabaseUrl -replace '^mysql\+pymysql://','mysql://' -replace '^mysql\+aiomysql://','mysql://'
$uri = [Uri]$normalized
$user = [Uri]::UnescapeDataString($uri.UserInfo.Split(':')[0])
$pass = ""
if ($uri.UserInfo.Contains(':')) { $pass = [Uri]::UnescapeDataString($uri.UserInfo.Substring($uri.UserInfo.IndexOf(':') + 1)) }
$hostName = $uri.Host
$port = if ($uri.Port -gt 0) { $uri.Port } else { 3306 }
$dbName = $uri.AbsolutePath.TrimStart('/')
if (-not $dbName) { throw "DATABASE_URL 中缺少数据库名。" }

$tmp = New-TemporaryFile
try {
  @"
[client]
user=$user
password=$pass
host=$hostName
port=$port
default-character-set=utf8mb4
"@ | Set-Content -Encoding UTF8 $tmp.FullName

  Write-Host "即将导入 RAG 治理种子数据到数据库：$dbName@$hostName:$port"
  mysql --defaults-extra-file="$($tmp.FullName)" $dbName --default-character-set=utf8mb4 < $SqlFile
  if ($LASTEXITCODE -ne 0) { throw "mysql 执行失败，退出码：$LASTEXITCODE" }
  Write-Host "导入完成。请重启 backend-ai 或等待缓存过期后刷新 RAG 治理页面。"
}
finally {
  Remove-Item -LiteralPath $tmp.FullName -Force -ErrorAction SilentlyContinue
}
