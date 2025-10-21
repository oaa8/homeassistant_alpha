# Test Deako Hub Rate Limiting Behavior - Version 2
# Date: October 18, 2025
# Purpose: Determine actual rate limiting behavior with improved methodology
# Improvements over v1:
#   - Tests multiple delay thresholds systematically
#   - Proper transaction ID matching for all responses
#   - Better sample sizes (20 commands per threshold)
#   - Network flush delays to reduce TCP buffering effects
#   - Calculates success rate vs delay curve

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub Rate Limiting Test v2 ===" -ForegroundColor Cyan
Write-Host "Hub: $hubIp`:$hubPort"
Write-Host "Test: Systematic delay threshold testing"
Write-Host ""

function Test-DelayThreshold {
    param(
        [System.IO.StreamWriter]$writer,
        [System.IO.StreamReader]$reader,
        [System.Net.Sockets.NetworkStream]$stream,
        [string]$deviceUuid,
        [string]$deviceName,
        [int]$delayMs,
        [int]$commandCount
    )

    Write-Host "Testing $commandCount commands with ${delayMs}ms delay..." -ForegroundColor Yellow
    
    $commands = @()
    
    # Send commands with specified delay
    for ($i = 0; $i -lt $commandCount; $i++) {
        $transactionId = [guid]::NewGuid().ToString()
        $sendTime = Get-Date
        
        $controlRequest = @{
            transactionId = $transactionId
            type = "CONTROL"
            dst = "deako"
            src = "rate_limit_test_v2"
            data = @{
                target = $deviceUuid
                state = @{
                    power = ($i % 2 -eq 0)  # Alternate on/off
                }
            }
        } | ConvertTo-Json -Compress

        $writer.WriteLine($controlRequest)
        $stream.Flush()  # Force TCP flush
        
        $commands += @{
            Index = $i
            TransactionId = $transactionId
            SentTime = $sendTime
            PowerState = ($i % 2 -eq 0)
            Response = $null
            ResponseTime = $null
        }
        
        # Wait for specified delay before next command (except after last)
        if ($i -lt $commandCount - 1) {
            Start-Sleep -Milliseconds $delayMs
        }
    }
    
    $sendDuration = (Get-Date) - $commands[0].SentTime
    Write-Host "  Sent $commandCount commands in $([math]::Round($sendDuration.TotalMilliseconds, 0))ms"
    
    # Collect responses for a reasonable timeout
    # Timeout = 3 seconds base + 100ms per command
    $timeoutSeconds = 3 + ($commandCount * 0.1)
    $responseTimeout = [DateTime]::Now.AddSeconds($timeoutSeconds)
    $responses = @()
    
    Write-Host "  Collecting responses (timeout: $([math]::Round($timeoutSeconds, 1))s)..." -ForegroundColor Gray
    
    while ([DateTime]::Now -lt $responseTimeout) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $receiveTime = Get-Date
                try {
                    $response = $line | ConvertFrom-Json
                    
                    # Only track CONTROL responses
                    if ($response.type -eq "CONTROL") {
                        $responses += @{
                            TransactionId = $response.transactionId
                            Status = $response.status
                            ReceiveTime = $receiveTime
                            ErrorCode = $response.data.code
                        }
                    }
                } catch {
                    # Ignore parsing errors for non-JSON or EVENT messages
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }
    
    # Match responses to commands
    $successCount = 0
    $busyCount = 0
    $otherErrorCount = 0
    $noResponseCount = 0
    $responseTimes = @()
    
    foreach ($cmd in $commands) {
        $matchingResponse = $responses | Where-Object { $_.TransactionId -eq $cmd.TransactionId } | Select-Object -First 1
        
        if ($matchingResponse) {
            $responseTime = ($matchingResponse.ReceiveTime - $cmd.SentTime).TotalMilliseconds
            $cmd.Response = $matchingResponse.Status
            $cmd.ResponseTime = $responseTime
            $responseTimes += $responseTime
            
            if ($matchingResponse.Status -eq "ok") {
                $successCount++
            } elseif ($matchingResponse.ErrorCode -eq "DEVICE_BUSY") {
                $busyCount++
            } else {
                $otherErrorCount++
            }
        } else {
            $noResponseCount++
        }
    }
    
    $successRate = [math]::Round(($successCount / $commandCount) * 100, 1)
    
    Write-Host "  Results: " -NoNewline
    Write-Host "$successCount success" -ForegroundColor Green -NoNewline
    Write-Host ", " -NoNewline
    Write-Host "$busyCount DEVICE_BUSY" -ForegroundColor Yellow -NoNewline
    Write-Host ", " -NoNewline
    Write-Host "$otherErrorCount errors" -ForegroundColor Red -NoNewline
    Write-Host ", " -NoNewline
    Write-Host "$noResponseCount no response" -ForegroundColor Red
    Write-Host "  Success rate: $successRate%" -ForegroundColor $(if ($successRate -ge 95) { "Green" } elseif ($successRate -ge 75) { "Yellow" } else { "Red" })
    
    if ($responseTimes.Count -gt 0) {
        $avgResponseTime = ($responseTimes | Measure-Object -Average).Average
        Write-Host "  Avg response time: $([math]::Round($avgResponseTime, 0))ms" -ForegroundColor Gray
    }
    
    Write-Host ""
    
    return @{
        DelayMs = $delayMs
        CommandCount = $commandCount
        SuccessCount = $successCount
        BusyCount = $busyCount
        OtherErrorCount = $otherErrorCount
        NoResponseCount = $noResponseCount
        SuccessRate = $successRate
        ResponseTimes = $responseTimes
        Commands = $commands
        Responses = $responses
    }
}

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
        src = "rate_limit_test_v2"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    
    # Read responses until we get at least one DEVICE_FOUND
    $deviceUuid = $null
    $deviceName = $null
    $timeout = [DateTime]::Now.AddSeconds(10)

    while ([DateTime]::Now -lt $timeout -and $deviceUuid -eq $null) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $response = $line | ConvertFrom-Json
                
                if ($response.type -eq "DEVICE_FOUND" -and $deviceUuid -eq $null) {
                    $deviceUuid = $response.data.uuid
                    $deviceName = $response.data.name
                    Write-Host "Using device: $deviceName ($deviceUuid)" -ForegroundColor Green
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }

    if ($deviceUuid -eq $null) {
        Write-Host "ERROR: Could not find a device to test with" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "=== Running Systematic Delay Tests ===" -ForegroundColor Cyan
    Write-Host ""

    # Test different delay thresholds
    $testResults = @()
    
    # Test 1: No delay (0ms) - baseline
    $testResults += Test-DelayThreshold -writer $writer -reader $reader -stream $stream `
        -deviceUuid $deviceUuid -deviceName $deviceName -delayMs 0 -commandCount 20
    
    Start-Sleep -Seconds 2  # Pause between test runs
    
    # Test 2: 50ms delay
    $testResults += Test-DelayThreshold -writer $writer -reader $reader -stream $stream `
        -deviceUuid $deviceUuid -deviceName $deviceName -delayMs 50 -commandCount 20
    
    Start-Sleep -Seconds 2
    
    # Test 3: 100ms delay
    $testResults += Test-DelayThreshold -writer $writer -reader $reader -stream $stream `
        -deviceUuid $deviceUuid -deviceName $deviceName -delayMs 100 -commandCount 20
    
    Start-Sleep -Seconds 2
    
    # Test 4: 150ms delay
    $testResults += Test-DelayThreshold -writer $writer -reader $reader -stream $stream `
        -deviceUuid $deviceUuid -deviceName $deviceName -delayMs 150 -commandCount 20
    
    Start-Sleep -Seconds 2
    
    # Test 5: 200ms delay
    $testResults += Test-DelayThreshold -writer $writer -reader $reader -stream $stream `
        -deviceUuid $deviceUuid -deviceName $deviceName -delayMs 200 -commandCount 20
    
    Start-Sleep -Seconds 2
    
    # Test 6: 500ms delay
    $testResults += Test-DelayThreshold -writer $writer -reader $reader -stream $stream `
        -deviceUuid $deviceUuid -deviceName $deviceName -delayMs 500 -commandCount 10
    
    Write-Host ""
    Write-Host "=== SUMMARY OF ALL TESTS ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Delay (ms) | Commands | Success | Busy | No Response | Success Rate"
    Write-Host "-----------|----------|---------|------|-------------|-------------"
    
    foreach ($result in $testResults) {
        $delayStr = $result.DelayMs.ToString().PadLeft(10)
        $cmdStr = $result.CommandCount.ToString().PadLeft(8)
        $successStr = $result.SuccessCount.ToString().PadLeft(7)
        $busyStr = $result.BusyCount.ToString().PadLeft(4)
        $noRespStr = $result.NoResponseCount.ToString().PadLeft(11)
        $rateStr = "$($result.SuccessRate)%".PadLeft(12)
        
        Write-Host "$delayStr | $cmdStr | $successStr | $busyStr | $noRespStr | $rateStr"
    }
    
    Write-Host ""
    Write-Host "=== KEY FINDINGS ===" -ForegroundColor Cyan
    Write-Host ""
    
    # Find threshold where success rate >= 95%
    $reliableThreshold = $testResults | Where-Object { $_.SuccessRate -ge 95 } | Select-Object -First 1
    
    if ($reliableThreshold) {
        Write-Host "✓ Reliable operation threshold: $($reliableThreshold.DelayMs)ms" -ForegroundColor Green
        Write-Host "  (95%+ success rate achieved)" -ForegroundColor Gray
    } else {
        $bestResult = $testResults | Sort-Object -Property SuccessRate -Descending | Select-Object -First 1
        Write-Host "⚠ No threshold achieved 95% reliability" -ForegroundColor Yellow
        Write-Host "  Best: $($bestResult.DelayMs)ms with $($bestResult.SuccessRate)% success" -ForegroundColor Gray
    }
    
    Write-Host ""
    
    # Check for DEVICE_BUSY errors
    $totalBusyErrors = ($testResults | Measure-Object -Property BusyCount -Sum).Sum
    
    if ($totalBusyErrors -eq 0) {
        Write-Host "✓ NO DEVICE_BUSY errors across all tests" -ForegroundColor Green
        Write-Host "  Hub does not use explicit rate limit error codes" -ForegroundColor Gray
    } else {
        Write-Host "⚠ $totalBusyErrors DEVICE_BUSY errors detected" -ForegroundColor Yellow
        Write-Host "  Hub enforces rate limiting with error codes" -ForegroundColor Gray
    }
    
    Write-Host ""
    
    # Analyze response patterns
    $rapidTest = $testResults | Where-Object { $_.DelayMs -eq 0 } | Select-Object -First 1
    $slowTest = $testResults | Sort-Object -Property DelayMs -Descending | Select-Object -First 1
    
    Write-Host "✓ Response pattern analysis:" -ForegroundColor Cyan
    Write-Host "  Rapid commands (0ms): $($rapidTest.SuccessRate)% success rate"
    Write-Host "  Slow commands ($($slowTest.DelayMs)ms): $($slowTest.SuccessRate)% success rate"
    Write-Host "  Improvement: +$([math]::Round($slowTest.SuccessRate - $rapidTest.SuccessRate, 1))% with spacing"
    
    Write-Host ""
    
    # Check which commands get responses
    Write-Host "✓ Command response patterns (0ms delay test):" -ForegroundColor Cyan
    $respondedIndices = $rapidTest.Commands | Where-Object { $_.Response -ne $null } | ForEach-Object { $_.Index }
    
    if ($respondedIndices.Count -gt 0) {
        Write-Host "  Commands that got responses: $($respondedIndices -join ', ')"
        
        $firstCommands = $respondedIndices | Where-Object { $_ -lt 3 }
        $lastCommands = $respondedIndices | Where-Object { $_ -ge ($rapidTest.CommandCount - 3) }
        
        if ($firstCommands.Count -gt 0 -and $lastCommands.Count -eq 0) {
            Write-Host "  Pattern: Hub responds to FIRST commands in burst" -ForegroundColor Yellow
        } elseif ($lastCommands.Count -gt 0 -and $firstCommands.Count -eq 0) {
            Write-Host "  Pattern: Hub responds to LAST commands in burst" -ForegroundColor Yellow
        } elseif ($respondedIndices.Count -eq 1) {
            Write-Host "  Pattern: Hub responds to only ONE command in burst" -ForegroundColor Yellow
        } else {
            Write-Host "  Pattern: Mixed/scattered responses" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  No responses received in rapid test" -ForegroundColor Red
    }
    
    Write-Host ""
    Write-Host "=== RECOMMENDATIONS ===" -ForegroundColor Cyan
    Write-Host ""
    
    if ($reliableThreshold) {
        Write-Host "For integration developers:" -ForegroundColor Green
        Write-Host "  • Space commands at least $($reliableThreshold.DelayMs)ms apart for reliable operation"
        Write-Host "  • Implement client-side rate limiting/queuing"
        Write-Host "  • Handle timeout scenarios (commands may not get responses)"
    } else {
        Write-Host "For integration developers:" -ForegroundColor Yellow
        Write-Host "  • Test with longer delays (>500ms) to find reliable threshold"
        Write-Host "  • Implement robust retry logic for failed commands"
        Write-Host "  • Monitor for timeout scenarios"
    }
    
    Write-Host ""
    Write-Host "For simulator implementation:" -ForegroundColor Green
    Write-Host "  • Default: No DEVICE_BUSY errors (replicate real behavior)"
    Write-Host "  • Process commands sequentially with realistic timing"
    Write-Host "  • Silently drop/ignore commands that arrive during processing"
    Write-Host "  • Optional: Configurable DEVICE_BUSY mode for testing edge cases"

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
