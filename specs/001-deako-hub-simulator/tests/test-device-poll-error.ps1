# DEVICE_POLL Error Investigation
# Purpose: Get the full error response to understand what's wrong

$hubIp = "192.168.86.221"
$hubPort = 23

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    # Get device
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "error_check"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    Start-Sleep -Milliseconds 2000
    
    $device = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.type -eq "DEVICE_FOUND" -and $device -eq $null) {
                $device = $msg.data.uuid
            }
        }
    }
    
    Write-Host "Testing DEVICE_POLL with Format 2 (target at root)..." -ForegroundColor Yellow
    Write-Host "Device UUID: $device" -ForegroundColor Gray
    Write-Host ""
    
    $tid = [guid]::NewGuid().ToString()
    $pollRequest = @{
        transactionId = $tid
        type = "DEVICE_POLL"
        dst = "deako"
        src = "error_check"
        target = $device
    } | ConvertTo-Json -Compress

    Write-Host "Request:" -ForegroundColor Cyan
    Write-Host $pollRequest -ForegroundColor Gray
    Write-Host ""
    
    $writer.WriteLine($pollRequest)
    $stream.Flush()
    
    Start-Sleep -Milliseconds 2000
    
    Write-Host "Response(s):" -ForegroundColor Cyan
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host $line -ForegroundColor Gray
            $msg = $line | ConvertFrom-Json
            
            if ($msg.transactionId -eq $tid) {
                Write-Host ""
                Write-Host "Parsed:" -ForegroundColor Yellow
                Write-Host "  Type: $($msg.type)" -ForegroundColor White
                Write-Host "  Status: $($msg.status)" -ForegroundColor White
                if ($msg.status -eq "error") {
                    Write-Host "  Error Code: $($msg.data.code)" -ForegroundColor Red
                    Write-Host "  Error Message: $($msg.data.message)" -ForegroundColor Red
                }
            }
        }
    }
    
} finally {
    if ($client) { $client.Close() }
}
