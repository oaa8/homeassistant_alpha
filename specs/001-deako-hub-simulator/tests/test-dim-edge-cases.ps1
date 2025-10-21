# Test Deako Hub Edge Case Dim Values
# Date: October 18, 2025
# Purpose: Determine how hub handles invalid dim values (negative, >100, non-numeric, etc.)
# Expected: REQUEST_INVALID error with descriptive messages (per FR-071)

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub Edge Case Dim Values Test ===" -ForegroundColor Cyan
Write-Host "Hub: $hubIp`:$hubPort"
Write-Host "Test: Sending control commands with invalid dim values"
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

    # Get a dimmable device to test with
    Write-Host "Finding a dimmable device..." -ForegroundColor Yellow
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "edge_case_test"
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
                    # Check if device supports dimming (has "dim" in capabilities)
                    if ($response.data.capabilities -match "dim") {
                        $deviceUuid = $response.data.uuid
                        $deviceName = $response.data.name
                        Write-Host "Found dimmable device: $deviceName" -ForegroundColor Green
                        Write-Host "  UUID: $deviceUuid" -ForegroundColor Gray
                        Write-Host "  Capabilities: $($response.data.capabilities)" -ForegroundColor Gray
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }

    if ($deviceUuid -eq $null) {
        Write-Host "ERROR: Could not find a dimmable device" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "=== Testing Invalid Dim Values ===" -ForegroundColor Cyan
    Write-Host ""

    # Define test cases
    $testCases = @(
        @{ Name = "Negative value"; Dim = -1; Expected = "REQUEST_INVALID or rejection" }
        @{ Name = "Zero"; Dim = 0; Expected = "Valid (min value) or error" }
        @{ Name = "Above maximum"; Dim = 101; Expected = "REQUEST_INVALID or rejection" }
        @{ Name = "Way above maximum"; Dim = 255; Expected = "REQUEST_INVALID or rejection" }
        @{ Name = "Large positive"; Dim = 1000; Expected = "REQUEST_INVALID or rejection" }
        @{ Name = "Decimal value"; Dim = 50.5; Expected = "Accept, truncate, or error" }
        @{ Name = "Valid minimum"; Dim = 1; Expected = "OK (control test)" }
        @{ Name = "Valid middle"; Dim = 50; Expected = "OK (control test)" }
        @{ Name = "Valid maximum"; Dim = 100; Expected = "OK (control test)" }
    )

    $results = @()

    foreach ($testCase in $testCases) {
        Write-Host "Test: $($testCase.Name) (dim=$($testCase.Dim))" -ForegroundColor Yellow
        
        $transactionId = [guid]::NewGuid().ToString()
        
        # Build control request
        $controlRequest = @{
            transactionId = $transactionId
            type = "CONTROL"
            dst = "deako"
            src = "edge_case_test"
            data = @{
                target = $deviceUuid
                state = @{
                    power = $true
                    dim = $testCase.Dim
                }
            }
        } | ConvertTo-Json -Compress

        $sendTime = Get-Date
        $writer.WriteLine($controlRequest)
        $stream.Flush()
        
        # Wait for response (3 second timeout)
        $responseTimeout = [DateTime]::Now.AddSeconds(3)
        $gotResponse = $false
        $responseData = $null
        
        while ([DateTime]::Now -lt $responseTimeout -and -not $gotResponse) {
            if ($stream.DataAvailable) {
                $line = $reader.ReadLine()
                if ($line) {
                    try {
                        $response = $line | ConvertFrom-Json
                        
                        if ($response.type -eq "CONTROL" -and $response.transactionId -eq $transactionId) {
                            $gotResponse = $true
                            $responseTime = (Get-Date) - $sendTime
                            $responseData = $response
                            
                            $statusColor = if ($response.status -eq "ok") { "Green" } elseif ($response.status -eq "error") { "Red" } else { "Yellow" }
                            Write-Host "  Response: status=$($response.status)" -ForegroundColor $statusColor -NoNewline
                            
                            if ($response.status -eq "error" -and $response.data.code) {
                                Write-Host " code=$($response.data.code)" -ForegroundColor Red -NoNewline
                                if ($response.data.message) {
                                    Write-Host " message='$($response.data.message)'" -ForegroundColor Gray
                                } else {
                                    Write-Host ""
                                }
                            } else {
                                Write-Host ""
                            }
                            
                            Write-Host "  Response time: $([math]::Round($responseTime.TotalMilliseconds, 0))ms" -ForegroundColor Gray
                        }
                    } catch {
                        # Ignore non-JSON or other message types
                    }
                }
            }
            Start-Sleep -Milliseconds 10
        }
        
        if (-not $gotResponse) {
            Write-Host "  Response: NO RESPONSE (timeout)" -ForegroundColor Red
        }
        
        $results += @{
            TestName = $testCase.Name
            DimValue = $testCase.Dim
            Expected = $testCase.Expected
            GotResponse = $gotResponse
            Status = if ($responseData) { $responseData.status } else { "no response" }
            ErrorCode = if ($responseData) { $responseData.data.code } else { $null }
            ErrorMessage = if ($responseData) { $responseData.data.message } else { $null }
        }
        
        Write-Host ""
        Start-Sleep -Milliseconds 150  # Space out commands
    }

    Write-Host ""
    Write-Host "=== RESULTS SUMMARY ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Dim Value | Test Case            | Response    | Error Code      | Error Message"
    Write-Host "----------|----------------------|-------------|-----------------|-----------------------------"
    
    foreach ($result in $results) {
        $dimStr = $result.DimValue.ToString().PadRight(9)
        $testStr = $result.TestName.PadRight(20)
        $statusStr = $result.Status.PadRight(11)
        $codeStr = if ($result.ErrorCode) { $result.ErrorCode.PadRight(15) } else { "N/A".PadRight(15) }
        $msgStr = if ($result.ErrorMessage) { $result.ErrorMessage.Substring(0, [Math]::Min(28, $result.ErrorMessage.Length)) } else { "N/A" }
        
        Write-Host "$dimStr | $testStr | $statusStr | $codeStr | $msgStr"
    }
    
    Write-Host ""
    Write-Host "=== ANALYSIS ===" -ForegroundColor Cyan
    Write-Host ""
    
    # Analyze behavior patterns
    $invalidValues = $results | Where-Object { $_.DimValue -lt 0 -or $_.DimValue -gt 100 }
    $validValues = $results | Where-Object { $_.DimValue -ge 0 -and $_.DimValue -le 100 }
    
    $invalidErrors = ($invalidValues | Where-Object { $_.Status -eq "error" }).Count
    $invalidOk = ($invalidValues | Where-Object { $_.Status -eq "ok" }).Count
    $invalidNoResponse = ($invalidValues | Where-Object { $_.Status -eq "no response" }).Count
    
    $validOk = ($validValues | Where-Object { $_.Status -eq "ok" }).Count
    $validErrors = ($validValues | Where-Object { $_.Status -eq "error" }).Count
    
    Write-Host "Invalid values (< 0 or > 100):"
    Write-Host "  Total tested: $($invalidValues.Count)"
    Write-Host "  Returned error: $invalidErrors" -ForegroundColor $(if ($invalidErrors -gt 0) { "Green" } else { "Red" })
    Write-Host "  Returned OK: $invalidOk" -ForegroundColor $(if ($invalidOk -gt 0) { "Yellow" } else { "Gray" })
    Write-Host "  No response: $invalidNoResponse" -ForegroundColor $(if ($invalidNoResponse -gt 0) { "Red" } else { "Gray" })
    
    Write-Host ""
    Write-Host "Valid values (0-100):"
    Write-Host "  Total tested: $($validValues.Count)"
    Write-Host "  Returned OK: $validOk" -ForegroundColor $(if ($validOk -eq $validValues.Count) { "Green" } else { "Yellow" })
    Write-Host "  Returned error: $validErrors" -ForegroundColor $(if ($validErrors -gt 0) { "Red" } else { "Gray" })
    
    Write-Host ""
    
    # Check for REQUEST_INVALID error code
    $hasRequestInvalid = ($results | Where-Object { $_.ErrorCode -eq "REQUEST_INVALID" }).Count -gt 0
    
    if ($hasRequestInvalid) {
        Write-Host "✓ Hub uses REQUEST_INVALID error code for invalid values" -ForegroundColor Green
        Write-Host "  FR-071 validation: CONFIRMED" -ForegroundColor Green
    } else {
        Write-Host "✗ Hub does NOT use REQUEST_INVALID error code" -ForegroundColor Yellow
        Write-Host "  FR-071 validation: BEHAVIOR DIFFERS FROM SPEC" -ForegroundColor Yellow
    }
    
    Write-Host ""
    
    # Check dim=0 behavior
    $zeroResult = $results | Where-Object { $_.DimValue -eq 0 } | Select-Object -First 1
    if ($zeroResult) {
        Write-Host "Special case: dim=0"
        if ($zeroResult.Status -eq "ok") {
            Write-Host "  ✓ Accepted as valid (minimum brightness)" -ForegroundColor Green
        } elseif ($zeroResult.Status -eq "error") {
            Write-Host "  ✗ Rejected as invalid" -ForegroundColor Yellow
            Write-Host "  → Spec should clarify if 0 is valid or invalid" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    
    # Check decimal behavior
    $decimalResult = $results | Where-Object { $_.DimValue -eq 50.5 } | Select-Object -First 1
    if ($decimalResult) {
        Write-Host "Special case: decimal values"
        if ($decimalResult.Status -eq "ok") {
            Write-Host "  ✓ Accepted (likely truncated to 50)" -ForegroundColor Green
        } elseif ($decimalResult.Status -eq "error") {
            Write-Host "  ✗ Rejected as invalid" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-Host "=== SPEC IMPACT ===" -ForegroundColor Cyan
    Write-Host ""
    
    if ($invalidOk -gt 0) {
        Write-Host "⚠ WARNING: Hub accepted invalid dim values without error" -ForegroundColor Yellow
        Write-Host "  This could indicate:" -ForegroundColor Gray
        Write-Host "  • Hub clamps values to 0-100 range (silent correction)" -ForegroundColor Gray
        Write-Host "  • Hub accepts any integer and handles it internally" -ForegroundColor Gray
        Write-Host "  • Validation is looser than documented" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  Recommendation: Update FR-071 to match actual behavior" -ForegroundColor Yellow
    }
    
    if ($hasRequestInvalid) {
        Write-Host "✓ FR-071 is correct: Hub validates dim values" -ForegroundColor Green
        Write-Host "✓ REQUEST_INVALID error code is used" -ForegroundColor Green
    } else {
        Write-Host "⚠ FR-071 needs update: Hub behavior differs" -ForegroundColor Yellow
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
