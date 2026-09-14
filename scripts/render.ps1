[CmdletBinding()]
param(
    [string]$BlenderPath = $env:BLENDER_EXE,
    [ValidateRange(128, 16384)][int]$Resolution = 2400,
    [ValidateRange(1, 4096)][int]$Samples = 96,
    [ValidateSet('AUTO', 'CPU', 'GPU')][string]$Device = 'AUTO',
    [switch]$NoRender
)
$ErrorActionPreference = 'Stop'
$solarRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($BlenderPath)) {
    $solarCommand = Get-Command blender -ErrorAction SilentlyContinue
    if ($null -eq $solarCommand) {
        throw 'Blender was not found. Pass -BlenderPath with your blender.exe location, or set BLENDER_EXE.'
    }
    $BlenderPath = $solarCommand.Source
}
$solarBuildArgs = @('--background', '--factory-startup', '--python-exit-code', '1',
    '--python', (Join-Path $solarRoot 'src/blender_sun.py'), '--',
    '--resolution', $Resolution.ToString(), '--samples', $Samples.ToString(), '--device', $Device)
if ($NoRender) { $solarBuildArgs += '--no-render' }
& $BlenderPath @solarBuildArgs
if ($LASTEXITCODE -ne 0) { throw "Blender failed with exit code $LASTEXITCODE." }
