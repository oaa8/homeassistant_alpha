# Error Code Validation Test
# Date: October 18, 2025
# Purpose: Trigger and validate all documented error codes
# Gap: Verify error codes exist, their format, and conditions that trigger them

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub Error Code Validation Test ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Testing 5 documented error codes:" -ForegroundColor Gray
Write-Host "  1. DEVICE_BUSY - Commands sent too rapidly" -ForegroundColor Gray
Write-Host "  2. DEVICE_UNKNOWN - Non-existent device UUID" -ForegroundColor Gray
Write-Host "  3. REQUEST_UNKNOWN - Invalid message type" -ForegroundColor Gray
Write-Host "  4. REQUEST_MALFORMED - Invalid JSON structure" -ForegroundColor Gray
Write-Host "  5. REQUEST_INVALID - Invalid data values" -ForegroundColor Gray
Write-Host ""

$errorsSeen = @{}
$testResults = @()

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    Write-Host "Connected to hub" -ForegroundColor Green
    Write-Host ""

    # ============================================
    # TEST 1: DEVICE_UNKNOWN
    # ============================================
    Write-Host "[TEST 1] DEVICE_UNKNOWN - Non-existent device UUID" -ForegroundColor Yellow
    Write-Host ""
    
    $fakeUuid = "00000000-0000-0000-0000-000000000000"
    $tid1 = [guid]::NewGuid().ToString()
    
    $request1 = @{
        transactionId = $tid1
        type = "CONTROL"
        dst = "deako"
        src = "error_test"
        data = @{
            target = $fakeUuid
            state = @{ power = $true }
        }
    } | ConvertTo-Json -Compress

    Write-Host "Sending CONTROL for non-existent device:" -ForegroundColor Gray
    Write-Host "  UUID: $fakeUuid" -ForegroundColor DarkGray
    
    $writer.WriteLine($request1)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $response1 = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.transactionId -eq $tid1) {
                $response1 = $msg
            }
        }
    }
    
    if ($response1 -and $response1.status -eq "error") {
        Write-Host "  ✓ Got error response" -ForegroundColor Green
        Write-Host "    Error code: $($response1.data.code)" -ForegroundColor Cyan
        Write-Host "    Error message: $($response1.data.message)" -ForegroundColor Gray
        $errorsSeen[$response1.data.code] = $true
        $testResults += @{ Test = "DEVICE_UNKNOWN"; Expected = "DEVICE_UNKNOWN"; Actual = $response1.data.code; Success = ($response1.data.code -eq "DEVICE_UNKNOWN") }
    } else {
        Write-Host "  ✗ No error response (got: $($response1.status))" -ForegroundColor Red
        $testResults += @{ Test = "DEVICE_UNKNOWN"; Expected = "DEVICE_UNKNOWN"; Actual = "No error"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 2: REQUEST_UNKNOWN
    # ============================================
    Write-Host "[TEST 2] REQUEST_UNKNOWN - Invalid message type" -ForegroundColor Yellow
    Write-Host ""
    
    $tid2 = [guid]::NewGuid().ToString()
    $request2 = @{
        transactionId = $tid2
        type = "INVALID_TYPE_DOES_NOT_EXIST"
        dst = "deako"
        src = "error_test"
    } | ConvertTo-Json -Compress

    Write-Host "Sending message with invalid type:" -ForegroundColor Gray
    Write-Host "  Type: INVALID_TYPE_DOES_NOT_EXIST" -ForegroundColor DarkGray
    
    $writer.WriteLine($request2)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $response2 = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.transactionId -eq $tid2) {
                $response2 = $msg
            }
        }
    }
    
    if ($response2 -and $response2.status -eq "error") {
        Write-Host "  ✓ Got error response" -ForegroundColor Green
        Write-Host "    Error code: $($response2.data.code)" -ForegroundColor Cyan
        Write-Host "    Error message: $($response2.data.message)" -ForegroundColor Gray
        $errorsSeen[$response2.data.code] = $true
        $testResults += @{ Test = "REQUEST_UNKNOWN"; Expected = "REQUEST_UNKNOWN"; Actual = $response2.data.code; Success = ($response2.data.code -eq "REQUEST_UNKNOWN") }
    } else {
        Write-Host "  ✗ No error response" -ForegroundColor Red
        $testResults += @{ Test = "REQUEST_UNKNOWN"; Expected = "REQUEST_UNKNOWN"; Actual = "No error"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 3: REQUEST_MALFORMED
    # ============================================
    Write-Host "[TEST 3] REQUEST_MALFORMED - Invalid JSON" -ForegroundColor Yellow
    Write-Host ""
    
    Write-Host "Sending malformed JSON:" -ForegroundColor Gray
    Write-Host "  {this is not valid json}" -ForegroundColor DarkGray
    
    $writer.WriteLine("{this is not valid json}")
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $response3 = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            try {
                $msg = $line | ConvertFrom-Json
                if ($msg.status -eq "error" -and $msg.data.code -eq "REQUEST_MALFORMED") {
                    $response3 = $msg
                }
            } catch {
                # Could be malformed response
            }
        }
    }
    
    if ($response3) {
        Write-Host "  ✓ Got error response" -ForegroundColor Green
        Write-Host "    Error code: $($response3.data.code)" -ForegroundColor Cyan
        Write-Host "    Error message: $($response3.data.message)" -ForegroundColor Gray
        $errorsSeen[$response3.data.code] = $true
        $testResults += @{ Test = "REQUEST_MALFORMED"; Expected = "REQUEST_MALFORMED"; Actual = $response3.data.code; Success = $true }
    } else {
        Write-Host "  ✗ No error response (hub may silently ignore)" -ForegroundColor Yellow
        $testResults += @{ Test = "REQUEST_MALFORMED"; Expected = "REQUEST_MALFORMED"; Actual = "No response"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 4: REQUEST_INVALID
    # ============================================
    Write-Host "[TEST 4] REQUEST_INVALID - Missing required fields" -ForegroundColor Yellow
    Write-Host ""
    
    $tid4 = [guid]::NewGuid().ToString()
    $request4 = @{
        transactionId = $tid4
        type = "CONTROL"
        dst = "deako"
        src = "error_test"
        # Missing 'data' field entirely
    } | ConvertTo-Json -Compress

    Write-Host "Sending CONTROL without data field:" -ForegroundColor Gray
    
    $writer.WriteLine($request4)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $response4 = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.transactionId -eq $tid4) {
                $response4 = $msg
            }
        }
    }
    
    if ($response4 -and $response4.status -eq "error") {
        Write-Host "  ✓ Got error response" -ForegroundColor Green
        Write-Host "    Error code: $($response4.data.code)" -ForegroundColor Cyan
        Write-Host "    Error message: $($response4.data.message)" -ForegroundColor Gray
        $errorsSeen[$response4.data.code] = $true
        $testResults += @{ Test = "REQUEST_INVALID"; Expected = "REQUEST_INVALID"; Actual = $response4.data.code; Success = ($response4.data.code -eq "REQUEST_INVALID") }
    } else {
        Write-Host "  ✗ No error response" -ForegroundColor Red
        $testResults += @{ Test = "REQUEST_INVALID"; Expected = "REQUEST_INVALID"; Actual = "No error"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 5: DEVICE_BUSY (we know this doesn't exist)
    # ============================================
    Write-Host "[TEST 5] DEVICE_BUSY - Rapid commands (expected: NOT triggered)" -ForegroundColor Yellow
    Write-Host ""
    
    # Get a real device first
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "error_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    Start-Sleep -Milliseconds 2000
    
    $realDevice = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.type -eq "DEVICE_FOUND" -and $realDevice -eq $null) {
                $realDevice = $msg.data.uuid
            }
        }
    }
    
    Write-Host "Sending 20 rapid commands (0ms delay):" -ForegroundColor Gray
    
    $deviceBusyCount = 0
    for ($i = 0; $i -lt 20; $i++) {
        $tid = [guid]::NewGuid().ToString()
        $rapidRequest = @{
            transactionId = $tid
            type = "CONTROL"
            dst = "deako"
            src = "error_test"
            data = @{
                target = $realDevice
                state = @{ power = $true }
            }
        } | ConvertTo-Json -Compress
        
        $writer.WriteLine($rapidRequest)
    }
    $stream.Flush()
    
    Start-Sleep -Milliseconds 2000
    
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.status -eq "error" -and $msg.data.code -eq "DEVICE_BUSY") {
                $deviceBusyCount++
                $errorsSeen["DEVICE_BUSY"] = $true
            }
        }
    }
    
    if ($deviceBusyCount -gt 0) {
        Write-Host "  ⚠ Got $deviceBusyCount DEVICE_BUSY error(s)" -ForegroundColor Yellow
        Write-Host "    This contradicts previous testing!" -ForegroundColor Red
        $testResults += @{ Test = "DEVICE_BUSY"; Expected = "Not triggered"; Actual = "$deviceBusyCount errors"; Success = $false }
    } else {
        Write-Host "  ✓ No DEVICE_BUSY errors (as expected from prior tests)" -ForegroundColor Green
        $testResults += @{ Test = "DEVICE_BUSY"; Expected = "Not triggered"; Actual = "No errors"; Success = $true }
    }
    Write-Host ""

    # ============================================
    # TEST 6: Invalid UUID format
    # ============================================
    Write-Host "[TEST 6] Invalid UUID format" -ForegroundColor Yellow
    Write-Host ""
    
    $tid6 = [guid]::NewGuid().ToString()
    $request6 = @{
        transactionId = $tid6
        type = "CONTROL"
        dst = "deako"
        src = "error_test"
        data = @{
            target = "not-a-valid-uuid"
            state = @{ power = $true }
        }
    } | ConvertTo-Json -Compress

    Write-Host "Sending CONTROL with invalid UUID format:" -ForegroundColor Gray
    Write-Host "  UUID: 'not-a-valid-uuid'" -ForegroundColor DarkGray
    
    $writer.WriteLine($request6)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $response6 = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.transactionId -eq $tid6) {
                $response6 = $msg
            }
        }
    }
    
    if ($response6 -and $response6.status -eq "error") {
        Write-Host "  ✓ Got error response" -ForegroundColor Green
        Write-Host "    Error code: $($response6.data.code)" -ForegroundColor Cyan
        Write-Host "    Error message: $($response6.data.message)" -ForegroundColor Gray
        $errorsSeen[$response6.data.code] = $true
        $testResults += @{ Test = "Invalid UUID"; Expected = "REQUEST_INVALID or DEVICE_UNKNOWN"; Actual = $response6.data.code; Success = $true }
    } else {
        Write-Host "  ✗ No error response" -ForegroundColor Red
        $testResults += @{ Test = "Invalid UUID"; Expected = "Error"; Actual = "No error"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # SUMMARY
    # ============================================
    Write-Host "=== TEST SUMMARY ===" -ForegroundColor Cyan
    Write-Host ""
    
    Write-Host "Error codes triggered:" -ForegroundColor Yellow
    if ($errorsSeen.Count -eq 0) {
        Write-Host "  None" -ForegroundColor Red
    } else {
        foreach ($code in $errorsSeen.Keys) {
            Write-Host "  ✓ $code" -ForegroundColor Green
        }
    }
    Write-Host ""
    
    Write-Host "Test results:" -ForegroundColor Yellow
    foreach ($result in $testResults) {
        $status = if ($result.Success) { "✓" } else { "✗" }
        $color = if ($result.Success) { "Green" } else { "Red" }
        Write-Host "  $status $($result.Test): Expected '$($result.Expected)', Got '$($result.Actual)'" -ForegroundColor $color
    }
    Write-Host ""
    
    $successCount = ($testResults | Where-Object { $_.Success }).Count
    $totalCount = $testResults.Count
    
    Write-Host "Success rate: $successCount/$totalCount tests passed" -ForegroundColor $(if ($successCount -eq $totalCount) { "Green" } else { "Yellow" })
    Write-Host ""
    
    Write-Host "Documented error codes:" -ForegroundColor Cyan
    Write-Host "  DEVICE_BUSY - $(if ($errorsSeen.ContainsKey('DEVICE_BUSY')) { '✓ Triggered' } else { '✗ Not triggered (matches prior testing)' })" -ForegroundColor Gray
    Write-Host "  DEVICE_UNKNOWN - $(if ($errorsSeen.ContainsKey('DEVICE_UNKNOWN')) { '✓ Triggered' } else { '✗ Not triggered' })" -ForegroundColor Gray
    Write-Host "  REQUEST_UNKNOWN - $(if ($errorsSeen.ContainsKey('REQUEST_UNKNOWN')) { '✓ Triggered' } else { '✗ Not triggered' })" -ForegroundColor Gray
    Write-Host "  REQUEST_MALFORMED - $(if ($errorsSeen.ContainsKey('REQUEST_MALFORMED')) { '✓ Triggered' } else { '✗ Not triggered' })" -ForegroundColor Gray
    Write-Host "  REQUEST_INVALID - $(if ($errorsSeen.ContainsKey('REQUEST_INVALID')) { '✓ Triggered' } else { '✗ Not triggered' })" -ForegroundColor Gray

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
