# Whitespace Message Behavior Test
# Date: October 18, 2025
# Purpose: Test if hub sends or accepts whitespace-only messages
# Gap: FR-026 mentions whitespace handling but research says none observed

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub Whitespace Message Test ===" -ForegroundColor Cyan
Write-Host ""

try {
    # ============================================
    # PART 1: Does hub send whitespace messages?
    # ============================================
    Write-Host "[PART 1] Long idle connection - checking for whitespace messages" -ForegroundColor Yellow
    Write-Host ""
    
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    Write-Host "Connected - waiting 30 seconds for any whitespace messages..." -ForegroundColor Gray
    
    $whitespaceCount = 0
    $messageCount = 0
    $startTime = [DateTime]::Now
    $timeout = $startTime.AddSeconds(30)
    
    while ([DateTime]::Now -lt $timeout) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            
            if ($line -eq $null) {
                continue
            }
            elseif ($line.Trim() -eq "") {
                $whitespaceCount++
                Write-Host "  [$(([DateTime]::Now - $startTime).TotalSeconds.ToString('F1'))s] Whitespace message received (length: $($line.Length))" -ForegroundColor Cyan
            }
            else {
                $messageCount++
                try {
                    $msg = $line | ConvertFrom-Json
                    Write-Host "  [$(([DateTime]::Now - $startTime).TotalSeconds.ToString('F1'))s] Message: $($msg.type)" -ForegroundColor Gray
                } catch {
                    Write-Host "  [$(([DateTime]::Now - $startTime).TotalSeconds.ToString('F1'))s] Non-JSON: $line" -ForegroundColor Yellow
                }
            }
        }
        Start-Sleep -Milliseconds 100
    }
    
    Write-Host ""
    Write-Host "Results after 30 seconds:" -ForegroundColor Cyan
    Write-Host "  Whitespace messages: $whitespaceCount" -ForegroundColor $(if ($whitespaceCount -gt 0) { "Green" } else { "Gray" })
    Write-Host "  Regular messages: $messageCount" -ForegroundColor Gray
    Write-Host ""
    
    # ============================================
    # PART 2: Does hub accept whitespace from client?
    # ============================================
    Write-Host "[PART 2] Sending whitespace to hub - checking response" -ForegroundColor Yellow
    Write-Host ""
    
    # Clear any pending messages
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }
    
    Write-Host "Sending empty line (just CRLF)..." -ForegroundColor Gray
    $writer.WriteLine("")
    $stream.Flush()
    Start-Sleep -Milliseconds 500
    
    $gotResponse1 = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "  Response: $line" -ForegroundColor Cyan
            $gotResponse1 = $true
        }
    }
    
    if (-not $gotResponse1) {
        Write-Host "  No response (whitespace ignored)" -ForegroundColor Gray
    }
    Write-Host ""
    
    Write-Host "Sending spaces-only line..." -ForegroundColor Gray
    $writer.WriteLine("    ")
    $stream.Flush()
    Start-Sleep -Milliseconds 500
    
    $gotResponse2 = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "  Response: $line" -ForegroundColor Cyan
            $gotResponse2 = $true
        }
    }
    
    if (-not $gotResponse2) {
        Write-Host "  No response (whitespace ignored)" -ForegroundColor Gray
    }
    Write-Host ""
    
    Write-Host "Sending tab-only line..." -ForegroundColor Gray
    $writer.WriteLine("`t`t")
    $stream.Flush()
    Start-Sleep -Milliseconds 500
    
    $gotResponse3 = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            Write-Host "  Response: $line" -ForegroundColor Cyan
            $gotResponse3 = $true
        }
    }
    
    if (-not $gotResponse3) {
        Write-Host "  No response (whitespace ignored)" -ForegroundColor Gray
    }
    Write-Host ""
    
    # ============================================
    # PART 3: Does valid command still work after whitespace?
    # ============================================
    Write-Host "[PART 3] Verify connection still works after whitespace" -ForegroundColor Yellow
    Write-Host ""
    
    # Clear buffer
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }
    
    Write-Host "Sending PING..." -ForegroundColor Gray
    $pingRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "PING"
        dst = "deako"
        src = "whitespace_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($pingRequest)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $gotPing = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.type -eq "PING") {
                Write-Host "  ✓ PING response received - connection still works" -ForegroundColor Green
                $gotPing = $true
            }
        }
    }
    
    if (-not $gotPing) {
        Write-Host "  ✗ No PING response - connection may be broken" -ForegroundColor Red
    }
    Write-Host ""
    
    # ============================================
    # PART 4: Rapid whitespace flood test
    # ============================================
    Write-Host "[PART 4] Sending 100 whitespace lines rapidly" -ForegroundColor Yellow
    Write-Host ""
    
    for ($i = 1; $i -le 100; $i++) {
        $writer.WriteLine("")
    }
    $stream.Flush()
    
    Write-Host "Sent 100 empty lines..." -ForegroundColor Gray
    Start-Sleep -Milliseconds 1000
    
    $responseCount = 0
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $responseCount++
        }
    }
    
    Write-Host "  Responses received: $responseCount" -ForegroundColor $(if ($responseCount -eq 0) { "Gray" } else { "Cyan" })
    Write-Host ""
    
    # Verify connection still alive
    Write-Host "Verifying connection with PING..." -ForegroundColor Gray
    $pingRequest2 = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "PING"
        dst = "deako"
        src = "whitespace_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($pingRequest2)
    $stream.Flush()
    Start-Sleep -Milliseconds 1000
    
    $stillAlive = $false
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.type -eq "PING") {
                $stillAlive = $true
            }
        }
    }
    
    if ($stillAlive) {
        Write-Host "  ✓ Connection survived whitespace flood" -ForegroundColor Green
    } else {
        Write-Host "  ✗ Connection appears broken after flood" -ForegroundColor Red
    }
    Write-Host ""
    
    # ============================================
    # SUMMARY
    # ============================================
    Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Hub sends whitespace during idle: $(if ($whitespaceCount -gt 0) { 'YES' } else { 'NO' })" -ForegroundColor $(if ($whitespaceCount -gt 0) { "Yellow" } else { "Gray" })
    Write-Host "Hub responds to client whitespace: $(if ($gotResponse1 -or $gotResponse2 -or $gotResponse3) { 'YES' } else { 'NO' })" -ForegroundColor $(if ($gotResponse1 -or $gotResponse2 -or $gotResponse3) { "Yellow" } else { "Gray" })
    Write-Host "Hub accepts whitespace gracefully: $(if ($gotPing) { 'YES' } else { 'NO' })" -ForegroundColor $(if ($gotPing) { "Green" } else { "Red" })
    Write-Host "Hub survives whitespace flood: $(if ($stillAlive) { 'YES' } else { 'NO' })" -ForegroundColor $(if ($stillAlive) { "Green" } else { "Red" })
    Write-Host ""
    
    if ($whitespaceCount -eq 0 -and -not ($gotResponse1 -or $gotResponse2 -or $gotResponse3)) {
        Write-Host "CONCLUSION: Hub neither sends nor responds to whitespace messages" -ForegroundColor Yellow
        Write-Host "FR-026 whitespace handling may be unnecessary for simulator" -ForegroundColor Gray
    } else {
        Write-Host "CONCLUSION: Hub has whitespace behavior that must be replicated" -ForegroundColor Yellow
        Write-Host "Simulator must implement FR-026 whitespace handling" -ForegroundColor Gray
    }
    
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
