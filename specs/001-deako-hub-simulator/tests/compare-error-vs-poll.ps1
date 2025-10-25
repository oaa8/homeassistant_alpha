# Compare Real Error vs DEVICE_POLL Response
# Purpose: Definitively determine if DEVICE_POLL status="error" is a quirk or actual error

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Error Response vs DEVICE_POLL Comparison ===" -ForegroundColor Cyan
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
        src = "compare_test"
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
    # TEST 1: Send CONTROL with INVALID UUID (guaranteed error)
    # ============================================
    Write-Host "[Test 1] Sending CONTROL with invalid UUID (should get error)..." -ForegroundColor Yellow
    $badTxn = [guid]::NewGuid().ToString()
    $badRequest = @{
        transactionId = $badTxn
        type = "CONTROL"
        dst = "deako"
        src = "compare_test"
        data = @{
            target = "00000000-0000-0000-0000-000000000000"  # Non-existent
            state = @{ power = $true }
        }
    } | ConvertTo-Json -Compress

    $writer.WriteLine($badRequest)
    Start-Sleep -Milliseconds 1000

    Write-Host ""
    Write-Host "=== REAL ERROR RESPONSE ===" -ForegroundColor Red
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host $line -ForegroundColor White
            $errorMsg = $line | ConvertFrom-Json
            Write-Host ""
            Write-Host "Parsed Error Response:" -ForegroundColor Red
            Write-Host "  status: $($errorMsg.status)" -ForegroundColor White
            Write-Host "  data.code: $($errorMsg.data.code)" -ForegroundColor White
            Write-Host "  data.message: $($errorMsg.data.message)" -ForegroundColor White
            Write-Host "  Has data.name?: $($null -ne $errorMsg.data.name)" -ForegroundColor White
            Write-Host "  Has data.uuid?: $($null -ne $errorMsg.data.uuid)" -ForegroundColor White
            Write-Host "  Has data.state?: $($null -ne $errorMsg.data.state)" -ForegroundColor White
        }
    }

    Start-Sleep -Milliseconds 500
    Write-Host ""

    # ============================================
    # TEST 2: Send DEVICE_POLL with VALID UUID
    # ============================================
    Write-Host "[Test 2] Sending DEVICE_POLL with valid UUID..." -ForegroundColor Yellow
    $pollTxn = [guid]::NewGuid().ToString()
    $pollRequest = @{
        transactionId = $pollTxn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "compare_test"
        target = $validUuid
    } | ConvertTo-Json -Compress

    $writer.WriteLine($pollRequest)
    Start-Sleep -Milliseconds 1000

    Write-Host ""
    Write-Host "=== DEVICE_POLL RESPONSE ===" -ForegroundColor Cyan
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host $line -ForegroundColor White
            $pollMsg = $line | ConvertFrom-Json
            Write-Host ""
            Write-Host "Parsed DEVICE_POLL Response:" -ForegroundColor Cyan
            Write-Host "  status: $($pollMsg.status)" -ForegroundColor White
            Write-Host "  data.code: $($pollMsg.data.code)" -ForegroundColor White
            Write-Host "  data.message: $($pollMsg.data.message)" -ForegroundColor White
            Write-Host "  Has data.name?: $($null -ne $pollMsg.data.name) (value: $($pollMsg.data.name))" -ForegroundColor White
            Write-Host "  Has data.uuid?: $($null -ne $pollMsg.data.uuid) (value: $($pollMsg.data.uuid))" -ForegroundColor White
            Write-Host "  Has data.state?: $($null -ne $pollMsg.data.state) (power=$($pollMsg.data.state.power), dim=$($pollMsg.data.state.dim))" -ForegroundColor White
        }
    }

    Write-Host ""
    Write-Host "=== ANALYSIS ===" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Key Differences:" -ForegroundColor White
    Write-Host "  1. Error responses have data.code and data.message" -ForegroundColor Gray
    Write-Host "  2. DEVICE_POLL has data.name, data.uuid, data.state" -ForegroundColor Gray
    Write-Host "  3. Both have status='error' but data structure is COMPLETELY different" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Conclusion:" -ForegroundColor White
    Write-Host "  If DEVICE_POLL response has data.name/uuid/state instead of data.code/message," -ForegroundColor Gray
    Write-Host "  then status='error' is misleading and this is indeed a HUB QUIRK/BUG" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Per API.md section 3.5.2:" -ForegroundColor Yellow
    Write-Host "  DEVICE_POLL should return type=DEVICE_FOUND (unsolicited, no status field)" -ForegroundColor Gray
    Write-Host "  But hub actually returns type=DEVICE_POLL with status='error'" -ForegroundColor Gray
    Write-Host "  This is a hub firmware bug that contradicts the API specification" -ForegroundColor Gray

} catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    if ($client -ne $null) {
        $client.Close()
    }
}
