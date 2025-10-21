# Message Format Edge Cases Test
# Date: October 18, 2025
# Purpose: Test hub's handling of various message format edge cases
# Gap: Extra fields, missing optional fields, field order, case sensitivity, whitespace

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub Message Format Edge Cases Test ===" -ForegroundColor Cyan
Write-Host ""

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

    # Get a real device UUID
    Write-Host "Getting device UUID..." -ForegroundColor Gray
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "edge_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    Start-Sleep -Milliseconds 2000
    
    $testDevice = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.type -eq "DEVICE_FOUND" -and $testDevice -eq $null) {
                $testDevice = $msg.data.uuid
            }
        }
    }
    Write-Host "Using device: $testDevice" -ForegroundColor Gray
    Write-Host ""

    # ============================================
    # TEST 1: Extra fields in message
    # ============================================
    Write-Host "[TEST 1] Extra fields in message" -ForegroundColor Yellow
    
    $tid1 = [guid]::NewGuid().ToString()
    $request1 = @{
        transactionId = $tid1
        type = "PING"
        dst = "deako"
        src = "edge_test"
        extraField1 = "this should be ignored"
        extraField2 = 12345
        extraField3 = $true
    } | ConvertTo-Json -Compress

    Write-Host "Sending PING with extra fields..." -ForegroundColor Gray
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
    
    if ($response1 -and $response1.status -eq "ok") {
        Write-Host "  ✓ Hub accepted message with extra fields" -ForegroundColor Green
        $testResults += @{ Test = "Extra fields"; Result = "Accepted"; Success = $true }
    } else {
        Write-Host "  ✗ Hub rejected message" -ForegroundColor Red
        $testResults += @{ Test = "Extra fields"; Result = "Rejected"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 2: Field order variation
    # ============================================
    Write-Host "[TEST 2] Field order variation" -ForegroundColor Yellow
    
    $tid2 = [guid]::NewGuid().ToString()
    # Manually construct JSON with different field order
    $request2 = "{`"src`":`"edge_test`",`"dst`":`"deako`",`"type`":`"PING`",`"transactionId`":`"$tid2`"}"

    Write-Host "Sending PING with fields in unusual order..." -ForegroundColor Gray
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
    
    if ($response2 -and $response2.status -eq "ok") {
        Write-Host "  ✓ Hub accepts different field order" -ForegroundColor Green
        $testResults += @{ Test = "Field order"; Result = "Order independent"; Success = $true }
    } else {
        Write-Host "  ✗ Hub requires specific field order" -ForegroundColor Yellow
        $testResults += @{ Test = "Field order"; Result = "Order dependent"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 3: Case sensitivity - message type
    # ============================================
    Write-Host "[TEST 3] Case sensitivity - message type" -ForegroundColor Yellow
    
    $tid3 = [guid]::NewGuid().ToString()
    $request3 = @{
        transactionId = $tid3
        type = "ping"  # lowercase instead of PING
        dst = "deako"
        src = "edge_test"
    } | ConvertTo-Json -Compress

    Write-Host "Sending 'ping' (lowercase) instead of 'PING'..." -ForegroundColor Gray
    $writer.WriteLine($request3)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $response3 = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.transactionId -eq $tid3) {
                $response3 = $msg
            }
        }
    }
    
    if ($response3 -and $response3.status -eq "ok") {
        Write-Host "  ✓ Hub is case-insensitive for message type" -ForegroundColor Green
        $testResults += @{ Test = "Type case sensitivity"; Result = "Case insensitive"; Success = $true }
    } elseif ($response3 -and $response3.status -eq "error") {
        Write-Host "  ✗ Hub is case-sensitive (got error)" -ForegroundColor Yellow
        Write-Host "    Error: $($response3.data.code) - $($response3.data.message)" -ForegroundColor Gray
        $testResults += @{ Test = "Type case sensitivity"; Result = "Case sensitive"; Success = $false }
    } else {
        Write-Host "  ✗ No response" -ForegroundColor Red
        $testResults += @{ Test = "Type case sensitivity"; Result = "No response"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 4: JSON with extra whitespace
    # ============================================
    Write-Host "[TEST 4] JSON with extra whitespace" -ForegroundColor Yellow
    
    $tid4 = [guid]::NewGuid().ToString()
    # JSON with lots of whitespace
    $request4 = @"
{
    "transactionId" : "$tid4"  ,
    "type"  :   "PING"   ,
    "dst"   :   "deako"  ,
    "src"   :   "edge_test"
}
"@

    Write-Host "Sending pretty-printed JSON with extra whitespace..." -ForegroundColor Gray
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
    
    if ($response4 -and $response4.status -eq "ok") {
        Write-Host "  ✓ Hub handles whitespace correctly" -ForegroundColor Green
        $testResults += @{ Test = "Extra whitespace"; Result = "Handled"; Success = $true }
    } else {
        Write-Host "  ✗ Hub rejected whitespace" -ForegroundColor Red
        $testResults += @{ Test = "Extra whitespace"; Result = "Rejected"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 5: Missing optional timestamp field
    # ============================================
    Write-Host "[TEST 5] Missing optional timestamp field (client → hub)" -ForegroundColor Yellow
    
    $tid5 = [guid]::NewGuid().ToString()
    # PING typically doesn't need timestamp from client
    $request5 = @{
        transactionId = $tid5
        type = "PING"
        dst = "deako"
        src = "edge_test"
        # No timestamp field
    } | ConvertTo-Json -Compress

    Write-Host "Sending PING without timestamp..." -ForegroundColor Gray
    $writer.WriteLine($request5)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $response5 = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.transactionId -eq $tid5) {
                $response5 = $msg
            }
        }
    }
    
    if ($response5 -and $response5.status -eq "ok") {
        Write-Host "  ✓ Timestamp is optional for client messages" -ForegroundColor Green
        $testResults += @{ Test = "Optional timestamp"; Result = "Optional"; Success = $true }
    } else {
        Write-Host "  ✗ Timestamp may be required" -ForegroundColor Yellow
        $testResults += @{ Test = "Optional timestamp"; Result = "Required?"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 6: Null values
    # ============================================
    Write-Host "[TEST 6] Null values in data field" -ForegroundColor Yellow
    
    $tid6 = [guid]::NewGuid().ToString()
    $request6 = @{
        transactionId = $tid6
        type = "CONTROL"
        dst = "deako"
        src = "edge_test"
        data = @{
            target = $testDevice
            state = @{
                power = $true
                dim = $null  # Null dim value
            }
        }
    } | ConvertTo-Json -Compress

    Write-Host "Sending CONTROL with dim=null..." -ForegroundColor Gray
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
    
    if ($response6 -and $response6.status -eq "ok") {
        Write-Host "  ✓ Hub accepts null values" -ForegroundColor Green
        $testResults += @{ Test = "Null values"; Result = "Accepted"; Success = $true }
    } elseif ($response6 -and $response6.status -eq "error") {
        Write-Host "  ✗ Hub rejects null values" -ForegroundColor Yellow
        Write-Host "    Error: $($response6.data.code) - $($response6.data.message)" -ForegroundColor Gray
        $testResults += @{ Test = "Null values"; Result = "Rejected"; Success = $false }
    } else {
        Write-Host "  ✗ No response" -ForegroundColor Red
        $testResults += @{ Test = "Null values"; Result = "No response"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 7: Unicode characters in strings
    # ============================================
    Write-Host "[TEST 7] Unicode characters in src field" -ForegroundColor Yellow
    
    $tid7 = [guid]::NewGuid().ToString()
    $request7 = @{
        transactionId = $tid7
        type = "PING"
        dst = "deako"
        src = "test_émojis_😀_中文"
    } | ConvertTo-Json -Compress

    Write-Host "Sending PING with Unicode characters..." -ForegroundColor Gray
    $writer.WriteLine($request7)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $response7 = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.transactionId -eq $tid7) {
                $response7 = $msg
            }
        }
    }
    
    if ($response7 -and $response7.status -eq "ok") {
        Write-Host "  ✓ Hub handles Unicode correctly" -ForegroundColor Green
        $testResults += @{ Test = "Unicode"; Result = "Handled"; Success = $true }
    } else {
        Write-Host "  ✗ Hub may not handle Unicode" -ForegroundColor Yellow
        $testResults += @{ Test = "Unicode"; Result = "Issue"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # TEST 8: Very long string values
    # ============================================
    Write-Host "[TEST 8] Very long string in src field" -ForegroundColor Yellow
    
    $tid8 = [guid]::NewGuid().ToString()
    $longString = "A" * 1000  # 1000 character string
    $request8 = @{
        transactionId = $tid8
        type = "PING"
        dst = "deako"
        src = $longString
    } | ConvertTo-Json -Compress

    Write-Host "Sending PING with 1000-char src field..." -ForegroundColor Gray
    $writer.WriteLine($request8)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $response8 = $null
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.transactionId -eq $tid8) {
                $response8 = $msg
            }
        }
    }
    
    if ($response8 -and $response8.status -eq "ok") {
        Write-Host "  ✓ Hub accepts long strings" -ForegroundColor Green
        $testResults += @{ Test = "Long strings"; Result = "Accepted"; Success = $true }
    } else {
        Write-Host "  ⚠ Hub may have string length limits" -ForegroundColor Yellow
        $testResults += @{ Test = "Long strings"; Result = "May have limits"; Success = $false }
    }
    Write-Host ""

    # ============================================
    # SUMMARY
    # ============================================
    Write-Host "=== TEST SUMMARY ===" -ForegroundColor Cyan
    Write-Host ""
    
    foreach ($result in $testResults) {
        $icon = if ($result.Success) { "✓" } else { "✗" }
        $color = if ($result.Success) { "Green" } else { "Yellow" }
        Write-Host "  $icon $($result.Test): $($result.Result)" -ForegroundColor $color
    }
    Write-Host ""
    
    $successCount = ($testResults | Where-Object { $_.Success }).Count
    Write-Host "Passed: $successCount/$($testResults.Count) tests" -ForegroundColor $(if ($successCount -eq $testResults.Count) { "Green" } else { "Yellow" })

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
