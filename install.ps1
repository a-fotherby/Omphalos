# Get the directory where the script is located
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Get user's default shell – we'll assume PowerShell since this is Windows
$USER_SHELL = "powershell"
$CURRENT_SHELL = (Get-Process -Id $PID).ProcessName

if ($CURRENT_SHELL -ne $USER_SHELL) {
    Write-Host "Switching to user shell: $USER_SHELL to run the script..."
    Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`""
    exit
}

Write-Host "User's login shell: $USER_SHELL"

# Define aliases
$ALIAS_omphalos = "function omphalos { python `"$SCRIPT_DIR\omphalos\main.py`" }"
$ALIAS_rhea     = "function rhea { python `"$SCRIPT_DIR\rhea\main.py`" }"

# PowerShell Profile for persistent alias/function setup
$CONFIG_FILE = $PROFILE

# Ensure conda is available
& conda init powershell | Out-Null
& conda config --add channels conda-forge
& conda config --set channel_priority strict
& conda env create --file "$SCRIPT_DIR\requirements.yml"

# Add aliases if not already present
if (Test-Path $CONFIG_FILE) {
    $ProfileContent = Get-Content $CONFIG_FILE -Raw

    if ($ProfileContent -notmatch [regex]::Escape($ALIAS_omphalos)) {
        Add-Content -Path $CONFIG_FILE -Value "`n$ALIAS_omphalos"
        Add-Content -Path $CONFIG_FILE -Value $ALIAS_rhea
        Write-Host "Aliases added to $CONFIG_FILE"
    }
    else {
        Write-Host "Aliases already exist in $CONFIG_FILE"
    }
} else {
    # Create the profile and add aliases
    New-Item -ItemType File -Path $CONFIG_FILE -Force | Out-Null
    Add-Content -Path $CONFIG_FILE -Value "`n$ALIAS_omphalos"
    Add-Content -Path $CONFIG_FILE -Value $ALIAS_rhea
    Write-Host "Profile created and aliases added to $CONFIG_FILE"
}

# Source the profile (loads aliases)
. $CONFIG_FILE

