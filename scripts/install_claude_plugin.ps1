<#
.SYNOPSIS
Install student-presentation-suite into Claude Code.

.DESCRIPTION
Default mode registers the marketplace straight from GitHub
(YFan945/student-ppt-create@main), so no local clone is needed:

    claude plugin marketplace add YFan945/student-ppt-create@main
    claude plugin install student-presentation-suite@claude-personal

Dependencies (Python wheels and npm packages) are installed into the plugin
cache Claude Code creates, because that copy is the one Claude Code loads.

Use -Local to register a local checkout instead (development or offline),
which is also the mode used by contributors working in a clone.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:USERPROFILE ".agents\claude-plugins"),
    [switch]$Local,
    [switch]$Migrate,
    [switch]$SkipDependencies,
    [switch]$SkipMarketplaceClone,
    [switch]$InstallDotNetSdk
)

$ErrorActionPreference = "Stop"
$Repository = "https://github.com/YFan945/student-ppt-create.git"
$GitHubRepo = "YFan945/student-ppt-create"
$Branch = "main"
$Marketplace = "claude-personal"
$Plugin = "student-presentation-suite"
$PluginId = "$Plugin@$Marketplace"
$OldPluginId = "$Plugin@personal"

function Invoke-Checked {
    param([Parameter(Mandatory)][string]$Command, [string[]]$Arguments = @())
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
}

function Install-ManagedDotNetSdk {
    $managedRoot = if ($env:LOCALAPPDATA) {
        Join-Path $env:LOCALAPPDATA "student-presentation-suite\dotnet"
    } else {
        Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "student-presentation-suite/dotnet"
    }
    $managedDotNet = Join-Path $managedRoot $(if ($env:OS -eq "Windows_NT") { "dotnet.exe" } else { "dotnet" })
    $candidates = @($managedDotNet)
    $systemDotNet = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($systemDotNet) {
        $candidates += $systemDotNet.Source
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            $sdks = (& $candidate --list-sdks 2>$null | Out-String)
            if ($LASTEXITCODE -eq 0 -and $sdks -match "(?m)^([89]|[1-9][0-9]+)\.") {
                $env:STUDENT_PRESENTATION_DOTNET_ROOT = Split-Path $candidate -Parent
                return
            }
        }
    }

    if (-not $InstallDotNetSdk) {
        throw (
            ".NET 8 SDK is required for PPTX schema validation but was not found. " +
            "Install it separately, or rerun this installer with -InstallDotNetSdk " +
            "to explicitly download the pinned user-local SDK."
        )
    }
    $architecture = switch ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()) {
        "Arm64" { "arm64" }
        "X64" { "x64" }
        default { throw "Unsupported .NET SDK architecture: $_" }
    }
    $installer = Join-Path ([IO.Path]::GetTempPath()) "dotnet-install-student-presentation-suite.ps1"
    Invoke-WebRequest -UseBasicParsing "https://dot.net/v1/dotnet-install.ps1" -OutFile $installer
    try {
        & $installer -Version "8.0.423" -Architecture $architecture -InstallDir $managedRoot -NoPath
        if ($LASTEXITCODE -ne 0) {
            throw ".NET SDK installation failed with exit code $LASTEXITCODE"
        }
    } finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }
    $env:STUDENT_PRESENTATION_DOTNET_ROOT = $managedRoot
}

function Get-PluginCacheRoot {
    $configRoot = if ($env:CLAUDE_CONFIG_DIR) {
        [IO.Path]::GetFullPath($env:CLAUDE_CONFIG_DIR)
    } else {
        Join-Path $env:USERPROFILE ".claude"
    }
    return Join-Path $configRoot "plugins\cache"
}

function Resolve-InstalledPluginRoot {
    <#
    Locate the plugin copy Claude Code actually loads. After a remote
    marketplace add, that copy lives under the plugin cache, not in any local
    clone, so dependencies must be installed there.
    #>
    param([Parameter(Mandatory)][string]$MarketplaceName)
    $marketplaceRoot = Join-Path (Get-PluginCacheRoot) $MarketplaceName
    if (-not (Test-Path -LiteralPath $marketplaceRoot)) {
        return $null
    }
    $manifest = Get-ChildItem -LiteralPath $marketplaceRoot -Recurse -Filter "plugin.json" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -replace '/', '\' -match '\.claude-plugin\\plugin\.json$' } |
        Select-Object -First 1
    if (-not $manifest) {
        return $null
    }
    # manifest -> .claude-plugin -> plugin root
    return (Split-Path (Split-Path $manifest.FullName -Parent) -Parent)
}

function Remove-PluginCache {
    param([Parameter(Mandatory)][string]$MarketplaceName)
    $configRoot = if ($env:CLAUDE_CONFIG_DIR) {
        [IO.Path]::GetFullPath($env:CLAUDE_CONFIG_DIR)
    } else {
        Join-Path $env:USERPROFILE ".claude"
    }
    $cacheRoot = Join-Path $configRoot "plugins\cache"
    if (-not (Test-Path -LiteralPath $cacheRoot)) {
        return
    }
    Get-ChildItem -LiteralPath $cacheRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ieq $MarketplaceName } |
        ForEach-Object {
            $target = Join-Path $_.FullName $Plugin
            if (Test-Path -LiteralPath $target) {
                $resolvedCache = [IO.Path]::GetFullPath($cacheRoot)
                $resolvedTarget = [IO.Path]::GetFullPath($target)
                if (-not $resolvedTarget.StartsWith($resolvedCache + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Unsafe cache target: $resolvedTarget"
                }
                Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
            }
        }
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    throw "Claude Code CLI is required."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required."
}

if ($Migrate) {
    & claude plugin uninstall $OldPluginId 2>$null
    & claude plugin marketplace remove personal 2>$null
    Remove-PluginCache -MarketplaceName "personal"
}

if ($Local) {
    $InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
    if (-not $SkipMarketplaceClone) {
        if (Test-Path -LiteralPath (Join-Path $InstallRoot ".git")) {
            Invoke-Checked git @("-C", $InstallRoot, "fetch", "origin", $Branch)
            Invoke-Checked git @("-C", $InstallRoot, "switch", $Branch)
            Invoke-Checked git @("-C", $InstallRoot, "pull", "--ff-only", "origin", $Branch)
        } elseif (Test-Path -LiteralPath $InstallRoot) {
            if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot ".claude-plugin\marketplace.json"))) {
                throw "InstallRoot exists but is not the expected Claude marketplace: $InstallRoot"
            }
        } else {
            $parent = Split-Path $InstallRoot -Parent
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
            Invoke-Checked git @("clone", "--branch", $Branch, "--single-branch", $Repository, $InstallRoot)
        }
    }
    $pluginRoot = Join-Path $InstallRoot "plugins\student-presentation-suite"
    if (-not (Test-Path -LiteralPath (Join-Path $pluginRoot ".claude-plugin\plugin.json"))) {
        throw "Claude plugin manifest not found under $pluginRoot"
    }
} else {
    # Remote mode: no clone needed; the marketplace is registered from GitHub.
    $pluginRoot = $null
}

if (-not $SkipDependencies -and $Local) {
    Install-ManagedDotNetSdk
    Invoke-Checked python @("-m", "pip", "install", "-r", (Join-Path $pluginRoot "requirements.txt"))
    Invoke-Checked python @("-m", "pip", "install", "-r", (Join-Path $pluginRoot "requirements-claude-pptx.txt"))
    Invoke-Checked npm @("--prefix", $pluginRoot, "ci")
}

$marketplaces = (& claude plugin marketplace list | Out-String)
if ($marketplaces -match "(?m)^\s*>\s+$Marketplace\s*$") {
    Invoke-Checked claude @("plugin", "marketplace", "remove", $Marketplace)
}
if ($Local) {
    Invoke-Checked claude @("plugin", "marketplace", "add", "--scope", "user", $InstallRoot)
    Write-Output "Registered local marketplace from $InstallRoot"
} else {
    # GitHub-hosted marketplace: pinned to the main branch, no local clone.
    Invoke-Checked claude @("plugin", "marketplace", "add", "--scope", "user", "$GitHubRepo@$Branch")
    Write-Output "Registered GitHub marketplace $GitHubRepo@$Branch"
}

$plugins = (& claude plugin list | Out-String)
if ($plugins -match [regex]::Escape($PluginId)) {
    Invoke-Checked claude @("plugin", "update", "-s", "user", $PluginId)
} else {
    Invoke-Checked claude @("plugin", "install", "-s", "user", $PluginId)
}
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$enableOutput = (& claude plugin enable $PluginId 2>&1 | Out-String)
$enableExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedPreference
if ($enableExitCode -ne 0 -and $enableOutput -notmatch "already enabled") {
    throw "Failed to enable ${PluginId}: $enableOutput"
}

if (-not $Local) {
    # Remote install: dependencies belong to the cached copy Claude Code loads.
    $pluginRoot = Resolve-InstalledPluginRoot -MarketplaceName $Marketplace
    if (-not $pluginRoot) {
        Write-Warning "Could not locate the cached plugin under $(Get-PluginCacheRoot)."
        Write-Warning "Install dependencies manually there, then restart Claude Code:"
        Write-Warning "  pip install -r requirements.txt -r requirements-claude-pptx.txt && npm ci"
    } else {
        Write-Output "Installing dependencies in $pluginRoot"
        if (-not $SkipDependencies) {
            Install-ManagedDotNetSdk
            Invoke-Checked python @("-m", "pip", "install", "-r", (Join-Path $pluginRoot "requirements.txt"))
            Invoke-Checked python @("-m", "pip", "install", "-r", (Join-Path $pluginRoot "requirements-claude-pptx.txt"))
            Invoke-Checked npm @("--prefix", $pluginRoot, "ci")
        }
    }
}

if ($pluginRoot) {
    Invoke-Checked python @((Join-Path $pluginRoot "scripts\check_claude_pptx_env.py"), "--json", "--strict")
}
Invoke-Checked claude @("plugin", "details", $PluginId)
Invoke-Checked claude @("plugin", "list")
if ($Local) {
    Invoke-Checked python @((Join-Path $InstallRoot "scripts\check_installed_version.py"), "--json")
}

$source = if ($Local) { "$InstallRoot ($Branch)" } else { "$GitHubRepo@$Branch" }
Write-Output "Installed $PluginId from $source. Restart Claude Code to load updates."
if (-not $Local) {
    Write-Output "Later updates: claude plugin marketplace update $Marketplace"
}
