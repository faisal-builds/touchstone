<#
.SYNOPSIS
  Windows mirror of the Makefile. Run: ./make.ps1 <target> [args]

.DESCRIPTION
  Provides the same one-command developer workflow as 'make' on Linux/macOS:
  build, up, down, restart, rebuild, test, test-unit, lint, typecheck, health,
  clean, all, plus install / compose-validate / validate-infra.

  Run "./make.ps1 help" for the full list.
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)] [string] $Target = "help",
  [Parameter(ValueFromRemainingArguments = $true)] [string[]] $Rest
)

# Continue (not Stop): native tools (docker, kubectl, terraform) legitimately
# write to stderr, which PowerShell 5.1 would otherwise promote to a terminating
# error. Failures are detected explicitly via $LASTEXITCODE and Run-In's throw.
$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
Set-Location $Root

$Venv = Join-Path $Root ".venv\Scripts"
$Py   = Join-Path $Venv "python.exe"
$Ruff = Join-Path $Venv "ruff.exe"
$Mypy = Join-Path $Venv "mypy.exe"
$CP   = "services/control-plane"

$ServicePkgs = @(
  "services/control-plane", "services/verification-engine", "services/risk-engine",
  "services/audit-engine", "services/reward-hacking-detector", "services/ivp"
)
$FlatPkgs      = @("libs/touchstone-events", "libs/touchstone-fleet", "sdks/python")
$RuffSrc       = @("services/control-plane", "services/verification-engine", "services/risk-engine", "services/audit-engine")
$RuffSrcTests  = @("services/reward-hacking-detector", "services/ivp", "libs/touchstone-events", "libs/touchstone-fleet", "sdks/python")

function Die($msg) { Write-Host "[X] $msg" -ForegroundColor Red; exit 1 }

# Run an executable (with args) in a directory; throw on non-zero exit.
function Run-In($dir, $exe, [string[]] $argv) {
  Push-Location $dir
  try {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "command failed in $dir (exit $LASTEXITCODE)" }
  } finally { Pop-Location }
}

function Need-Venv {
  if (-not (Test-Path $Py)) { Die "venv not found - run: ./make.ps1 install" }
}

# ----------------------------------------------------------------------------
function Do-Help {
  Write-Host "Touchstone developer entrypoints (Windows). Usage: ./make.ps1 [target]`n"
  $rows = @(
    @("install",          "Create venv and install all packages (editable, dev deps)"),
    @("build",            "Build every service image"),
    @("up",               "Start the full local stack (detached)"),
    @("down",             "Stop the local stack (keeps volumes)"),
    @("restart",          "Restart the full stack"),
    @("rebuild",          "Rebuild images from scratch and recreate the stack"),
    @("health",           "Poll every service health endpoint (pass/fail table)"),
    @("lint",             "Lint every package with ruff (CI scopes)"),
    @("typecheck",        "Type-check the typed surface with mypy"),
    @("fmt",              "Auto-format + fix lint (control-plane)"),
    @("test",             "Run the FULL suite (integration needs the stack up)"),
    @("test-unit",        "Run unit tests across all packages (no infra)"),
    @("compose-validate", "Validate docker-compose config"),
    @("validate-infra",   "Offline infra preflight (compose/terraform/helm/k8s)"),
    @("all",              "Complete verifiable workflow (lint+types+unit+compose)"),
    @("clean",            "Tear down stack and volumes; remove caches/venv/artifacts")
  )
  foreach ($r in $rows) { "  {0,-18} {1}" -f $r[0], $r[1] }
}

function Do-Install {
  & python -m venv .venv; if ($LASTEXITCODE -ne 0) { Die "venv creation failed" }
  & $Py -m pip install -q --upgrade pip
  & $Py -m pip install -q -e ./libs/touchstone-events
  & $Py -m pip install -q -e ./libs/touchstone-fleet
  & $Py -m pip install -q -e "./$CP[dev]"
  & $Py -m pip install -q -e "./services/verification-engine[dev]"
  & $Py -m pip install -q -e "./services/risk-engine[dev]"
  & $Py -m pip install -q -e "./services/audit-engine[dev]"
  & $Py -m pip install -q -e "./services/reward-hacking-detector[dev]"
  & $Py -m pip install -q -e "./services/ivp[dev]"
  & $Py -m pip install -q -e "./sdks/python[dev]"
  Write-Host "[OK] install complete" -ForegroundColor Green
}

function Do-Build   { & docker compose build;                       if ($LASTEXITCODE) { exit $LASTEXITCODE } }
function Do-Up      { & docker compose up --build -d;               if ($LASTEXITCODE) { exit $LASTEXITCODE } }
function Do-Down    { & docker compose down;                        if ($LASTEXITCODE) { exit $LASTEXITCODE } }
function Do-Restart { & docker compose down; & docker compose up --build -d; if ($LASTEXITCODE) { exit $LASTEXITCODE } }
function Do-Rebuild { & docker compose build --no-cache; if ($LASTEXITCODE) { exit $LASTEXITCODE }; & docker compose up -d --force-recreate; if ($LASTEXITCODE) { exit $LASTEXITCODE } }

function Do-Lint {
  Need-Venv
  foreach ($p in $RuffSrc)      { Write-Host "== ruff: $p =="; Run-In $p $Ruff @("check", "src") }
  foreach ($p in $RuffSrcTests) { Write-Host "== ruff: $p =="; Run-In $p $Ruff @("check", "src", "tests") }
  Write-Host "[OK] lint passed" -ForegroundColor Green
}

function Do-Typecheck {
  Need-Venv
  $env:PYTHONPATH = "src"
  Run-In $CP $Mypy @("src")
  Write-Host "[OK] typecheck passed" -ForegroundColor Green
}

function Do-Fmt {
  Need-Venv
  & $Ruff format "$CP/src"
  & $Ruff check --fix "$CP/src"
}

function Do-Test {
  Need-Venv
  $env:PYTHONPATH = "src"
  foreach ($p in ($ServicePkgs + $FlatPkgs)) {
    Write-Host "== pytest: $p =="
    Run-In $p $Py @("-m", "pytest", "tests", "-q")
  }
  Write-Host "[OK] full test suite passed" -ForegroundColor Green
}

function Do-TestUnit {
  Need-Venv
  $env:PYTHONPATH = "src"
  foreach ($p in $ServicePkgs) {
    Write-Host "== unit: $p =="
    Run-In $p $Py @("-m", "pytest", "tests/unit", "-q")
  }
  foreach ($p in $FlatPkgs) {
    Write-Host "== unit: $p =="
    Run-In $p $Py @("-m", "pytest", "tests", "-q")
  }
  Write-Host "[OK] unit tests passed" -ForegroundColor Green
}

function Do-ComposeValidate {
  & docker compose config --quiet
  if ($LASTEXITCODE -ne 0) { Die "docker compose config invalid" }
  Write-Host "[OK] docker compose config: OK" -ForegroundColor Green
}

function Test-Url($url) {
  try {
    $r = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Do-Health {
  $services = @(
    @{ name = "control-plane";           url = "http://localhost:8000/healthz" },
    @{ name = "control-plane(ready)";    url = "http://localhost:8000/readyz" },
    @{ name = "reward-hacking-detector"; url = "http://localhost:8030/healthz" },
    @{ name = "ivp";                     url = "http://localhost:8050/healthz" },
    @{ name = "web";                     url = "http://localhost:3000/api/health" }
  )
  "{0,-26} {1,-8} {2}" -f "SERVICE", "STATUS", "ENDPOINT"
  "{0,-26} {1,-8} {2}" -f "-------", "------", "--------"
  $fail = 0
  foreach ($s in $services) {
    if (Test-Url $s.url) {
      Write-Host ("{0,-26} {1,-8} {2}" -f $s.name, "PASS", $s.url) -ForegroundColor Green
    } else {
      Write-Host ("{0,-26} {1,-8} {2}" -f $s.name, "FAIL", $s.url) -ForegroundColor Red
      $fail = 1
    }
  }
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "`nHeadless workers (docker compose state):"
    foreach ($svc in @("verification-engine", "risk-engine", "audit-engine", "reward-hacking-detector-worker")) {
      $state = (& docker compose ps --format "{{.State}}" $svc 2>$null | Select-Object -First 1)
      if (-not $state) { $state = "not running" }
      "  {0,-32} {1}" -f $svc, $state
    }
  }
  if ($fail -eq 0) { Write-Host "`n[OK] all HTTP services healthy" -ForegroundColor Green }
  else { Write-Host "`n[X] one or more services unhealthy (is the stack up? try ./make.ps1 up)" -ForegroundColor Red }
  exit $fail
}

function Do-ValidateInfra {
  $script:pass = 0; $script:fail = 0; $script:skip = 0
  function _ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green;  $script:pass++ }
  function _bad($m)  { Write-Host "  [X]    $m" -ForegroundColor Red;    $script:fail++ }
  function _note($m) { Write-Host "  [skip] $m" -ForegroundColor Yellow; $script:skip++ }
  function _have($c) { return [bool](Get-Command $c -ErrorAction SilentlyContinue) }

  Write-Host "== docker compose =="
  if (_have docker) {
    & docker compose config --quiet 2>$null
    if ($LASTEXITCODE -eq 0) { _ok "docker compose config" } else { _bad "docker compose config" }
  } else { _note "docker not installed" }

  Write-Host "== terraform (fmt + validate, no backend) =="
  if (_have terraform) {
    & terraform -chdir=deploy/terraform fmt -check -recursive *>$null
    if ($LASTEXITCODE -eq 0) { _ok "terraform fmt" } else { _bad "terraform fmt (run: terraform -chdir=deploy/terraform fmt -recursive)" }
    & terraform -chdir=deploy/terraform init -backend=false -input=false *>$null
    if ($LASTEXITCODE -eq 0) {
      & terraform -chdir=deploy/terraform validate *>$null
      if ($LASTEXITCODE -eq 0) { _ok "terraform validate" } else { _bad "terraform validate" }
    } else { _bad "terraform init (no backend)" }
  } else { _note "terraform not installed" }

  Write-Host "== helm lint =="
  if (_have helm) {
    & helm lint deploy/helm/touchstone -f deploy/helm/touchstone/values-production.yaml *>$null
    if ($LASTEXITCODE -eq 0) { _ok "helm lint" } else { _bad "helm lint" }
  } else { _note "helm not installed" }

  Write-Host "== kubernetes manifests =="
  $hasContext = $false
  if (_have kubectl) { & kubectl config current-context *>$null; $hasContext = ($LASTEXITCODE -eq 0) }
  if (_have kubeconform) {
    & kubeconform -strict -ignore-missing-schemas -summary deploy/k8s/ *>$null
    if ($LASTEXITCODE -eq 0) { _ok "kubeconform (raw manifests)" } else { _bad "kubeconform (raw manifests)" }
  } elseif ((_have kubectl) -and $hasContext) {
    & kubectl apply --dry-run=client -f deploy/k8s/ *>$null
    if ($LASTEXITCODE -eq 0) { _ok "kubectl --dry-run=client" } else { _bad "kubectl --dry-run=client" }
  } else { _note "kubeconform not installed (kubectl dry-run needs a kube-context); CI runs kubeconform" }

  Write-Host "`npreflight: $script:pass passed, $script:fail failed, $script:skip skipped"
  Write-Host "NOTE: validation only - 'well-formed', not 'deploy-ready'."
  if ($script:fail -ne 0) { exit 1 } else { exit 0 }
}

function Do-All {
  Do-Lint
  Do-Typecheck
  Do-TestUnit
  Do-ComposeValidate
  Write-Host "`n[OK] all: lint + typecheck + unit tests + compose config all green" -ForegroundColor Green
  exit 0
}

function Do-Clean {
  & docker compose down -v --remove-orphans 2>$null
  foreach ($d in @(".venv", "apps/web/.next", "apps/web/node_modules", "sdks/typescript/node_modules", "sdks/typescript/dist")) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
  }
  Get-ChildItem -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "reports") } |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }
  Get-ChildItem -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @(".coverage", "coverage.xml", "junit.xml") } |
    ForEach-Object { Remove-Item -Force $_.FullName -ErrorAction SilentlyContinue }
  if (Test-Path rendered.yaml) { Remove-Item -Force rendered.yaml -ErrorAction SilentlyContinue }
  if (Test-Path .artifacts) {
    Get-ChildItem .artifacts -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -ne ".gitkeep" } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  }
  Write-Host "[OK] clean complete" -ForegroundColor Green
}

switch ($Target.ToLower()) {
  "help"             { Do-Help }
  "install"          { Do-Install }
  "build"            { Do-Build }
  "up"               { Do-Up }
  "down"             { Do-Down }
  "restart"          { Do-Restart }
  "rebuild"          { Do-Rebuild }
  "health"           { Do-Health }
  "lint"             { Do-Lint }
  "typecheck"        { Do-Typecheck }
  "fmt"              { Do-Fmt }
  "test"             { Do-Test }
  "test-unit"        { Do-TestUnit }
  "compose-validate" { Do-ComposeValidate }
  "validate-infra"   { Do-ValidateInfra }
  "all"              { Do-All }
  "clean"            { Do-Clean }
  default            { Write-Host "Unknown target: $Target`n"; Do-Help; exit 2 }
}
