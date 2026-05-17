$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONPATH = "src"
$url = "http://127.0.0.1:8765/"
Start-Process $url
py -m cfd_agent.web_app --host 127.0.0.1 --port 8765 --no-browser
