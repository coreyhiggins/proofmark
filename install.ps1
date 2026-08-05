# proofmark installer for Windows. Free, no admin rights, no Python needed.
#
# Read it before you run it. It is short on purpose.
#
#   irm https://raw.githubusercontent.com/coreyhiggins/proofmark/main/install.ps1 -OutFile install.ps1
#   notepad install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# What it does:
#   1. Downloads the latest proofmark.exe from GitHub Releases.
#   2. Puts it in %LOCALAPPDATA%\Programs\proofmark
#   3. Adds that folder to YOUR PATH, not the machine's.
#   4. Adds a Start Menu shortcut.
#
# It never asks for administrator, never touches Program Files, and never edits
# the machine-wide registry. Uninstalling is deleting one folder, and this
# prints exactly how.
#
# It installs nothing else UNLESS you say yes to one question at the end. That
# question offers Ollama and a 2GB language model, which lets proofmark write
# its daily summaries in English instead of a template. It is off by default,
# it is a separate download, and declining changes nothing about the program.

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$Repo = "coreyhiggins/proofmark",
    # Answers the model question without a prompt, for anyone scripting this.
    [switch]$WithModel,
    [switch]$NoModel,
    [string]$Model = "llama3.2:3b"
)

$ErrorActionPreference = "Stop"

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\proofmark"
$ExePath    = Join-Path $InstallDir "proofmark.exe"
$StartMenu  = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\proofmark.lnk"

function Write-Step($msg) { Write-Host "  $msg" }

# ------------------------------------------------------------- uninstall ----

if ($Uninstall) {
    Write-Host "`nRemoving proofmark`n"
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force; Write-Step "deleted $InstallDir" }
    if (Test-Path $StartMenu)  { Remove-Item $StartMenu -Force;            Write-Step "removed the Start Menu shortcut" }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -and $userPath.Split(';') -contains $InstallDir) {
        $cleaned = ($userPath.Split(';') | Where-Object { $_ -and $_ -ne $InstallDir }) -join ';'
        [Environment]::SetEnvironmentVariable("Path", $cleaned, "User")
        Write-Step "removed it from your PATH"
    }
    Write-Host "`n  Done. Nothing else was changed.`n"
    exit 0
}

# --------------------------------------------------------------- install ----

Write-Host "`nproofmark installer`n"

# Ask GitHub which release is current. Public API, no token, no rate limit
# worth worrying about for one call.
Write-Step "looking up the latest release"
try {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" `
                                 -Headers @{ "User-Agent" = "proofmark-installer" }
} catch {
    Write-Host "`n  Could not reach GitHub. Check your connection and try again." -ForegroundColor Red
    Write-Host "  You can also download it by hand from:"
    Write-Host "      https://github.com/$Repo/releases/latest`n"
    exit 1
}

$asset = $release.assets | Where-Object { $_.name -like "*windows*.exe" } | Select-Object -First 1
if (-not $asset) {
    Write-Host "`n  That release has no Windows build attached." -ForegroundColor Red
    Write-Host "  Have a look at https://github.com/$Repo/releases/latest`n"
    exit 1
}

Write-Step "found $($release.tag_name)"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Download beside the target and move into place, so a failed or interrupted
# download never leaves a half-written executable someone then runs.
$temp = "$ExePath.download"
Write-Step "downloading $([math]::Round($asset.size / 1MB, 1)) MB"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $temp -UseBasicParsing
Move-Item -Path $temp -Destination $ExePath -Force
Write-Step "installed to $ExePath"

# User PATH only. Touching the machine PATH needs admin and affects everyone
# on the computer, neither of which this has any business doing.
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if ($userPath.Split(';') -notcontains $InstallDir) {
    $newPath = if ($userPath.TrimEnd(';')) { "$($userPath.TrimEnd(';'));$InstallDir" } else { $InstallDir }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Step "added to your PATH (new terminals will find it)"
}

try {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($StartMenu)
    $link.TargetPath = $ExePath
    $link.Description = "Check whether a trading result is safe to believe"
    $link.WorkingDirectory = $InstallDir
    $link.Save()
    Write-Step "added a Start Menu shortcut"
} catch {
    Write-Step "could not create the Start Menu shortcut, which is not fatal"
}

# ------------------------------------------------- the optional writer ----
#
# Opt in, never opt out. Somebody who opened a program to watch a trading bot
# did not come here to download a language model, and a several-GB pull that
# starts because they pressed enter too fast is a bad way to meet a tool.
#
# Everything works without it. The daily summaries are written from a template
# instead, and the program says which it used rather than hiding the
# difference.

function Install-Writer($modelName) {
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue)
    if (-not $ollama) {
        $winget = (Get-Command winget -ErrorAction SilentlyContinue)
        if (-not $winget) {
            Write-Step "winget is not available, so Ollama cannot be installed automatically."
            Write-Step "Get it from https://ollama.com and then run: ollama pull $modelName"
            return
        }
        Write-Step "installing Ollama"
        winget install --id Ollama.Ollama --accept-source-agreements --accept-package-agreements --silent
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "Machine")
    }

    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-Step "Ollama did not land on PATH. Open a new terminal and run: ollama pull $modelName"
        return
    }

    Write-Step "downloading $modelName, which is about 2GB and only happens once"
    ollama pull $modelName
    if ($LASTEXITCODE -eq 0) {
        Write-Step "done. proofmark will find it on its own, with nothing to configure."
    } else {
        Write-Step "the download did not finish. Run 'ollama pull $modelName' whenever you like."
    }
}

$wantsModel = $false
if ($WithModel) {
    $wantsModel = $true
} elseif (-not $NoModel) {
    Write-Host ""
    Write-Host "  Optional: proofmark can write its daily summaries in plain English"
    Write-Host "  instead of a template. That needs a language model running on this"
    Write-Host "  machine: about 2GB, downloaded once, free, and nothing is sent"
    Write-Host "  anywhere. Everything works without it."
    Write-Host ""
    $answer = Read-Host "  Download it? (y/N)"
    $wantsModel = ($answer -match "^(y|yes)$")
}

if ($wantsModel) { Install-Writer $Model }

Write-Host @"

  Installed.

  Open it from the Start Menu, or run:

      proofmark app

  The first time you run it Windows will say "Windows protected your PC".
  Click More info, then Run anyway. That happens because the file is not
  code-signed, which costs money we have not spent. It is also exactly the
  warning you should heed for a file you were not expecting.

  To update later:   proofmark update
  To remove it:      powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall

  If you skipped the optional writer and change your mind, install Ollama from
  https://ollama.com and run:  ollama pull llama3.2:3b

"@
