# Voix off : un WAV par séquence avec une voix Windows OneCore (WinRT Windows.Media.SpeechSynthesis).
# Usage : powershell -ExecutionPolicy Bypass -File tts.ps1 [-Voice Julie] [-Rate 0.95] [-Out dir] [-Only s1]
param([string]$Voice = "Julie", [double]$Rate = 0.95, [string]$Out = "$PSScriptRoot\audio", [string]$Only = "")

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Out | Out-Null
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]

$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Await($op, [type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait() | Out-Null
    $task.Result
}

$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$v = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.DisplayName -like "*$Voice*" -and $_.Language -eq "fr-FR" } | Select-Object -First 1
if (-not $v) { throw "voice $Voice (fr-FR) not found" }
$synth.Voice = $v
$synth.Options.SpeakingRate = $Rate
Write-Host "Voice: $($v.DisplayName) ($($v.Gender)), rate $Rate"

$segments = Get-Content "$PSScriptRoot\script.json" -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($s in $segments) {
    if ($Only -and $s.id -ne $Only) { continue }
    $stream = Await ($synth.SynthesizeTextToStreamAsync($s.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $size = [uint32]$stream.Size
    $null = Await ($reader.LoadAsync($size)) ([uint32])
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    [IO.File]::WriteAllBytes("$Out\$($s.id).wav", $bytes)
    Write-Host "$($s.id).wav  $([math]::Round($size / 1KB)) KB"
}
