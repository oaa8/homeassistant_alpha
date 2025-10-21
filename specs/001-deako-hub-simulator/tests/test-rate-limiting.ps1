# Test Deako Hub Rate Limiting Behavior
# Date: October 17, 2025
# Purpose: Determine actual rate limiting behavior vs documented 800ms minimum

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub Rate Limiting Test ===" -ForegroundColor Cyan
Write-Host "Hub: $hubIp`:$hubPort"
Write-Host "Test: Sending rapid-fire commands to measure rate limiting"
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

    # First, get a device to test with
    Write-Host "Step 1: Getting device list..." -ForegroundColor Yellow
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "rate_limit_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    Write-Host "Sent: DEVICE_LIST request"

    # Read responses until we get DEVICE_LIST response and at least one DEVICE_FOUND
    $deviceUuid = $null
    $deviceName = $null
    $responseCount = 0
    $timeout = [DateTime]::Now.AddSeconds(10)

    while ([DateTime]::Now -lt $timeout -and $deviceUuid -eq $null) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $responseCount++
                $response = $line | ConvertFrom-Json
                
                if ($response.type -eq "DEVICE_FOUND" -and $deviceUuid -eq $null) {
                    $deviceUuid = $response.data.uuid
                    $deviceName = $response.data.name
                    Write-Host "Found device: $deviceName ($deviceUuid)" -ForegroundColor Green
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
    Write-Host "Step 2: Testing rate limiting with rapid commands..." -ForegroundColor Yellow
    Write-Host "Target device: $deviceName" -ForegroundColor Cyan
    Write-Host ""

    # Test 1: Send commands with NO delay (as fast as possible)
    Write-Host "Test 1: Sending 10 commands with NO delay between them" -ForegroundColor Magenta
    $results = @()
    
    for ($i = 0; $i -lt 10; $i++) {
        $transactionId = [guid]::NewGuid().ToString()
        $sendTime = Get-Date
        
        $controlRequest = @{
            transactionId = $transactionId
            type = "CONTROL"
            dst = "deako"
            src = "rate_limit_test"
            data = @{
                target = $deviceUuid
                state = @{
                    power = ($i % 2 -eq 0)  # Alternate on/off
                }
            }
        } | ConvertTo-Json -Compress

        $writer.WriteLine($controlRequest)
        
        $results += @{
            CommandNumber = $i + 1
            TransactionId = $transactionId
            SentTime = $sendTime
            PowerState = ($i % 2 -eq 0)
        }
        
        Write-Host "  Sent command $($i + 1)/10 (power=$($i % 2 -eq 0)) at $($sendTime.ToString('HH:mm:ss.fff'))"
    }

    Write-Host ""
    Write-Host "Waiting for responses..." -ForegroundColor Yellow
    
    # Collect responses for 5 seconds
    $responseTimeout = [DateTime]::Now.AddSeconds(5)
    $responses = @()
    
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
                        
                        $statusColor = if ($response.status -eq "ok") { "Green" } else { "Red" }
                        $errorInfo = if ($response.data.code) { " (Error: $($response.data.code))" } else { "" }
                        Write-Host "  Received response: status=$($response.status)$errorInfo at $($receiveTime.ToString('HH:mm:ss.fff'))" -ForegroundColor $statusColor
                    }
                } catch {
                    # Ignore parsing errors
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }

    Write-Host ""
    Write-Host "=== RESULTS ===" -ForegroundColor Cyan
    Write-Host "Commands sent: $($results.Count)"
    Write-Host "Responses received: $($responses.Count)"
    Write-Host ""

    # Match responses to requests and calculate timing
    $successCount = 0
    $busyCount = 0
    $otherErrorCount = 0
    $timings = @()

    foreach ($result in $results) {
        $matchingResponse = $responses | Where-Object { $_.TransactionId -eq $result.TransactionId } | Select-Object -First 1
        
        if ($matchingResponse) {
            $responseTime = ($matchingResponse.ReceiveTime - $result.SentTime).TotalMilliseconds
            $timings += $responseTime
            
            Write-Host "Command $($result.CommandNumber): " -NoNewline
            
            if ($matchingResponse.Status -eq "ok") {
                Write-Host "SUCCESS" -ForegroundColor Green -NoNewline
                $successCount++
            } elseif ($matchingResponse.ErrorCode -eq "DEVICE_BUSY") {
                Write-Host "DEVICE_BUSY" -ForegroundColor Yellow -NoNewline
                $busyCount++
            } else {
                Write-Host "ERROR ($($matchingResponse.ErrorCode))" -ForegroundColor Red -NoNewline
                $otherErrorCount++
            }
            
            Write-Host " - Response time: $([math]::Round($responseTime, 0))ms"
        } else {
            Write-Host "Command $($result.CommandNumber): NO RESPONSE" -ForegroundColor Red
        }
    }

    Write-Host ""
    Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
    Write-Host "Successful commands: $successCount" -ForegroundColor Green
    Write-Host "DEVICE_BUSY errors: $busyCount" -ForegroundColor Yellow
    Write-Host "Other errors: $otherErrorCount" -ForegroundColor Red
    Write-Host "No response: $($results.Count - $responses.Count)" -ForegroundColor Red
    
    if ($timings.Count -gt 0) {
        $avgResponseTime = ($timings | Measure-Object -Average).Average
        $minResponseTime = ($timings | Measure-Object -Minimum).Minimum
        $maxResponseTime = ($timings | Measure-Object -Maximum).Maximum
        
        Write-Host ""
        Write-Host "Response time statistics:"
        Write-Host "  Average: $([math]::Round($avgResponseTime, 0))ms"
        Write-Host "  Minimum: $([math]::Round($minResponseTime, 0))ms"
        Write-Host "  Maximum: $([math]::Round($maxResponseTime, 0))ms"
    }

    # Calculate inter-command timing
    if ($results.Count -gt 1) {
        Write-Host ""
        Write-Host "Inter-command intervals (time between sending commands):"
        for ($i = 1; $i -lt $results.Count; $i++) {
            $interval = ($results[$i].SentTime - $results[$i-1].SentTime).TotalMilliseconds
            Write-Host "  Between command $i and $($i+1): $([math]::Round($interval, 0))ms"
        }
    }

    Write-Host ""
    Write-Host "=== CONCLUSIONS ===" -ForegroundColor Cyan
    
    if ($busyCount -eq 0) {
        Write-Host "✓ NO DEVICE_BUSY errors received despite rapid-fire commands" -ForegroundColor Green
        Write-Host "✓ Hub appears to handle messages much faster than documented 800ms limit" -ForegroundColor Green
        Write-Host "→ Recommendation: Simulator rate limiting should DEFAULT TO OFF" -ForegroundColor Yellow
    } else {
        Write-Host "✗ Received $busyCount DEVICE_BUSY errors" -ForegroundColor Yellow
        Write-Host "→ Rate limiting IS enforced by the hub" -ForegroundColor Yellow
        Write-Host "→ Recommendation: Simulator should replicate this behavior" -ForegroundColor Yellow
    }

    # Test 2: Send commands with 100ms delay
    Write-Host ""
    Write-Host ""
    Write-Host "Test 2: Sending 5 commands with 100ms delay between them" -ForegroundColor Magenta
    $results2 = @()
    
    for ($i = 0; $i -lt 5; $i++) {
        $transactionId = [guid]::NewGuid().ToString()
        $sendTime = Get-Date
        
        $controlRequest = @{
            transactionId = $transactionId
            type = "CONTROL"
            dst = "deako"
            src = "rate_limit_test"
            data = @{
                target = $deviceUuid
                state = @{
                    power = $true
                    dim = (20 * ($i + 1))  # 20, 40, 60, 80, 100
                }
            }
        } | ConvertTo-Json -Compress

        $writer.WriteLine($controlRequest)
        
        Write-Host "  Sent command $($i + 1)/5 (dim=$(20 * ($i + 1))) at $($sendTime.ToString('HH:mm:ss.fff'))"
        
        if ($i -lt 4) {
            Start-Sleep -Milliseconds 100
        }
    }

    Write-Host ""
    Write-Host "Waiting for responses..." -ForegroundColor Yellow
    
    # Collect responses for 3 seconds
    $responseTimeout = [DateTime]::Now.AddSeconds(3)
    $responses2 = @()
    
    while ([DateTime]::Now -lt $responseTimeout) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $receiveTime = Get-Date
                try {
                    $response = $line | ConvertFrom-Json
                    
                    if ($response.type -eq "CONTROL") {
                        $responses2 += $response
                        $statusColor = if ($response.status -eq "ok") { "Green" } else { "Red" }
                        $errorInfo = if ($response.data.code) { " (Error: $($response.data.code))" } else { "" }
                        Write-Host "  Received response: status=$($response.status)$errorInfo at $($receiveTime.ToString('HH:mm:ss.fff'))" -ForegroundColor $statusColor
                    }
                } catch {
                    # Ignore parsing errors
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }

    $busyCount2 = ($responses2 | Where-Object { $_.data.code -eq "DEVICE_BUSY" }).Count
    $successCount2 = ($responses2 | Where-Object { $_.status -eq "ok" }).Count
    
    Write-Host ""
    Write-Host "Test 2 Results: $successCount2 success, $busyCount2 DEVICE_BUSY"
    
    if ($busyCount2 -eq 0) {
        Write-Host "✓ 100ms intervals are acceptable to the hub" -ForegroundColor Green
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
