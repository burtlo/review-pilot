# review-ticket headless reviewer adapter (Windows entry)
param(
    [Parameter(Mandatory = $true)][string]$Context,
    [Parameter(Mandatory = $true)][string]$Output,
    [Parameter(Mandatory = $true)][string]$Checkout,
    [Parameter(Mandatory = $true)][string]$Repository,
    [Parameter(Mandatory = $true)][string]$Sha,
    [Parameter(Mandatory = $true)][string]$Issue,
    [string]$Agent = "reviewer"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here "review_ticket_reviewer.py"

$argsList = @(
    $py,
    "--context", $Context,
    "--output", $Output,
    "--checkout", $Checkout,
    "--repository", $Repository,
    "--sha", $Sha,
    "--issue", $Issue,
    "--agent", $Agent
)

& python @argsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
