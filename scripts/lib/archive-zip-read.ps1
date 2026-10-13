[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ZipPath)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$OutputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=$OutputEncoding
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive=$null
try{
    $archive=[IO.Compression.ZipFile]::OpenRead($ZipPath)
    if($archive.Entries.Count -gt 5000){throw 'Archive entry limit exceeded'}
    $records=New-Object 'System.Collections.Generic.List[object]'
    [long]$total=0
    foreach($entry in $archive.Entries){
        if($entry.Length -gt 16777216){throw 'Archive entry size limit exceeded'}
        $total+=$entry.Length
        if($total -gt 67108864){throw 'Archive total size limit exceeded'}
        if($entry.FullName.EndsWith('/')){
            if($entry.Length -ne 0){throw 'Unexpected directory data'}
            $records.Add([pscustomobject]@{name=$entry.FullName;size=0;data=''})
            continue
        }
        $stream=$entry.Open()
        $buffer=New-Object IO.MemoryStream
        try{
            $chunk=New-Object byte[] 65536
            while(($count=$stream.Read($chunk,0,$chunk.Length)) -gt 0){
                if($buffer.Length+$count -gt $entry.Length){throw 'Archive entry exceeded declared size'}
                $buffer.Write($chunk,0,$count)
            }
            if($buffer.Length -ne $entry.Length){throw 'Archive entry was not completely read'}
            $records.Add([pscustomobject]@{name=$entry.FullName;size=$entry.Length;data=[Convert]::ToBase64String($buffer.ToArray())})
        }finally{$buffer.Dispose();$stream.Dispose()}
    }
    # The caller captures this data privately and reviews it; never forward raw output to a user.
    ConvertTo-Json -InputObject @($records.ToArray()) -Depth 4 -Compress
}finally{if($archive){$archive.Dispose()}}
