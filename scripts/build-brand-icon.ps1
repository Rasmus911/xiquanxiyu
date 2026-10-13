[CmdletBinding()]
param([string]$OutputDirectory)
$ErrorActionPreference='Stop'
if(-not $OutputDirectory){$OutputDirectory=Join-Path $PSScriptRoot '..\client\electron\assets'}
Add-Type -AssemblyName System.Drawing
New-Item -ItemType Directory -Force -Path $OutputDirectory|Out-Null
$fonts=[Drawing.Text.InstalledFontCollection]::new()
$familyName=@('华文行楷','STXingkai','楷体','KaiTi','Microsoft YaHei')|Where-Object {$_ -in $fonts.Families.Name}|Select-Object -First 1
if(-not $familyName){throw 'No Chinese brand font found.'}
$family=[Drawing.FontFamily]::new($familyName)
$frames=@()
foreach($size in @(16,24,32,48,64,128,256)){
 $bitmap=[Drawing.Bitmap]::new($size,$size)
 $graphics=[Drawing.Graphics]::FromImage($bitmap)
 $graphics.SmoothingMode=[Drawing.Drawing2D.SmoothingMode]::AntiAlias
 $graphics.Clear([Drawing.Color]::Transparent)
 $graphics.ScaleTransform($size/256.0,$size/256.0)
 $shape=[Drawing.Drawing2D.GraphicsPath]::new()
 $shape.AddArc(0,0,48,48,180,90);$shape.AddArc(208,0,48,48,270,90)
 $shape.AddArc(208,208,48,48,0,90);$shape.AddArc(0,208,48,48,90,90);$shape.CloseFigure()
 $background=[Drawing.SolidBrush]::new([Drawing.ColorTranslator]::FromHtml('#594239'))
 $graphics.FillPath($background,$shape)
 $gold=[Drawing.Pen]::new([Drawing.ColorTranslator]::FromHtml('#C5A784'),2)
 $graphics.DrawArc($gold,24,23,208,208,18,144)
 $ink=[Drawing.SolidBrush]::new([Drawing.ColorTranslator]::FromHtml('#FFF2DD'))
 $letters=[Drawing.Drawing2D.GraphicsPath]::new()
 $format=[Drawing.StringFormat]::GenericTypographic.Clone()
 $letters.AddString('溪泉',$family,[int][Drawing.FontStyle]::Regular,101,[Drawing.PointF]::new(18,64),$format)
 $bounds=$letters.GetBounds()
 $matrix=[Drawing.Drawing2D.Matrix]::new()
 $matrix.Translate(128-$bounds.X-$bounds.Width/2,122-$bounds.Y-$bounds.Height/2)
 $letters.Transform($matrix);$graphics.FillPath($ink,$letters)
 $water=[Drawing.Pen]::new([Drawing.ColorTranslator]::FromHtml('#D5BC9D'),3)
 $graphics.DrawBezier($water,55,186,92,173,122,198,154,185)
 $graphics.DrawBezier($water,101,203,131,192,158,211,196,194)
 $stream=[IO.MemoryStream]::new();$bitmap.Save($stream,[Drawing.Imaging.ImageFormat]::Png)
 $frames+=,@{Size=$size;Bytes=$stream.ToArray()}
 if($size-eq 256){$bitmap.Save((Join-Path $OutputDirectory 'xiquan.png'),[Drawing.Imaging.ImageFormat]::Png)}
 $stream.Dispose();$graphics.Dispose();$bitmap.Dispose();$shape.Dispose();$letters.Dispose();$matrix.Dispose();$background.Dispose();$gold.Dispose();$ink.Dispose();$water.Dispose();$format.Dispose()
}
$ico=[IO.MemoryStream]::new();$writer=[IO.BinaryWriter]::new($ico)
$writer.Write([uint16]0);$writer.Write([uint16]1);$writer.Write([uint16]$frames.Count)
$offset=6+16*$frames.Count
foreach($frame in $frames){
 $writer.Write([byte]$(if($frame.Size-eq 256){0}else{$frame.Size}))
 $writer.Write([byte]$(if($frame.Size-eq 256){0}else{$frame.Size}))
 $writer.Write([byte]0);$writer.Write([byte]0);$writer.Write([uint16]1);$writer.Write([uint16]32)
 $writer.Write([uint32]$frame.Bytes.Length);$writer.Write([uint32]$offset);$offset+=$frame.Bytes.Length
}
foreach($frame in $frames){$writer.Write([byte[]]$frame.Bytes)}
[IO.File]::WriteAllBytes((Join-Path $OutputDirectory 'xiquan.ico'),$ico.ToArray())
$writer.Dispose();$ico.Dispose();$family.Dispose();$fonts.Dispose()
Write-Host ('BRAND_ICON_GENERATED font='+$familyName+' sizes=16,24,32,48,64,128,256')
