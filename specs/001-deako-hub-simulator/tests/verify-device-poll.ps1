# Verify DEVICE_POLL actual response format
# Purpose: Capture exact response to determine if status="error" quirk is real

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== DEVICE_POLL Response Verification ===" -ForegroundColor Cyan
Write-Host "This test will capture the EXACT response from the hub" -ForegroundColor Gray
Write-Host ""

try {
    # Connect
    Write-Host "[1] Connecting to hub..." -ForegroundColor Yellow
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true
    Write-Host "    Connected" -ForegroundColor Green
    Write-Host ""

    # Get devices with proper wait time
    Write-Host "[2] Requesting device list..." -ForegroundColor Yellow
    $deviceListTxn = [guid]::NewGuid().ToString()
    $deviceListRequest = @{
        transactionId = $deviceListTxn
        type = "DEVICE_LIST"
        dst = "deako"
        src = "verify_poll"
    } | ConvertTo-Json -Compress

    Write-Host "    Sending: $deviceListRequest" -ForegroundColor DarkGray
    $writer.WriteLine($deviceListRequest)
    $stream.Flush()

    # Wait for responses with longer timeout
    Write-Host "    Waiting for responses..." -ForegroundColor Gray
    Start-Sleep -Milliseconds 5000

    $deviceListResponse = $null
    $devices = @()
    $lineCount = 0

    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        $lineCount++
        if ($line) {
            try {
                $msg = $line | ConvertFrom-Json
                
                if ($msg.transactionId -eq $deviceListTxn -and $msg.type -eq "DEVICE_LIST") {
                    $deviceListResponse = $msg
                    Write-Host "    ✓ Got DEVICE_LIST response: $($msg.data.number_of_devices) devices" -ForegroundColor Green
                }
                elseif ($msg.type -eq "DEVICE_FOUND") {
                    $devices += $msg
                    Write-Host "    ✓ Found device: $($msg.data.name)" -ForegroundColor Gray
                }
            } catch {
                Write-Host "    [WARN] Non-JSON line: $line" -ForegroundColor Yellow
            }
        }
    }

    Write-Host "    Total lines read: $lineCount" -ForegroundColor Gray
    Write-Host "    Total devices found: $($devices.Count)" -ForegroundColor Green
    Write-Host ""

    if ($devices.Count -eq 0) {
        Write-Host "✗ No devices found - cannot test DEVICE_POLL" -ForegroundColor Red
        exit 1
    }

    # Pick first device
    $testDevice = $devices[0].data
    Write-Host "[3] Selected test device:" -ForegroundColor Yellow
    Write-Host "    Name: $($testDevice.name)" -ForegroundColor White
    Write-Host "    UUID: $($testDevice.uuid)" -ForegroundColor White
    Write-Host "    Capabilities: $($testDevice.capabilities)" -ForegroundColor White
    Write-Host "    Current state: power=$($testDevice.state.power), dim=$($testDevice.state.dim)" -ForegroundColor White
    Write-Host ""

    # Clear any pending messages
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }

    # Now test DEVICE_POLL
    Write-Host "[4] Sending DEVICE_POLL request..." -ForegroundColor Yellow
    $pollTxn = [guid]::NewGuid().ToString()
    $pollRequest = @{
        transactionId = $pollTxn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "verify_poll"
        target = $testDevice.uuid
    } | ConvertTo-Json -Compress

    Write-Host "    Request: $pollRequest" -ForegroundColor DarkGray
    $writer.WriteLine($pollRequest)
    $stream.Flush()

    # Wait for response
    Write-Host "    Waiting for response..." -ForegroundColor Gray
    Start-Sleep -Milliseconds 2000

    Write-Host ""
    Write-Host "=== RAW RESPONSE ===" -ForegroundColor Cyan
    $gotResponse = $false
    $responseCount = 0

    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        $responseCount++
        if ($line) {
            Write-Host ""
            Write-Host "Response #$responseCount (RAW):" -ForegroundColor Yellow
            Write-Host $line -ForegroundColor White
            Write-Host ""

            try {
                $msg = $line | ConvertFrom-Json
                
                Write-Host "Parsed fields:" -ForegroundColor Cyan
                Write-Host "  transactionId: $($msg.transactionId)" -ForegroundColor White
                Write-Host "  type: $($msg.type)" -ForegroundColor White
                Write-Host "  src: $($msg.src)" -ForegroundColor White
                Write-Host "  dst: $($msg.dst)" -ForegroundColor White
                Write-Host "  status: $($msg.status)" -ForegroundColor $(if ($msg.status -eq "error") { "Red" } else { "Green" })
                Write-Host "  timestamp: $($msg.timestamp)" -ForegroundColor White
                
                if ($msg.data) {
                    Write-Host "  data.name: $($msg.data.name)" -ForegroundColor White
                    Write-Host "  data.uuid: $($msg.data.uuid)" -ForegroundColor White
                    Write-Host "  data.capabilities: $($msg.data.capabilities)" -ForegroundColor White
                    Write-Host "  data.state.power: $($msg.data.state.power)" -ForegroundColor White
                    Write-Host "  data.state.dim: $($msg.data.state.dim)" -ForegroundColor White
                }

                $gotResponse = $true

                # Check if transactionId matches
                if ($msg.transactionId -eq $pollTxn) {
                    Write-Host ""
                    Write-Host "✓ TransactionId MATCHES our request" -ForegroundColor Green
                } else {
                    Write-Host ""
                    Write-Host "⚠ TransactionId does NOT match (expected: $pollTxn)" -ForegroundColor Yellow
                }

            } catch {
                Write-Host "  [ERROR parsing JSON]: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }

    Write-Host ""
    Write-Host "=== CONCLUSION ===" -ForegroundColor Cyan
    Write-Host ""

    if ($gotResponse) {
        Write-Host "✓ DEVICE_POLL got a response" -ForegroundColor Green
        Write-Host ""
        Write-Host "ANALYSIS:" -ForegroundColor Yellow
        Write-Host "- Check if type is DEVICE_POLL or DEVICE_FOUND" -ForegroundColor Gray
        Write-Host "- Check if status field exists and its value" -ForegroundColor Gray
        Write-Host "- Check if data field contains device information" -ForegroundColor Gray
        Write-Host ""
        Write-Host "Compare this to API.md section 3.5.2 which says:" -ForegroundColor Yellow
        Write-Host '  Response should be type="DEVICE_FOUND" (unsolicited format)' -ForegroundColor Gray
        Write-Host "  Response should NOT have status field" -ForegroundColor Gray
    } else {
        Write-Host "✗ NO RESPONSE received for DEVICE_POLL" -ForegroundColor Red
        Write-Host ""
        Write-Host "Possible reasons:" -ForegroundColor Yellow
        Write-Host "- DEVICE_POLL not supported by this hub firmware" -ForegroundColor Gray
        Write-Host "- Request format incorrect" -ForegroundColor Gray
        Write-Host "- Hub silently rejects unknown message types" -ForegroundColor Gray
    }

} catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
} finally {
    if ($client -ne $null) {
        $client.Close()
        Write-Host ""
        Write-Host "Connection closed" -ForegroundColor Gray
    }
}
