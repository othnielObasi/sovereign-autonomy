param([ValidateRange(1024, 65535)][int]$Port = 17687)

# Local validation runtime prepared under the existing Ubuntu WSL distribution.
# Foreground process: Ctrl+C stops it. This does not install a system service.
$ErrorActionPreference = 'Stop'
$runtimeRoot = '/opt/sovereign-memgraph'
wsl -d Ubuntu -- test -x "$runtimeRoot/runtime/usr/lib/memgraph/memgraph"
if ($LASTEXITCODE -ne 0) {
    throw 'Local Memgraph runtime missing. See docs/MEMGRAPH.md for the Docker installation path.'
}
wsl -d Ubuntu -- mkdir -p "$runtimeRoot/data" "$runtimeRoot/log"
wsl -d Ubuntu -- env "LD_LIBRARY_PATH=$runtimeRoot/runtime/usr/lib/memgraph" `
    "$runtimeRoot/runtime/usr/lib/memgraph/memgraph" `
    "--data-directory=$runtimeRoot/data" --bolt-address=127.0.0.1 "--bolt-port=$Port" `
    --telemetry-enabled=false --query-execution-timeout-sec=3 "--log-file=$runtimeRoot/log/memgraph.log"
exit $LASTEXITCODE
