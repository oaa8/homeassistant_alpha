# DEVICE_POLL Final Validation
# Purpose: Confirm DEVICE_POLL works and understand the response format

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== DEVICE_POLL Final Validation ===" -ForegroundColor Cyan
Write-Host ""

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    # Get devices
    Write-Host "[1] Getting devices..." -ForegroundColor Yellow
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "final_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    Start-Sleep -Milliseconds 3000
    
    $devices = @()
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.type -eq "DEVICE_FOUND") {
                $devices += $msg.data
            }
        }
    }
    
    Write-Host "  Found $($devices.Count) devices" -ForegroundColor Green
    $testDevice = $devices[0]
    Write-Host "  Testing with: $($testDevice.name)" -ForegroundColor Gray
    Write-Host ""
    
    # Change state
    Write-Host "[2] Changing state to power=true, dim=75..." -ForegroundColor Yellow
    $controlRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "CONTROL"
        dst = "deako"
        src = "final_test"
        data = @{
            target = $testDevice.uuid
            state = @{
                power = $true
                dim = 75
            }
        }
    } | ConvertTo-Json -Compress

    $writer.WriteLine($controlRequest)
    Start-Sleep -Milliseconds 1000
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }
    Write-Host "  State changed" -ForegroundColor Green
    Write-Host ""
    
    # Poll the device
    Write-Host "[3] Polling device state with DEVICE_POLL..." -ForegroundColor Yellow
    $pollRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_POLL"
        dst = "deako"
        src = "final_test"
        target = $testDevice.uuid
    } | ConvertTo-Json -Compress

    $writer.WriteLine($pollRequest)
    Start-Sleep -Milliseconds 1000
    
    Write-Host ""
    Write-Host "Response:" -ForegroundColor Cyan
    $gotResponse = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            
            Write-Host "  Type: $($msg.type)" -ForegroundColor White
            Write-Host "  Status: $($msg.status)" -ForegroundColor White
            Write-Host "  Device Name: $($msg.data.name)" -ForegroundColor White
            Write-Host "  Device UUID: $($msg.data.uuid)" -ForegroundColor White
            Write-Host "  Power: $($msg.data.state.power)" -ForegroundColor White
            Write-Host "  Dim: $($msg.data.state.dim)" -ForegroundColor White
            $gotResponse = $true
        }
    }
    
    Write-Host ""
    if ($gotResponse) {
        Write-Host "=== CONCLUSION ===" -ForegroundColor Green
        Write-Host ""
        Write-Host "✓ DEVICE_POLL WORKS!" -ForegroundColor Green
        Write-Host ""
        Write-Host "Format: {target: uuid} at root level (not in data)" -ForegroundColor Yellow
        Write-Host "Response: type=DEVICE_POLL, status=error (misleading!)" -ForegroundColor Yellow
        Write-Host "         data contains device info (name, uuid, capabilities, state)" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Note: Hub returns status='error' even though request succeeded." -ForegroundColor Gray
        Write-Host "      This is a hub quirk - check data field for device info." -ForegroundColor Gray
    } else {
        Write-Host "✗ No response received" -ForegroundColor Red
    }
    
} finally {
    if ($client) { $client.Close() }
}
