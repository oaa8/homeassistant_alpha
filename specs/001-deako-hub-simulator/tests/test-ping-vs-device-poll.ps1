# Test PING vs DEVICE_POLL with target field
# Purpose: Verify which message type actually works for device polling

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== PING vs DEVICE_POLL Testing ===" -ForegroundColor Cyan
Write-Host ""

try {
    # Connect
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    # Get a real device UUID
    Write-Host "[Setup] Getting a valid device UUID..." -ForegroundColor Yellow
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "ping_vs_poll_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    Start-Sleep -Milliseconds 5000

    $validUuid = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.type -eq "DEVICE_FOUND" -and $validUuid -eq $null) {
                $validUuid = $msg.data.uuid
                Write-Host "  Valid UUID: $validUuid" -ForegroundColor Green
            }
        }
    }

    if (-not $validUuid) {
        Write-Host "  ERROR: Could not get valid UUID" -ForegroundColor Red
        exit 1
    }

    # Clear buffer
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }
    Write-Host ""

    # ============================================
    # TEST 1: Use type="PING" with target field (as API docs show)
    # ============================================
    Write-Host "[Test 1] Sending type='PING' with target field (per API docs section 3.5.1)..." -ForegroundColor Yellow
    $pingTxn = [guid]::NewGuid().ToString()
    $pingRequest = @{
        transactionId = $pingTxn
        type = "PING"
        dst = "deako"
        src = "ping_vs_poll_test"
        target = $validUuid
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $pingRequest" -ForegroundColor DarkGray
    $writer.WriteLine($pingRequest)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    $gotPingResponse = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "    $line" -ForegroundColor White
            $msg = $line | ConvertFrom-Json
            Write-Host "    Type: $($msg.type)" -ForegroundColor White
            Write-Host "    Status: $($msg.status)" -ForegroundColor White
            if ($msg.data.name) {
                Write-Host "    [Got device data: $($msg.data.name)]" -ForegroundColor Green
            } elseif ($msg.data.code) {
                Write-Host "    [Got error: $($msg.data.code) - $($msg.data.message)]" -ForegroundColor Red
            } else {
                Write-Host "    [Simple PING response]" -ForegroundColor Gray
            }
            $gotPingResponse = $true
        }
    }
    if (-not $gotPingResponse) {
        Write-Host "    [NO RESPONSE]" -ForegroundColor Red
    }
    Write-Host ""

    Start-Sleep -Milliseconds 500
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }

    # ============================================
    # TEST 2: Use type="DEVICE_POLL" with target field (what we've been using)
    # ============================================
    Write-Host "[Test 2] Sending type='DEVICE_POLL' with target field..." -ForegroundColor Yellow
    $pollTxn = [guid]::NewGuid().ToString()
    $pollRequest = @{
        transactionId = $pollTxn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "ping_vs_poll_test"
        target = $validUuid
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $pollRequest" -ForegroundColor DarkGray
    $writer.WriteLine($pollRequest)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    $gotPollResponse = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "    $line" -ForegroundColor White
            $msg = $line | ConvertFrom-Json
            Write-Host "    Type: $($msg.type)" -ForegroundColor White
            Write-Host "    Status: $($msg.status)" -ForegroundColor White
            if ($msg.data.name) {
                Write-Host "    [Got device data: $($msg.data.name)]" -ForegroundColor Green
            } elseif ($msg.data.code) {
                Write-Host "    [Got error: $($msg.data.code) - $($msg.data.message)]" -ForegroundColor Red
            }
            $gotPollResponse = $true
        }
    }
    if (-not $gotPollResponse) {
        Write-Host "    [NO RESPONSE]" -ForegroundColor Red
    }
    Write-Host ""

    Start-Sleep -Milliseconds 500
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }

    # ============================================
    # TEST 3: Use type="PING" WITHOUT target field (normal PING)
    # ============================================
    Write-Host "[Test 3] Sending type='PING' WITHOUT target field (normal ping)..." -ForegroundColor Yellow
    $ping2Txn = [guid]::NewGuid().ToString()
    $ping2Request = @{
        transactionId = $ping2Txn
        type = "PING"
        dst = "deako"
        src = "ping_vs_poll_test"
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $ping2Request" -ForegroundColor DarkGray
    $writer.WriteLine($ping2Request)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    $gotPing2Response = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "    $line" -ForegroundColor White
            $msg = $line | ConvertFrom-Json
            Write-Host "    Type: $($msg.type)" -ForegroundColor White
            Write-Host "    Status: $($msg.status)" -ForegroundColor White
            $gotPing2Response = $true
        }
    }
    if (-not $gotPing2Response) {
        Write-Host "    [NO RESPONSE]" -ForegroundColor Red
    }
    Write-Host ""

    # ============================================
    Write-Host "=== CONCLUSION ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "API.md section 3.5.1 shows type='PING' with target field" -ForegroundColor White
    Write-Host "But section 3.5 is titled 'Device Poll'" -ForegroundColor White
    Write-Host ""
    Write-Host "Which one actually works for device polling?" -ForegroundColor Yellow
    Write-Host "  - If PING with target returns device data: API docs are correct" -ForegroundColor Gray
    Write-Host "  - If DEVICE_POLL with target returns device data: API docs have typo" -ForegroundColor Gray
    Write-Host "  - If PING ignores target field: target is for DEVICE_POLL only" -ForegroundColor Gray

} catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    if ($client -ne $null) {
        $client.Close()
        Write-Host ""
        Write-Host "Connection closed" -ForegroundColor Gray
    }
}
