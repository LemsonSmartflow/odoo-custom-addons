$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path (Split-Path -Parent $projectRoot) 'virtual environments\odoo_19_venv\Scripts\python.exe'
$odooPath = Join-Path $projectRoot 'odoo-19.0\odoo-bin'
$configPath = Join-Path $projectRoot 'odoo.conf'

foreach ($requiredPath in @($pythonPath, $odooPath, $configPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file not found: $requiredPath"
    }
}

if (Test-NetConnection -ComputerName 127.0.0.1 -Port 8069 -InformationLevel Quiet -WarningAction SilentlyContinue) {
    Write-Host 'Port 8069 is already in use. Your Odoo server may already be running.'
    Write-Host 'Open http://127.0.0.1:8069. Stop the existing server before starting another.'
    exit 0
}

Write-Host 'Starting Odoo: http://127.0.0.1:8069'
Write-Host 'Keep this window open. Press Ctrl+C to stop Odoo.'
& $pythonPath $odooPath -c $configPath
exit $LASTEXITCODE
