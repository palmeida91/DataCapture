# Xubuntu 22.04 LTS Setup Guide for OEE Monitoring

Complete guide for installing Ubuntu on low-spec laptops (4GB RAM, Celeron) for production line monitoring.

---

## Overview

**What you're building:**
- Xubuntu 22.04 LTS (lightweight Ubuntu with XFCE desktop)
- PostgreSQL 16 (database)
- Grafana (dashboards)
- Python 3.13 + OEE Collector
- Google Chrome in kiosk mode (auto-start dashboard)

**Per laptop:**
- ~1.2GB RAM used by OS
- ~2.8GB RAM free for applications
- Boots directly to dashboard (fullscreen)
- Press F11 to access desktop when needed

---

## Part 1: Create Bootable USB

### Requirements:
- USB drive (4GB minimum, 8GB recommended)
- Windows PC with internet (your dev machine)

### Step 1.1: Download Xubuntu

**Download from:** https://xubuntu.org/download/

**Choose:** Xubuntu 22.04.3 LTS (64-bit)
- File: `xubuntu-22.04.3-desktop-amd64.iso` (~2.8GB)
- **Important:** Use 22.04 LTS (Long Term Support - 5 years of updates)

### Step 1.2: Create Bootable USB

**Option A: Use Rufus (Recommended for Windows)**

1. Download Rufus: https://rufus.ie/
2. Insert USB drive (will be erased!)
3. Open Rufus
4. Settings:
   - Device: Select your USB drive
   - Boot selection: Click SELECT → choose downloaded `.iso`
   - Partition scheme: **GPT**
   - Target system: **UEFI (non CSM)**
   - Leave other settings as default
5. Click START
6. Wait 5-10 minutes

**Option B: Use balenaEtcher**
1. Download: https://www.balena.io/etcher/
2. Flash ISO to USB (simpler UI than Rufus)

---

## Part 2: Install Xubuntu on Laptop

### Step 2.1: Boot from USB

1. **Insert USB** into laptop
2. **Power on** laptop
3. **Press boot menu key** repeatedly during startup:
   - Common keys: F12, F9, F8, Esc, F2
   - (Check laptop manual if needed)
4. **Select USB drive** from boot menu
5. Xubuntu will load (takes 1-2 minutes)

### Step 2.2: Start Installation

1. Language: **English** (or your preference)
2. Click: **Install Xubuntu**
3. Keyboard layout: **English (US)** (or your layout)
4. Updates and other software:
   - ✅ Check: "Download updates while installing Xubuntu"
   - ✅ Check: "Install third-party software for graphics..." (for WiFi drivers)
5. Click: **Continue**

### Step 2.3: Disk Setup (IMPORTANT!)

**⚠️ This will erase Windows! Make sure you're okay with this.**

**Option 1: Erase Everything (Easiest)**
1. Select: **Erase disk and install Xubuntu**
2. Click: **Install Now**
3. Confirm: **Continue**

**Option 2: Manual Partitioning (If you know what you're doing)**
- Not needed for your use case, skip this

### Step 2.4: Complete Installation

1. **Time zone:** Select your location
2. **Your info:**
   - Your name: `oee` (or whatever you prefer)
   - Computer name: `line-a-laptop` (or `line-b-laptop`, etc.)
   - Username: `oee`
   - Password: Choose a password (write it down!)
   - ✅ Check: "Log in automatically" (no password needed on boot)
3. Click: **Continue**
4. **Wait 15-20 minutes** (installation + updates)
5. **Restart now** (remove USB when prompted)

---

## Part 3: First Boot & Basic Setup

### Step 3.1: Initial Configuration

After restart, Xubuntu desktop appears.

**Update system immediately:**
1. Press `Ctrl+Alt+T` (opens terminal)
2. Run these commands:

```bash
# Update package lists
sudo apt update

# Upgrade all packages
sudo apt upgrade -y

# Reboot to apply updates
sudo reboot
```

**Wait for reboot** (~1 minute)

### Step 3.2: Install Essential Tools

Open terminal (`Ctrl+Alt+T`):

```bash
# Install basic tools
sudo apt install -y curl wget net-tools software-properties-common gnupg2

# Install Git
sudo apt install -y git

# Verify Git installation
git --version
# Should show: git version 2.34.1 (or similar)
```

---

## Part 4: Install Google Chrome

### Step 4.1: Download and Install Chrome

```bash
# Download Google Chrome .deb package
cd ~/Downloads
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb

# Install Chrome
sudo dpkg -i google-chrome-stable_current_amd64.deb

# Fix any dependency issues (if any)
sudo apt install -f -y

# Verify installation
google-chrome --version
# Should show: Google Chrome 120.x.x.x (or current version)
```

### Step 4.2: Test Chrome

```bash
# Launch Chrome (should open browser window)
google-chrome &
```

**First launch:**
- Chrome asks: "Set as default browser?" → Click **Set as default**
- Chrome asks: "Sign in to Chrome?" → Click **Skip**

Close Chrome for now.

---

## Part 5: Install PostgreSQL 16

### Step 5.1: Add PostgreSQL Repository

```bash
# Add PostgreSQL apt repository
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'

# Add repository key
wget -qO- https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo tee /etc/apt/trusted.gpg.d/pgdg.asc &>/dev/null

# Update package list
sudo apt update
```

### Step 5.2: Install PostgreSQL

```bash
# Install PostgreSQL 16
sudo apt install -y postgresql-16 postgresql-contrib-16

# Check status (should show "active (running)")
sudo systemctl status postgresql
# Press 'q' to quit

# Enable auto-start on boot (already enabled, but verify)
sudo systemctl enable postgresql
```

### Step 5.3: Configure PostgreSQL

**Create database and user:**

```bash
# Switch to postgres user
sudo -u postgres psql

# Inside PostgreSQL prompt (postgres=#), run these commands:
```

```sql
-- Create database
CREATE DATABASE production;

-- Create user with password
CREATE USER collector WITH PASSWORD 'secure_password_here';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE production TO collector;

-- Connect to production database
\c production

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO collector;

-- Exit PostgreSQL
\q
```

**Test connection:**

```bash
# Test connection with new user
psql -U collector -d production -h localhost

# Should connect successfully (will ask for password)
# Type: secure_password_here
# You'll see: production=>

# Exit
\q
```

**✅ PostgreSQL installed and configured!**

---

## Part 6: Install Python 3.13

### Step 6.1: Add deadsnakes PPA

```bash
# Add PPA for newer Python versions
sudo add-apt-repository ppa:deadsnakes/ppa -y

# Update package list
sudo apt update
```

### Step 6.2: Install Python 3.13

```bash
# Install Python 3.13
sudo apt install -y python3.13 python3.13-venv python3.13-dev

# Install pip for Python 3.13
curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3.13

# Verify installation
python3.13 --version
# Should show: Python 3.13.x

pip3.13 --version
# Should show: pip 23.x.x from /usr/local/lib/python3.13/...
```

### Step 6.3: Install Python Dependencies

```bash
# Install required Python packages
sudo pip3.13 install asyncua asyncpg --break-system-packages
```

**Note:** `--break-system-packages` is required on Ubuntu 22.04+ due to PEP 668.

---

## Part 7: Install Grafana

### Step 7.1: Add Grafana Repository

```bash
# Add Grafana GPG key
wget -q -O - https://packages.grafana.com/gpg.key | sudo apt-key add -

# Add Grafana repository
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"

# Update package list
sudo apt update
```

### Step 7.2: Install Grafana

```bash
# Install Grafana
sudo apt install -y grafana

# Enable and start Grafana
sudo systemctl enable grafana-server
sudo systemctl start grafana-server

# Check status (should show "active (running)")
sudo systemctl status grafana-server
# Press 'q' to quit
```

### Step 7.3: Test Grafana

```bash
# Open Chrome to Grafana
google-chrome http://localhost:3000 &
```

**First login:**
- Username: `admin`
- Password: `admin`
- Change password when prompted (write it down!)

**✅ Grafana is running!**

Close Chrome for now.

---

## Part 8: Set Up OEE Collector

### Step 8.1: Clone Git Repository

```bash
# Navigate to home directory
cd ~

# Clone your repository
git clone https://github.com/your-username/DataCollection.git

# Navigate to collector directory
cd DataCollection/DataCapture
```

**If repository is private:**
```bash
# Git will ask for username and password/token
# Use your GitHub username and Personal Access Token
```

### Step 8.2: Copy Configuration Files

```bash
# Copy collector config to working directory
cp config/collector_config.json .

# Copy certificates (if using security)
cp client_cert.der .
cp client_key.pem .

# Copy logging config
cp logging_config.py .

# Copy connection manager
cp opcua_connection_manager.py .

# Copy V2 collector
cp data_collector_oee_v2.py .
```

### Step 8.3: Edit Configuration for This Laptop

**Open config file:**
```bash
nano collector_config.json
```

**Edit these values:**
```json
{
  "machine": {
    "machine_id": "line_a2_1",              ← Change per laptop
    "machine_name": "PoC Line A2.1",        ← Change per laptop
    "opcua_endpoint": "192.168.61.2:4840",  ← Change per laptop (PLC IP)
    "target_cycle_time_seconds": 17,        ← Change if different
    "active_sequences": [5, 8, 9, 10, ...] ← Change per laptop
  }
}
```

**Save:** Press `Ctrl+X`, then `Y`, then `Enter`

### Step 8.4: Initialize Database

```bash
# Run database migration (creates tables)
python3.13 database/migration_connection_events.py

# Insert sequences for this line
psql -U collector -d production -h localhost -f sequences_setup.sql
# Password: secure_password_here
```

### Step 8.5: Test Collector Manually

```bash
# Run collector manually (test run)
python3.13 data_collector_oee_v2.py

# You should see:
# ======================================================================
# OEE DATA COLLECTOR V2
# ======================================================================
# Connecting to database...
# ✓ Database connection established
# Using security: Basic256Sha256/SignAndEncrypt
# Starting OPC UA connection to opc.tcp://192.168.61.2:4840...
# 🔌 Connected: opc.tcp://192.168.61.2:4840
# ✓ OPC UA connection manager started
# ...

# Press Ctrl+C to stop (for now)
```

---

## Part 9: Create Systemd Service (Auto-Start)

### Step 9.1: Create Service File

```bash
# Create service file
sudo nano /etc/systemd/system/oee-collector.service
```

**Paste this content:**
```ini
[Unit]
Description=OEE Data Collector
After=network.target postgresql.service

[Service]
Type=simple
User=oee
WorkingDirectory=/home/oee/DataCollection/DataCapture
ExecStart=/usr/bin/python3.13 /home/oee/DataCollection/DataCapture/data_collector_oee_v2.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Save:** `Ctrl+X`, `Y`, `Enter`

### Step 9.2: Enable and Start Service

```bash
# Reload systemd to read new service
sudo systemctl daemon-reload

# Enable service (auto-start on boot)
sudo systemctl enable oee-collector

# Start service now
sudo systemctl start oee-collector

# Check status
sudo systemctl status oee-collector

# Should show: "active (running)"
```

### Step 9.3: View Collector Logs

```bash
# View live logs (Ctrl+C to exit)
journalctl -u oee-collector -f

# View last 50 lines
journalctl -u oee-collector -n 50
```

---

## Part 10: Configure Chrome Kiosk Mode

### Step 10.1: Create Kiosk Script

```bash
# Create kiosk script
nano ~/start_dashboard.sh
```

**Paste this content:**
```bash
#!/bin/bash
# Wait for Grafana to start
sleep 5

# Launch Chrome in kiosk mode
google-chrome --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble http://localhost:3000
```

**Save:** `Ctrl+X`, `Y`, `Enter`

**Make executable:**
```bash
chmod +x ~/start_dashboard.sh
```

### Step 10.2: Auto-Start on Boot

```bash
# Create autostart directory (if doesn't exist)
mkdir -p ~/.config/autostart

# Create desktop entry for auto-start
nano ~/.config/autostart/grafana-dashboard.desktop
```

**Paste this content:**
```ini
[Desktop Entry]
Type=Application
Name=Grafana Dashboard
Exec=/home/oee/start_dashboard.sh
X-GNOME-Autostart-enabled=true
```

**Save:** `Ctrl+X`, `Y`, `Enter`

### Step 10.3: Test Kiosk Mode

```bash
# Run kiosk script manually
~/start_dashboard.sh

# Chrome should open fullscreen showing Grafana
# Press F11 to exit fullscreen
# Press Alt+F4 to close Chrome
```

---

## Part 11: Create Desktop Shortcut (Optional)

If you want manual desktop icon instead of auto-start:

```bash
# Create desktop shortcut
nano ~/Desktop/Dashboard.desktop
```

**Paste this content:**
```ini
[Desktop Entry]
Version=1.0
Type=Application
Name=Line A Dashboard
Comment=Open Grafana Dashboard
Exec=google-chrome --kiosk http://localhost:3000
Icon=browser
Terminal=false
Categories=Application;
```

**Save and make executable:**
```bash
chmod +x ~/Desktop/Dashboard.desktop

# Right-click desktop icon → "Trust This Executable"
```

---

## Part 12: Configure Grafana Dashboard

### Step 12.1: Add PostgreSQL Data Source

1. Open Chrome to Grafana: http://localhost:3000
2. Login (admin / your-password)
3. Click **⚙️ (Settings)** → **Data sources**
4. Click **Add data source**
5. Select **PostgreSQL**
6. Configure:
   - Name: `Production Database`
   - Host: `localhost:5432`
   - Database: `production`
   - User: `collector`
   - Password: `secure_password_here`
   - SSL Mode: `disable`
   - Version: `16.0`
7. Click **Save & test** (should show green checkmark)

### Step 12.2: Import Dashboard

**Option A: Create from scratch** (follow your current dashboard design)

**Option B: Import existing dashboard**
1. Click **+** → **Import**
2. Upload your dashboard JSON
3. Select data source: `Production Database`
4. Click **Import**

---

## Part 13: Final Configuration

### Step 13.1: Set Up Grafana for Kiosk Display

**Login to Grafana:**
1. Navigate to your main dashboard
2. Click **⭐ (star icon)** to favorite it
3. Click dashboard settings (gear icon)
4. **General** → Copy dashboard UID
5. Update kiosk script to point directly to dashboard:

```bash
nano ~/start_dashboard.sh
```

**Change last line to:**
```bash
google-chrome --kiosk --noerrdialogs --disable-infobars http://localhost:3000/d/YOUR-DASHBOARD-UID
```

### Step 13.2: Disable Screen Sleep

```bash
# Open power settings
xfce4-power-manager-settings

# Set:
# - Display power management: OFF
# - System power saving: Never
# - When laptop lid is closed: Do nothing
```

### Step 13.3: Configure Auto-Login (If Not Done During Install)

```bash
# Edit display manager config
sudo nano /etc/lightdm/lightdm.conf
```

**Add under `[Seat:*]` section:**
```ini
autologin-user=oee
autologin-user-timeout=0
```

---

## Part 14: Reboot and Test Full System

### Step 14.1: Reboot Laptop

```bash
sudo reboot
```

### Step 14.2: Verify Everything Works

**After reboot, check:**
- ✅ Desktop loads automatically (no login)
- ✅ Chrome opens fullscreen showing Grafana dashboard (~5 seconds)
- ✅ Dashboard shows live data
- ✅ Press F11 → exits fullscreen (can access desktop)
- ✅ Press F11 again → back to fullscreen

### Step 14.3: Check Services are Running

**Press Ctrl+Alt+T** (opens terminal over Chrome):

```bash
# Check PostgreSQL
sudo systemctl status postgresql

# Check Grafana
sudo systemctl status grafana-server

# Check OEE Collector
sudo systemctl status oee-collector

# All should show: "active (running)"

# View collector logs
journalctl -u oee-collector -n 20

# Exit terminal
exit
```

---

## Part 15: Troubleshooting

### Collector Not Running

```bash
# Check logs
journalctl -u oee-collector -n 50

# Common issues:
# - Wrong PLC IP in config
# - Certificate files missing
# - Database connection failed

# Restart collector
sudo systemctl restart oee-collector
```

### Chrome Not Auto-Starting

```bash
# Check autostart file exists
ls ~/.config/autostart/grafana-dashboard.desktop

# Check script is executable
ls -l ~/start_dashboard.sh

# Test script manually
~/start_dashboard.sh
```

### Grafana Not Showing Data

```bash
# Check PostgreSQL connection
psql -U collector -d production -h localhost

# Inside PostgreSQL:
\dt  # List tables
SELECT COUNT(*) FROM cycle_times;  # Check data exists
\q

# Check Grafana data source
# Open Grafana → Settings → Data sources → Test connection
```

### Network Not Working

```bash
# Check network interface
ip addr show

# If using WiFi, connect via GUI:
# Click WiFi icon in system tray → Select network → Enter password

# Test PLC connectivity
ping 192.168.61.2  # Your PLC IP
```

---

## Part 16: Useful Commands

### System Management

```bash
# Reboot laptop
sudo reboot

# Shutdown laptop
sudo shutdown now

# View system resources
htop  # Press 'q' to quit (install: sudo apt install htop)

# Check disk space
df -h
```

### Service Management

```bash
# Start service
sudo systemctl start oee-collector

# Stop service
sudo systemctl stop oee-collector

# Restart service
sudo systemctl restart oee-collector

# View service status
sudo systemctl status oee-collector

# View service logs (live)
journalctl -u oee-collector -f
```

### File Editing

```bash
# Edit config file
nano ~/DataCollection/DataCapture/collector_config.json

# Save: Ctrl+X, then Y, then Enter

# View file contents
cat filename.txt

# View large file with scrolling
less filename.txt  # Press 'q' to quit
```

### Git Commands

```bash
# Pull latest changes from GitHub
cd ~/DataCollection
git pull

# Check status
git status

# View changes
git log

# Clone repository (first time)
git clone https://github.com/your-username/DataCollection.git
```

---

## Part 17: Production Supervisor Quick Guide

**For non-technical users:**

### Normal Operation
1. **Turn on laptop** (press power button)
2. **Wait 30 seconds** (dashboard appears automatically)
3. **Dashboard shows live data** fullscreen

### If Dashboard Not Visible
1. **Look for Chrome icon** on taskbar at bottom
2. **Click icon** to show Chrome window
3. **Press F11** for fullscreen

### If Laptop is Frozen
1. **Hold power button** for 10 seconds (forces shutdown)
2. **Wait 10 seconds**
3. **Press power button** again (restart)
4. **Wait 30 seconds** for dashboard to appear

### When to Call IT
- Dashboard shows "No data" for more than 5 minutes
- Screen says "Connection lost"
- Laptop won't turn on
- Any error messages

---

## Part 18: Maintenance Tasks

### Daily
- None required (system runs automatically)

### Weekly
- Check disk space: `df -h` (should have >5GB free)
- Check logs for errors: `journalctl -u oee-collector -n 100`

### Monthly
- Update system: `sudo apt update && sudo apt upgrade -y`
- Reboot after updates: `sudo reboot`

### Quarterly
- Check database size: `sudo -u postgres psql -c "\l+"`
- Backup database (see backup section)

---

## Part 19: Backup and Restore

### Backup Database

```bash
# Create backup directory
mkdir -p ~/backups

# Backup database
pg_dump -U collector -d production -h localhost > ~/backups/production_$(date +%Y%m%d).sql

# Backup will ask for password: secure_password_here
```

### Restore Database

```bash
# Restore from backup
psql -U collector -d production -h localhost < ~/backups/production_20260204.sql
```

### Backup Configuration

```bash
# Backup entire collector folder
cd ~
tar -czf collector_backup_$(date +%Y%m%d).tar.gz DataCollection/

# Copy to USB drive
cp collector_backup_*.tar.gz /media/oee/USB_DRIVE/
```

---

## Part 20: Replicating to Other Laptops

### Quick Clone Method

Once first laptop is working:

1. **Create disk image:**
   - Boot from USB (Clonezilla or similar)
   - Create full disk image
   - Save to external drive

2. **Clone to other laptops:**
   - Boot from USB on new laptop
   - Restore disk image
   - Boot new laptop

3. **Configure each laptop:**
   ```bash
   # Edit machine config
   nano ~/DataCollection/DataCapture/collector_config.json
   
   # Change:
   # - machine_id: "line_b1_1"
   # - machine_name: "Line B"
   # - opcua_endpoint: "192.168.62.10:4840"
   # - active_sequences: [1,2,3,...]
   
   # Update database sequences
   psql -U collector -d production -h localhost -f sequences_line_b.sql
   
   # Restart services
   sudo systemctl restart oee-collector
   sudo reboot
   ```

**Time per laptop:** ~30 minutes (after first laptop is done)

---

## Summary - What You Have Now

**On each laptop:**
- ✅ Xubuntu 22.04 LTS (lightweight, ~1.2GB RAM)
- ✅ PostgreSQL 16 (local database)
- ✅ Grafana (dashboards on http://localhost:3000)
- ✅ Python 3.13 + OEE Collector V2
- ✅ Google Chrome in kiosk mode
- ✅ Auto-starts dashboard on boot
- ✅ Git for easy updates
- ✅ ~2.8GB RAM free for operations

**Production supervisor sees:**
- Laptop turns on
- Dashboard appears automatically
- Live OEE data fullscreen

**You can:**
- Press F11 to exit fullscreen
- Press Ctrl+Alt+T for terminal
- SSH from dev machine (if on same network)
- Update code via Git
- View logs, restart services

---

## Next Steps

1. ✅ Install Xubuntu on first laptop (follow this guide)
2. ✅ Test everything works for 1-2 days
3. ✅ Create disk image of working laptop
4. ✅ Clone to remaining 3 laptops
5. ✅ Configure each laptop (30 min per laptop)
6. ✅ Deploy to production lines

---

**Questions? Issues?**
- Check troubleshooting section (Part 15)
- Review logs: `journalctl -u oee-collector -f`
- Test components individually (PostgreSQL, Grafana, Collector)

**Guide Version:** 1.0  
**Last Updated:** February 4, 2026  
**Status:** Production Ready ✅
