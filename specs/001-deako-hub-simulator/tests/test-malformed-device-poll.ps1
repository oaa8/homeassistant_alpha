# Test Malformed DEVICE_POLL Requests
# Purpose: Determine if malformed DEVICE_POLL returns error or no response

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Malformed DEVICE_POLL Request Testing ===" -ForegroundColor Cyan
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
        src = "malform_test"
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
    # TEST 1: DEVICE_POLL with target in wrong place (in data field)
    # ============================================
    Write-Host "[Test 1] DEVICE_POLL with target in data field (wrong format)..." -ForegroundColor Yellow
    $test1Txn = [guid]::NewGuid().ToString()
    $test1Request = @{
        transactionId = $test1Txn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "malform_test"
        data = @{
            target = $validUuid  # WRONG: should be at root level
        }
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $test1Request" -ForegroundColor DarkGray
    $writer.WriteLine($test1Request)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    $gotResponse = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "    $line" -ForegroundColor White
            $gotResponse = $true
        }
    }
    if (-not $gotResponse) {
        Write-Host "    [NO RESPONSE]" -ForegroundColor Red
    }
    Write-Host ""

    # ============================================
    # TEST 2: DEVICE_POLL with missing target field entirely
    # ============================================
    Write-Host "[Test 2] DEVICE_POLL with missing target field..." -ForegroundColor Yellow
    $test2Txn = [guid]::NewGuid().ToString()
    $test2Request = @{
        transactionId = $test2Txn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "malform_test"
        # NO target field at all
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $test2Request" -ForegroundColor DarkGray
    $writer.WriteLine($test2Request)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    $gotResponse = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "    $line" -ForegroundColor White
            $gotResponse = $true
        }
    }
    if (-not $gotResponse) {
        Write-Host "    [NO RESPONSE]" -ForegroundColor Red
    }
    Write-Host ""

    # ============================================
    # TEST 3: DEVICE_POLL with invalid UUID format
    # ============================================
    Write-Host "[Test 3] DEVICE_POLL with invalid UUID format..." -ForegroundColor Yellow
    $test3Txn = [guid]::NewGuid().ToString()
    $test3Request = @{
        transactionId = $test3Txn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "malform_test"
        target = "not-a-valid-uuid-format"
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $test3Request" -ForegroundColor DarkGray
    $writer.WriteLine($test3Request)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    $gotResponse = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "    $line" -ForegroundColor White
            $msg = $line | ConvertFrom-Json
            Write-Host "    Status: $($msg.status)" -ForegroundColor White
            if ($msg.data.code) {
                Write-Host "    Error Code: $($msg.data.code)" -ForegroundColor White
                Write-Host "    Error Message: $($msg.data.message)" -ForegroundColor White
            }
            $gotResponse = $true
        }
    }
    if (-not $gotResponse) {
        Write-Host "    [NO RESPONSE]" -ForegroundColor Red
    }
    Write-Host ""

    # ============================================
    # TEST 4: DEVICE_POLL with non-existent but valid UUID format
    # ============================================
    Write-Host "[Test 4] DEVICE_POLL with non-existent UUID..." -ForegroundColor Yellow
    $test4Txn = [guid]::NewGuid().ToString()
    $test4Request = @{
        transactionId = $test4Txn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "malform_test"
        target = "00000000-0000-0000-0000-000000000000"
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $test4Request" -ForegroundColor DarkGray
    $writer.WriteLine($test4Request)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    $gotResponse = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "    $line" -ForegroundColor White
            $msg = $line | ConvertFrom-Json
            Write-Host "    Status: $($msg.status)" -ForegroundColor White
            if ($msg.data.code) {
                Write-Host "    Error Code: $($msg.data.code)" -ForegroundColor White
                Write-Host "    Error Message: $($msg.data.message)" -ForegroundColor White
            } elseif ($msg.data.name) {
                Write-Host "    [Has device data - not an error!]" -ForegroundColor Yellow
            }
            $gotResponse = $true
        }
    }
    if (-not $gotResponse) {
        Write-Host "    [NO RESPONSE]" -ForegroundColor Red
    }
    Write-Host ""

    # ============================================
    # TEST 5: VALID DEVICE_POLL (baseline)
    # ============================================
    Write-Host "[Test 5] VALID DEVICE_POLL (baseline for comparison)..." -ForegroundColor Yellow
    $test5Txn = [guid]::NewGuid().ToString()
    $test5Request = @{
        transactionId = $test5Txn
        type = "DEVICE_POLL"
        dst = "deako"
        src = "malform_test"
        target = $validUuid
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $test5Request" -ForegroundColor DarkGray
    $writer.WriteLine($test5Request)
    Start-Sleep -Milliseconds 2000

    Write-Host "  Response:" -ForegroundColor Cyan
    $gotResponse = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "    $line" -ForegroundColor White
            $msg = $line | ConvertFrom-Json
            Write-Host "    Status: $($msg.status)" -ForegroundColor White
            if ($msg.data.code) {
                Write-Host "    Error Code: $($msg.data.code)" -ForegroundColor White
                Write-Host "    Error Message: $($msg.data.message)" -ForegroundColor White
            } elseif ($msg.data.name) {
                Write-Host "    Device: $($msg.data.name)" -ForegroundColor Green
                Write-Host "    Power: $($msg.data.state.power)" -ForegroundColor Green
                Write-Host "    [Has device data with status=error - THIS IS THE QUIRK]" -ForegroundColor Yellow
            }
            $gotResponse = $true
        }
    }
    if (-not $gotResponse) {
        Write-Host "    [NO RESPONSE]" -ForegroundColor Red
    }
    Write-Host ""

    # ============================================
    Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "The goal is to determine:" -ForegroundColor White
    Write-Host "  - Do malformed DEVICE_POLL requests return REQUEST_MALFORMED error?" -ForegroundColor Gray
    Write-Host "  - Or do they return nothing (silent ignore)?" -ForegroundColor Gray
    Write-Host "  - Does valid DEVICE_POLL always return status='error' with device data?" -ForegroundColor Gray
    Write-Host ""
    Write-Host "If valid DEVICE_POLL returns status='error' but has device data (not error code/message)," -ForegroundColor White
    Write-Host "then this confirms it's a hub firmware bug/quirk that must be replicated." -ForegroundColor White

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
