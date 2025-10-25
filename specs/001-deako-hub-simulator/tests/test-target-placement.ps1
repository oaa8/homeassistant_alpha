# Test if target should be in data field vs root level
# Purpose: Determine if target placement affects the error status

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Target Field Placement Test ===" -ForegroundColor Cyan
Write-Host ""

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    # Get device UUID
    Write-Host "[Setup] Getting device UUID..." -ForegroundColor Yellow
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "target_placement_test"
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
            }
        }
    }
    Write-Host "  UUID: $validUuid" -ForegroundColor Green
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }
    Write-Host ""

    # ============================================
    # TEST 1: target at ROOT level (what we've been using)
    # ============================================
    Write-Host "[Test 1] target at ROOT level..." -ForegroundColor Yellow
    $test1Txn = [guid]::NewGuid().ToString()
    $test1 = @{
        transactionId = $test1Txn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "target_placement_test"
        target = $validUuid
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $test1" -ForegroundColor DarkGray
    $writer.WriteLine($test1)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            Write-Host "    status: $($msg.status)" -ForegroundColor $(if ($msg.status -eq "ok") { "Green" } else { "Red" })
            if ($msg.data.name) {
                Write-Host "    Got device data: $($msg.data.name)" -ForegroundColor White
            } elseif ($msg.data.code) {
                Write-Host "    Error: $($msg.data.code) - $($msg.data.message)" -ForegroundColor Red
            }
        }
    }
    Write-Host ""

    Start-Sleep -Milliseconds 500
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }

    # ============================================
    # TEST 2: target in DATA field (maybe more correct?)
    # ============================================
    Write-Host "[Test 2] target in DATA field..." -ForegroundColor Yellow
    $test2Txn = [guid]::NewGuid().ToString()
    $test2 = @{
        transactionId = $test2Txn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "target_placement_test"
        data = @{
            target = $validUuid
        }
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $test2" -ForegroundColor DarkGray
    $writer.WriteLine($test2)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    $gotResponse = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            Write-Host "    status: $($msg.status)" -ForegroundColor $(if ($msg.status -eq "ok") { "Green" } else { "Red" })
            if ($msg.data.name) {
                Write-Host "    Got device data: $($msg.data.name)" -ForegroundColor White
            } elseif ($msg.data.code) {
                Write-Host "    Error: $($msg.data.code) - $($msg.data.message)" -ForegroundColor Red
            }
            $gotResponse = $true
        }
    }
    if (-not $gotResponse) {
        Write-Host "    [NO RESPONSE - silently ignored]" -ForegroundColor Red
    }
    Write-Host ""

    Start-Sleep -Milliseconds 500
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }

    # ============================================
    # TEST 3: Compare with CONTROL (which uses target in data)
    # ============================================
    Write-Host "[Test 3] CONTROL with target in DATA (for comparison)..." -ForegroundColor Yellow
    $test3Txn = [guid]::NewGuid().ToString()
    $test3 = @{
        transactionId = $test3Txn
        type = "CONTROL"
        dst = "deako"
        src = "target_placement_test"
        data = @{
            target = $validUuid
            state = @{ power = $true }
        }
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $test3" -ForegroundColor DarkGray
    $writer.WriteLine($test3)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            Write-Host "    status: $($msg.status)" -ForegroundColor $(if ($msg.status -eq "ok") { "Green" } else { "Red" })
            if ($msg.data.code) {
                Write-Host "    Error: $($msg.data.code) - $($msg.data.message)" -ForegroundColor Red
            } else {
                Write-Host "    CONTROL acknowledged" -ForegroundColor White
            }
        }
    }
    Write-Host ""

    # ============================================
    Write-Host "=== ANALYSIS ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Question: Is DEVICE_POLL returning status='error' because target is in wrong place?" -ForegroundColor White
    Write-Host ""
    Write-Host "Expected outcomes:" -ForegroundColor Yellow
    Write-Host "  - If target at root is WRONG: should get REQUEST_MALFORMED error" -ForegroundColor Gray
    Write-Host "  - If target in data is CORRECT: should get status='ok' with device data" -ForegroundColor Gray
    Write-Host "  - If BOTH work but one has bug: status field differs but both return data" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Note: CONTROL uses data.target (per API docs section 3.3)" -ForegroundColor Yellow
    Write-Host "So logically DEVICE_POLL should also use data.target" -ForegroundColor Yellow
    Write-Host "But the (buggy) API docs show target at root level" -ForegroundColor Yellow

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
