# Sets up volis for development on this machine. Run it once after cloning,
# and again whenever the lock file changes or a reinstall is needed:
#
#     .\setup.ps1              install (or bring up to date)
#     .\setup.ps1 -Reinstall   reinstall every package, e.g. after security
#                              software removed a DLL and an exclusion was added
#
# Copied from model-converter's setup.ps1, for the same reasons: it keeps uv's
# download cache, the Python interpreter and the environment all inside this
# folder, so every native file lives under one path, the one to give security
# software as an exclusion. Nothing is changed outside this folder.
# This is the only part of setup that uses the internet; volis itself never does.

param([switch]$Reinstall)
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

function Fail($message) {
    Write-Host "`nSTOP: $message" -ForegroundColor Red
    exit 1
}

Write-Host "== Checking tools"
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    Fail "this needs 64-bit x86 Windows (found $env:PROCESSOR_ARCHITECTURE)."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv is not installed. Install it with: winget install astral-sh.uv   (then open a new terminal)"
}
$uvVersion = ((uv --version) -split " ")[1]
$v = [version]$uvVersion
if ($v -lt [version]"0.11.26" -or $v -ge [version]"0.12") {
    Fail "uv is $uvVersion; this project is locked with uv 0.11.x (0.11.26 or newer). Install that version: uv self update 0.11.26"
}
Write-Host "  uv: $uvVersion"

# For this process and the uv commands it starts only.
$env:UV_CACHE_DIR = Join-Path $repo ".uv\cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repo ".uv\python"
# Copy files out of the cache rather than hard-linking them: a scanner that
# quarantines a cached file then cannot take the installed copy with it.
$env:UV_LINK_MODE = "copy"
# Install the uv-managed CPython from .python-version, never an installed one.
$env:UV_PYTHON_PREFERENCE = "only-managed"
Write-Host "  cache:  $env:UV_CACHE_DIR"
Write-Host "  python: $env:UV_PYTHON_INSTALL_DIR"

Write-Host "`n== Installing (uv sync --locked; PyTorch with CUDA is several GB the first time)"
Push-Location $repo
try {
    $syncArgs = @("sync", "--locked")
    if ($Reinstall) { $syncArgs += "--reinstall" }
    & uv @syncArgs
    if ($LASTEXITCODE -ne 0) {
        Fail ("uv sync failed. If it says the lock file needs updating, pyproject.toml was edited " +
              "without re-locking; run 'uv lock' on the machine that made the change and commit uv.lock. " +
              "If it failed writing or loading a .dll, see the README's 'Security software' section.")
    }
    # The GPU build of the translator, when this machine has built one
    # (build-llama.ps1 -Cuda): too large to commit, so it replaces the CPU wheel here.
    $cudaWheel = Get-ChildItem (Join-Path $repo "wheels\cuda") -Filter "llama_cpp_python-*.whl" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($cudaWheel) {
        Write-Host "`n== Installing the GPU build of the translator ($($cudaWheel.Name))"
        & uv pip install --python (Join-Path $repo ".venv\Scripts\python.exe") --reinstall --no-deps $cudaWheel.FullName
        if ($LASTEXITCODE -ne 0) { Fail "installing $($cudaWheel.FullName) failed" }
    }
}
finally {
    Pop-Location
}

Write-Host "`n== Checking the environment (doctor)"
& (Join-Path $repo "doctor.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Say plainly where the translator will run: nothing else fails when the GPU
# build is missing, it is only several times slower. (No stderr redirect: Windows
# PowerShell 5.1 turns a redirected stderr line into an error.)
$gpuTranslator = & (Join-Path $repo ".venv\Scripts\python.exe") -c "from volis.translate.llamacpp import gpu_available; print('yes' if gpu_available() else 'no')"
if ($gpuTranslator -eq "yes") {
    Write-Host "`nThe translator will run on the graphics card." -ForegroundColor Green
} else {
    Write-Host "`nThe translator will run on the PROCESSOR, several times slower than on the graphics card." -ForegroundColor Yellow
    Write-Host "To put it on the graphics card, do step 3 of 'Set it up' in README.md" -ForegroundColor Yellow
    Write-Host "(install two tools, then .\build-llama.ps1 -Cuda, then .\setup.ps1 again)." -ForegroundColor Yellow
}
