# Test: DEVICE_LIST EVENT Ordering Validation
# Date: October 25, 2025
# Purpose: Determine if EVENTs ALWAYS arrive before DEVICE_LIST response or if it's coincidental
# Validates: FR-065 assumption about EVENT ordering

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== DEVICE_LIST EVENT Ordering Test ===" -ForegroundColor Cyan
Write-Host "Testing if EVENTs consistently arrive before DEVICE_LIST response" -ForegroundColor Gray
Write-Host ""

function Test-DeviceListOrdering {
    param(
        [int]$testNumber
    )
    
    Write-Host "[Test #$testNumber] Connecting..." -ForegroundColor Yellow
    
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect($hubIp, $hubPort)
        $stream = $client.GetStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $writer = New-Object System.IO.StreamWriter($stream)
        $writer.AutoFlush = $true
        
        # Send DEVICE_LIST request
        $request = @{
            transactionId = [guid]::NewGuid().ToString()
            type = "DEVICE_LIST"
            dst = "deako"
            src = "ordering_test_$testNumber"
        } | ConvertTo-Json -Compress
        
        Write-Host "  Sending DEVICE_LIST..." -ForegroundColor Gray
        $writer.WriteLine($request)
        $stream.Flush()
        
        # Collect messages for 5 seconds
        $messages = @()
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        $timeout = 5000 # 5 seconds
        
        while ($stopwatch.ElapsedMilliseconds -lt $timeout) {
            if ($stream.DataAvailable) {
                $line = $reader.ReadLine()
                if ($line) {
                    try {
                        $msg = $line | ConvertFrom-Json
                        $messages += [PSCustomObject]@{
                            Time = $stopwatch.ElapsedMilliseconds
                            Type = $msg.type
                            TransactionId = $msg.transactionId
                            Message = $msg
                        }
                    } catch {
                        Write-Host "  [WARN] Non-JSON: $line" -ForegroundColor Yellow
                    }
                }
            }
            Start-Sleep -Milliseconds 10
        }
        
        # Analyze ordering
        $deviceListResponse = $messages | Where-Object { $_.Type -eq "DEVICE_LIST" } | Select-Object -First 1
        $eventsBeforeResponse = @()
        $eventsAfterResponse = @()
        
        if ($deviceListResponse) {
            $responseTime = $deviceListResponse.Time
            $eventsBeforeResponse = $messages | Where-Object { 
                $_.Type -eq "EVENT" -and $_.Time -lt $responseTime 
            }
            $eventsAfterResponse = $messages | Where-Object { 
                $_.Type -eq "EVENT" -and $_.Time -gt $responseTime 
            }
        }
        
        # Report results
        Write-Host "  Results:" -ForegroundColor Green
        Write-Host "    Total messages: $($messages.Count)" -ForegroundColor Gray
        Write-Host "    EVENTs before DEVICE_LIST response: $($eventsBeforeResponse.Count)" -ForegroundColor $(if ($eventsBeforeResponse.Count -gt 0) { "Cyan" } else { "Gray" })
        Write-Host "    EVENTs after DEVICE_LIST response: $($eventsAfterResponse.Count)" -ForegroundColor Gray
        Write-Host "    DEVICE_FOUND messages: $(($messages | Where-Object { $_.Type -eq 'DEVICE_FOUND' }).Count)" -ForegroundColor Gray
        
        if ($deviceListResponse) {
            Write-Host "    DEVICE_LIST response time: $($responseTime)ms" -ForegroundColor Gray
        } else {
            Write-Host "    [ERROR] No DEVICE_LIST response received!" -ForegroundColor Red
        }
        
        $client.Close()
        
        return [PSCustomObject]@{
            TestNumber = $testNumber
            Success = ($deviceListResponse -ne $null)
            EventsBeforeCount = $eventsBeforeResponse.Count
            EventsAfterCount = $eventsAfterResponse.Count
            TotalMessages = $messages.Count
            ResponseTimeMs = if ($deviceListResponse) { $responseTime } else { $null }
        }
        
    } catch {
        Write-Host "  [ERROR] $($_.Exception.Message)" -ForegroundColor Red
        return [PSCustomObject]@{
            TestNumber = $testNumber
            Success = $false
            EventsBeforeCount = 0
            EventsAfterCount = 0
            TotalMessages = 0
            ResponseTimeMs = $null
        }
    }
    
    Write-Host ""
}

# Run multiple tests
$results = @()

Write-Host "Running 10 consecutive tests to determine consistency..." -ForegroundColor Cyan
Write-Host ""

for ($i = 1; $i -le 10; $i++) {
    $results += Test-DeviceListOrdering -testNumber $i
    
    # Wait between tests
    if ($i -lt 10) {
        Write-Host "Waiting 2 seconds before next test..." -ForegroundColor DarkGray
        Start-Sleep -Seconds 2
    }
}

# Summary
Write-Host ""
Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
Write-Host ""

$successfulTests = $results | Where-Object { $_.Success }
$testsWithEventsBefore = $results | Where-Object { $_.EventsBeforeCount -gt 0 }
$testsWithEventsAfter = $results | Where-Object { $_.EventsAfterCount -gt 0 }

Write-Host "Successful tests: $($successfulTests.Count) / $($results.Count)" -ForegroundColor $(if ($successfulTests.Count -eq $results.Count) { "Green" } else { "Yellow" })
Write-Host "Tests with EVENTs BEFORE response: $($testsWithEventsBefore.Count) / $($successfulTests.Count)" -ForegroundColor Cyan
Write-Host "Tests with EVENTs AFTER response: $($testsWithEventsAfter.Count) / $($successfulTests.Count)" -ForegroundColor Cyan
Write-Host ""

if ($successfulTests.Count -gt 0) {
    $avgEventsBefore = ($successfulTests | Measure-Object -Property EventsBeforeCount -Average).Average
    $avgEventsAfter = ($successfulTests | Measure-Object -Property EventsAfterCount -Average).Average
    
    Write-Host "Average EVENTs before response: $([Math]::Round($avgEventsBefore, 2))" -ForegroundColor Gray
    Write-Host "Average EVENTs after response: $([Math]::Round($avgEventsAfter, 2))" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=== ANALYSIS ===" -ForegroundColor Cyan
Write-Host ""

if ($testsWithEventsBefore.Count -eq $successfulTests.Count) {
    Write-Host "✓ EVENTs ALWAYS arrived before DEVICE_LIST response" -ForegroundColor Green
    Write-Host "  Conclusion: This is consistent behavior, likely buffered events" -ForegroundColor Green
    Write-Host "  FR-065 should state: 'Simulator MUST send buffered EVENTs before DEVICE_LIST response'" -ForegroundColor Green
} elseif ($testsWithEventsBefore.Count -eq 0) {
    Write-Host "✓ EVENTs NEVER arrived before DEVICE_LIST response" -ForegroundColor Yellow
    Write-Host "  Conclusion: Original observation was likely coincidental (lights being used)" -ForegroundColor Yellow
    Write-Host "  FR-065 should be REMOVED or rewritten as 'EVENTs MAY arrive asynchronously'" -ForegroundColor Yellow
} else {
    Write-Host "⚠ EVENTs SOMETIMES arrived before DEVICE_LIST response" -ForegroundColor Yellow
    Write-Host "  Frequency: $($testsWithEventsBefore.Count) / $($successfulTests.Count) tests" -ForegroundColor Yellow
    Write-Host "  Conclusion: Behavior is non-deterministic or environment-dependent" -ForegroundColor Yellow
    Write-Host "  FR-065 should state: 'EVENTs MAY arrive before, during, or after DEVICE_LIST'" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Detailed Results:" -ForegroundColor Gray
$results | Format-Table -Property TestNumber, Success, EventsBeforeCount, EventsAfterCount, TotalMessages, ResponseTimeMs -AutoSize

Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Review the analysis above" -ForegroundColor Gray
Write-Host "  2. Update FR-065 based on findings" -ForegroundColor Gray
Write-Host "  3. Document the actual behavior in spec.md" -ForegroundColor Gray
