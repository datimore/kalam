# A native Windows text box (same Ctrl+V handling as Word / Notepad) that dumps its text to $env:KALAM_TARGET_OUT.
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object Windows.Forms.Form; $f.Text = 'Kalam test target'; $f.Width = 700; $f.Height = 220; $f.TopMost = $true
$t = New-Object Windows.Forms.TextBox; $t.Multiline = $true; $t.Dock = 'Fill'; $t.Font = New-Object Drawing.Font('Segoe UI', 14)
$f.Controls.Add($t)
$timer = New-Object Windows.Forms.Timer; $timer.Interval = 300
$timer.Add_Tick({ [IO.File]::WriteAllText($env:KALAM_TARGET_OUT, $t.Text, [Text.Encoding]::UTF8) }); $timer.Start()
$f.Add_Shown({ $f.Activate(); $t.Focus() })
[Windows.Forms.Application]::Run($f)
