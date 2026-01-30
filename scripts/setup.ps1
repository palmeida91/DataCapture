# Production Monitoring System - Setup Script for Windows
# Run this script as Administrator

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Production Monitoring System - Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    Pause
    exit 1
}

# Step 1: Check Docker installation
Write-Host "Step 1: Checking Docker installation..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version
    Write-Host "  OK: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Docker is not installed!" -ForegroundColor Red
    Write-Host "  Please install Docker Desktop from: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
    Pause
    exit 1
}

# Check if Docker is running
Write-Host "Step 2: Checking if Docker is running..." -ForegroundColor Yellow
try {
    docker ps | Out-Null
    Write-Host "  OK: Docker is running" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Docker is not running!" -ForegroundColor Red
    Write-Host "  Please start Docker Desktop and try again" -ForegroundColor Yellow
    Pause
    exit 1
}

# Step 3: Check Python installation
Write-Host "Step 3: Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version
    Write-Host "  OK: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Python is not installed!" -ForegroundColor Red
    Write-Host "  Please install Python 3.11+ from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Pause
    exit 1
}

# Step 4: Install Python dependencies
Write-Host "Step 4: Installing Python dependencies..." -ForegroundColor Yellow
try {
    pip install asyncua==1.0.6 asyncpg cryptography --quiet
    Write-Host "  OK: Python packages installed" -ForegroundColor Green
} catch {
    Write-Host "  WARNING: Could not install Python packages" -ForegroundColor Yellow
    Write-Host "  You may need to run: pip install asyncua asyncpg cryptography" -ForegroundColor Yellow
}

# Step 5: Generate certificates
Write-Host "Step 5: Generating OPC UA certificates..." -ForegroundColor Yellow
if (-not (Test-Path "client_cert.der")) {
    python generate_certs.py
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK: Certificates generated" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: Certificate generation failed" -ForegroundColor Yellow
        Write-Host "  Run manually: python generate_certs.py" -ForegroundColor Yellow
    }
} else {
    Write-Host "  OK: Certificates already exist" -ForegroundColor Green
}

# Step 6: Pull Docker images
Write-Host "Step 6: Pulling Docker images (this may take a few minutes)..." -ForegroundColor Yellow
docker compose pull
if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK: Docker images downloaded" -ForegroundColor Green
} else {
    Write-Host "  ERROR: Failed to pull Docker images" -ForegroundColor Red
    Pause
    exit 1
}

# Step 7: Start containers
Write-Host "Step 7: Starting Docker containers..." -ForegroundColor Yellow
docker compose up -d
if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK: Containers started" -ForegroundColor Green
} else {
    Write-Host "  ERROR: Failed to start containers" -ForegroundColor Red
    Pause
    exit 1
}

# Step 8: Wait for database to be ready
Write-Host "Step 8: Waiting for database to initialize (30 seconds)..." -ForegroundColor Yellow
Start-Sleep -Seconds 30
Write-Host "  OK: Database should be ready" -ForegroundColor Green

# Step 9: Configure Windows Firewall
Write-Host "Step 9: Configuring Windows Firewall..." -ForegroundColor Yellow
try {
    New-NetFirewallRule -DisplayName "Grafana Dashboard" -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "PostgreSQL" -Direction Inbound -LocalPort 5432 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue
    Write-Host "  OK: Firewall rules added" -ForegroundColor Green
} catch {
    Write-Host "  WARNING: Could not add firewall rules (may already exist)" -ForegroundColor Yellow
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Verify config/opcua_nodes.json has correct settings" -ForegroundColor White
Write-Host "  2. Update 'active_sequences' to match your machine" -ForegroundColor White
Write-Host "  3. Start data collector: python data_collector.py" -ForegroundColor White
Write-Host "  4. Open Grafana: http://localhost:3000 (admin/admin)" -ForegroundColor White
Write-Host ""
Write-Host "Access Points:" -ForegroundColor Yellow
Write-Host "  Grafana:   http://localhost:3000" -ForegroundColor Cyan
Write-Host "  Database:  localhost:5432 (user: collector, db: production)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Useful Commands:" -ForegroundColor Yellow
Write-Host "  Start services:    docker compose up -d" -ForegroundColor White
Write-Host "  Stop services:     docker compose stop" -ForegroundColor White
Write-Host "  View logs:         docker compose logs -f" -ForegroundColor White
Write-Host "  Start collector:   python data_collector.py" -ForegroundColor White
Write-Host ""

Pause
