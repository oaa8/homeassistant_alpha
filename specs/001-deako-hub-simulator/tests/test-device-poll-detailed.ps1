# Test DEVICE_POLL Behavior Thoroughly
# Date: October 18, 2025
# Purpose: Understand how DEVICE_POLL actually works

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub DEVICE_POLL Detailed Test ===" -ForegroundColor Cyan
Write-Host ""

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    Write-Host "Connected successfully" -ForegroundColor Green
    Write-Host ""

    # Get multiple devices
    Write-Host "Getting device list..." -ForegroundColor Yellow
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "poll_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    
    $devices = @()
    $timeout = [DateTime]::Now.AddSeconds(10)

    while ([DateTime]::Now -lt $timeout -and $devices.Count -lt 5) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $response = $line | ConvertFrom-Json
                
                if ($response.type -eq "DEVICE_FOUND") {
                    $devices += @{
                        UUID = $response.data.uuid
                        Name = $response.data.name
                        Capabilities = $response.data.capabilities
                        InitialPower = $response.data.state.power
                        InitialDim = $response.data.state.dim
                    }
                    Write-Host "  Device: $($response.data.name)" -ForegroundColor Gray
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }

    Write-Host "Found $($devices.Count) devices" -ForegroundColor Green
    Write-Host ""

    # Clear pending messages
    Start-Sleep -Milliseconds 500
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }

    Write-Host "=== Testing DEVICE_POLL for each device ===" -ForegroundColor Cyan
    Write-Host ""

    foreach ($device in $devices) {
        Write-Host "Polling: $($device.Name)" -ForegroundColor Yellow
        Write-Host "  Requested UUID: $($device.UUID)" -ForegroundColor Gray
        
        $transactionId = [guid]::NewGuid().ToString()
        $pollRequest = @{
            transactionId = $transactionId
            type = "DEVICE_POLL"
            dst = "deako"
            src = "poll_test"
            data = @{
                target = $device.UUID
            }
        } | ConvertTo-Json -Compress

        $writer.WriteLine($pollRequest)
        $stream.Flush()
        
        # Collect ALL responses for this poll
        $responseTimeout = [DateTime]::Now.AddSeconds(2)
        $responses = @()
        
        while ([DateTime]::Now -lt $responseTimeout) {
            if ($stream.DataAvailable) {
                $line = $reader.ReadLine()
                if ($line) {
                    try {
                        $response = $line | ConvertFrom-Json
                        $responses += $response
                    } catch {
                        # Ignore malformed
                    }
                }
            }
            Start-Sleep -Milliseconds 10
        }
        
        Write-Host "  Received $($responses.Count) response(s)" -ForegroundColor Gray
        
        foreach ($response in $responses) {
            if ($response.type -eq "DEVICE_FOUND") {
                $isMatch = $response.data.uuid -eq $device.UUID
                $matchStr = if ($isMatch) { "(MATCH)" } else { "(DIFFERENT!)" }
                Write-Host "  Response: $($response.data.name) $matchStr" -ForegroundColor $(if ($isMatch) { "Green" } else { "Red" })
                Write-Host "    Returned UUID: $($response.data.uuid)" -ForegroundColor Gray
                Write-Host "    State: power=$($response.data.state.power), dim=$($response.data.state.dim)" -ForegroundColor Gray
            }
        }
        
        Write-Host ""
        Start-Sleep -Milliseconds 200
    }

    Write-Host "=== ANALYSIS ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Does DEVICE_POLL return the requested device or all devices?" -ForegroundColor Yellow
    Write-Host "Check if returned UUIDs match requested UUIDs above." -ForegroundColor Gray

} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    if ($client -ne $null) {
        $client.Close()
        Write-Host ""
        Write-Host "Connection closed" -ForegroundColor Gray
    }
}
