$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Run the real publisher's public-verification block against loopback HTTP.
# Removing UTF-8 decoding must reject a valid binary response; weakening the
# version check must accept an old/empty manifest and fail these regressions.
$publisherPath = Join-Path $PSScriptRoot '..\publish-electron-update.ps1'
$tokens = $null
$parseErrors = $null
$publisherAst = [Management.Automation.Language.Parser]::ParseFile(
    $publisherPath, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count) { throw 'Publisher contains PowerShell syntax errors.' }
$verificationNodes = @($publisherAst.FindAll({
    param($node)
    if ($node -isnot [Management.Automation.Language.TryStatementAst]) { return $false }
    return @($node.Body.Statements | Where-Object {
        $_ -is [Management.Automation.Language.AssignmentStatementAst] -and
        $_.Left -is [Management.Automation.Language.VariableExpressionAst] -and
        $_.Left.VariablePath.UserPath -eq 'published'
    }).Count -gt 0
}, $false))
if ($verificationNodes.Count -ne 1) { throw 'Cannot locate the real public-verification block.' }
$verification = [scriptblock]::Create($verificationNodes[0].Extent.Text)

Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
public sealed class XiquanManifestHttpFixture : IDisposable {
    private readonly TcpListener listener;
    private readonly Thread worker;
    private readonly byte[] manifest;
    private readonly string contentType;
    private readonly int headStatus;
    private volatile bool stopped;
    public readonly int Port;
    public XiquanManifestHttpFixture(byte[] body, string type, int status) {
        manifest = body; contentType = type; headStatus = status;
        listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start(); Port = ((IPEndPoint)listener.LocalEndpoint).Port;
        worker = new Thread(Serve); worker.IsBackground = true; worker.Start();
    }
    private void Serve() {
        while (!stopped) {
            try {
                using (var client = listener.AcceptTcpClient())
                using (var stream = client.GetStream()) {
                    client.ReceiveTimeout = 5000; client.SendTimeout = 5000;
                    var reader = new StreamReader(stream, Encoding.ASCII, false, 1024, true);
                    var first = reader.ReadLine();
                    while (!String.IsNullOrEmpty(reader.ReadLine())) { }
                    bool get = first == "GET /updates/latest.yml HTTP/1.1";
                    bool head = first == "HEAD /updates/Xiquan-Bathhouse-Setup-0.4.1.exe HTTP/1.1";
                    int status = get ? 200 : head ? headStatus : 404;
                    byte[] body = get ? manifest : new byte[0];
                    string headers = "HTTP/1.1 " + status + " " + (status == 200 ? "OK" : "Not Found") +
                        "\r\nContent-Type: " + contentType + "\r\nContent-Length: " + body.Length +
                        "\r\nConnection: close\r\n\r\n";
                    var headerBytes = Encoding.ASCII.GetBytes(headers);
                    stream.Write(headerBytes, 0, headerBytes.Length);
                    if (!head) stream.Write(body, 0, body.Length);
                    stream.Flush();
                }
            } catch (SocketException) { if (!stopped) throw; }
              catch (ObjectDisposedException) { if (!stopped) throw; }
        }
    }
    public void Dispose() { stopped = true; listener.Stop(); worker.Join(5000); }
}
'@

$validManifest = "version: 0.4.1`r`npath: Xiquan-Bathhouse-Setup-0.4.1.exe`r`n"
$validBytes = [Text.Encoding]::UTF8.GetBytes($validManifest)
$probe = New-Object XiquanManifestHttpFixture -ArgumentList @($validBytes, 'application/octet-stream', 200)
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$($probe.Port)/updates/latest.yml" -UseBasicParsing -TimeoutSec 5
    if ($PSVersionTable.PSVersion.Major -eq 5 -and $response.Content -isnot [byte[]]) {
        throw 'Windows PowerShell binary-response characterization did not reproduce.'
    }
    Write-Host "Characterized HTTP octet-stream response: $($response.Content.GetType().FullName)."
} finally { $probe.Dispose() }

$cases = @(
    @{Name='valid binary YAML'; Body=$validBytes; Type='application/octet-stream'; Head=200; Reject=$false},
    @{Name='valid text YAML'; Body=$validBytes; Type='text/plain; charset=utf-8'; Head=200; Reject=$false},
    @{Name='valid binary YAML with UTF8 BOM'; Body=[byte[]](@(239,187,191) + $validBytes); Type='application/octet-stream'; Head=200; Reject=$false},
    @{Name='old binary version'; Body=[Text.Encoding]::UTF8.GetBytes("version: 0.4.0`n"); Type='application/octet-stream'; Head=200; Reject=$true},
    @{Name='old text version'; Body=[Text.Encoding]::UTF8.GetBytes("version: 0.4.0`n"); Type='text/plain'; Head=200; Reject=$true},
    @{Name='empty binary manifest'; Body=[byte[]]@(); Type='application/octet-stream'; Head=200; Reject=$true},
    @{Name='HTML instead of manifest'; Body=[Text.Encoding]::UTF8.GetBytes('<html>not a release</html>'); Type='text/html'; Head=200; Reject=$true},
    @{Name='missing installer'; Body=$validBytes; Type='application/octet-stream'; Head=404; Reject=$true}
)
$failed = New-Object 'System.Collections.Generic.List[string]'
foreach ($case in $cases) {
    $fixture = New-Object XiquanManifestHttpFixture -ArgumentList @($case.Body, $case.Type, $case.Head)
    try {
        $manifestUrl = "http://127.0.0.1:$($fixture.Port)/updates/latest.yml"
        $installerUrl = "http://127.0.0.1:$($fixture.Port)/updates/Xiquan-Bathhouse-Setup-0.4.1.exe"
        $version = '0.4.1'
        $rejected = $false
        try { & $verification } catch { $rejected = $true }
        if ($rejected -ne $case.Reject) { $failed.Add($case.Name) }
    } finally { $fixture.Dispose() }
}
if ($failed.Count) { throw "Publisher behavior failed: $($failed -join ', ')." }
Write-Host '8 real HTTP manifest verification regressions passed; no cloud, SSH or upload invoked.'
