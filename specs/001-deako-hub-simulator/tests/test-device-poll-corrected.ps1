# Test Deako Hub DEVICE_POLL - Corrected
# Date: October 18, 2025
# Purpose: Re-test DEVICE_POLL with correct message format and fresh connection

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub DEVICE_POLL Corrected Test ===" -ForegroundColor Cyan
Write-Host "Hub: $hubIp`:$hubPort"
Write-Host ""

try {
    # Connect to hub
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    Write-Host "Connected to hub successfully" -ForegroundColor Green
    Write-Host ""

    # Get a device to test with
    Write-Host "Getting device list..." -ForegroundColor Yellow
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "poll_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    
    $deviceUuid = $null
    $deviceName = $null
    $timeout = [DateTime]::Now.AddSeconds(10)

    while ([DateTime]::Now -lt $timeout -and $deviceUuid -eq $null) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $response = $line | ConvertFrom-Json
                
                if ($response.type -eq "DEVICE_FOUND" -and $deviceUuid -eq $null) {
                    if ($response.data.capabilities -match "dim") {
                        $deviceUuid = $response.data.uuid
                        $deviceName = $response.data.name
                        Write-Host "Found device: $deviceName" -ForegroundColor Green
                        Write-Host "  UUID: $deviceUuid" -ForegroundColor Gray
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }

    if ($deviceUuid -eq $null) {
        Write-Host "ERROR: Could not find a device" -ForegroundColor Red
        exit 1
    }

    # Clear any pending messages
    Start-Sleep -Milliseconds 500
    while ($stream.DataAvailable) {
        $null = $reader.ReadLine()
    }

    Write-Host ""
    Write-Host "=== Testing DEVICE_POLL (Correct Format) ===" -ForegroundColor Cyan
    Write-Host ""

    # According to API docs section 3.5, the correct format should be:
    # Note: API doc has a typo showing "PING" but it should be "DEVICE_POLL"
    # Response will be a DEVICE_FOUND message
    
    Write-Host "Sending DEVICE_POLL request..." -ForegroundColor Yellow
    $transactionId = [guid]::NewGuid().ToString()
    
    # Try with "target" in data field (like CONTROL)
    $pollRequest1 = @{
        transactionId = $transactionId
        type = "DEVICE_POLL"
        dst = "deako"
        src = "poll_test"
        data = @{
            target = $deviceUuid
        }
    } | ConvertTo-Json -Compress

    Write-Host "Format 1 (target in data):" -ForegroundColor Gray
    Write-Host "  $pollRequest1" -ForegroundColor DarkGray
    
    $writer.WriteLine($pollRequest1)
    $stream.Flush()
    
    # Wait for response
    $responseTimeout = [DateTime]::Now.AddSeconds(3)
    $gotResponse = $false
    
    while ([DateTime]::Now -lt $responseTimeout -and -not $gotResponse) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                Write-Host ""
                Write-Host "Received response:" -ForegroundColor Green
                Write-Host "  $line" -ForegroundColor Gray
                
                try {
                    $response = $line | ConvertFrom-Json
                    Write-Host ""
                    Write-Host "Parsed response:" -ForegroundColor Green
                    Write-Host "  Type: $($response.type)" -ForegroundColor Gray
                    
                    if ($response.type -eq "DEVICE_FOUND") {
                        Write-Host "  Name: $($response.data.name)" -ForegroundColor Gray
                        Write-Host "  UUID: $($response.data.uuid)" -ForegroundColor Gray
                        Write-Host "  Power: $($response.data.state.power)" -ForegroundColor Gray
                        Write-Host "  Dim: $($response.data.state.dim)" -ForegroundColor Gray
                        $gotResponse = $true
                    } elseif ($response.transactionId -eq $transactionId) {
                        Write-Host "  Status: $($response.status)" -ForegroundColor Gray
                        if ($response.status -eq "error") {
                            Write-Host "  Error code: $($response.data.code)" -ForegroundColor Red
                            Write-Host "  Error message: $($response.data.message)" -ForegroundColor Red
                        }
                        $gotResponse = $true
                    }
                } catch {
                    Write-Host "  Failed to parse: $($_.Exception.Message)" -ForegroundColor Red
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }
    
    if (-not $gotResponse) {
        Write-Host ""
        Write-Host "✗ No response received for Format 1" -ForegroundColor Red
        Write-Host ""
        
        # Try alternative format with "target" at top level (like API doc example)
        Write-Host "Trying Format 2 (target at top level)..." -ForegroundColor Yellow
        
        $transactionId2 = [guid]::NewGuid().ToString()
        $pollRequest2 = @{
            transactionId = $transactionId2
            type = "DEVICE_POLL"
            dst = "deako"
            src = "poll_test"
            target = $deviceUuid
        } | ConvertTo-Json -Compress

        Write-Host "Format 2 (target at root):" -ForegroundColor Gray
        Write-Host "  $pollRequest2" -ForegroundColor DarkGray
        
        $writer.WriteLine($pollRequest2)
        $stream.Flush()
        
        # Wait for response
        $responseTimeout2 = [DateTime]::Now.AddSeconds(3)
        $gotResponse2 = $false
        
        while ([DateTime]::Now -lt $responseTimeout2 -and -not $gotResponse2) {
            if ($stream.DataAvailable) {
                $line = $reader.ReadLine()
                if ($line) {
                    Write-Host ""
                    Write-Host "Received response:" -ForegroundColor Green
                    Write-Host "  $line" -ForegroundColor Gray
                    
                    try {
                        $response = $line | ConvertFrom-Json
                        Write-Host ""
                        Write-Host "Parsed response:" -ForegroundColor Green
                        Write-Host "  Type: $($response.type)" -ForegroundColor Gray
                        
                        if ($response.type -eq "DEVICE_FOUND") {
                            Write-Host "  Name: $($response.data.name)" -ForegroundColor Gray
                            Write-Host "  UUID: $($response.data.uuid)" -ForegroundColor Gray
                            Write-Host "  Power: $($response.data.state.power)" -ForegroundColor Gray
                            Write-Host "  Dim: $($response.data.state.dim)" -ForegroundColor Gray
                            $gotResponse2 = $true
                        } elseif ($response.transactionId -eq $transactionId2) {
                            Write-Host "  Status: $($response.status)" -ForegroundColor Gray
                            if ($response.status -eq "error") {
                                Write-Host "  Error code: $($response.data.code)" -ForegroundColor Red
                                Write-Host "  Error message: $($response.data.message)" -ForegroundColor Red
                            }
                            $gotResponse2 = $true
                        }
                    } catch {
                        Write-Host "  Failed to parse: $($_.Exception.Message)" -ForegroundColor Red
                    }
                }
            }
            Start-Sleep -Milliseconds 10
        }
        
        if (-not $gotResponse2) {
            Write-Host ""
            Write-Host "✗ No response received for Format 2" -ForegroundColor Red
            Write-Host ""
            Write-Host "Conclusion: DEVICE_POLL may not be implemented despite API docs" -ForegroundColor Yellow
        } else {
            Write-Host ""
            Write-Host "✓ DEVICE_POLL works with Format 2!" -ForegroundColor Green
        }
    } else {
        Write-Host ""
        Write-Host "✓ DEVICE_POLL works with Format 1!" -ForegroundColor Green
    }

} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
} finally {
    if ($client -ne $null) {
        $client.Close()
        Write-Host ""
        Write-Host "Connection closed" -ForegroundColor Gray
    }
}
