# Systematic DEVICE_POLL Investigation
# Date: October 18, 2025
# Purpose: Methodically test DEVICE_POLL per API docs to understand actual behavior
# Reference: https://github.com/DeakoLights/local-integrations/blob/master/API.md section 3.5

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== DEVICE_POLL Systematic Investigation ===" -ForegroundColor Cyan
Write-Host "Testing per API.md section 3.5" -ForegroundColor Gray
Write-Host ""

function Read-AllMessages {
    param($reader, $stream, $timeoutMs = 2000)
    
    $messages = @()
    $timeout = [DateTime]::Now.AddMilliseconds($timeoutMs)
    
    while ([DateTime]::Now -lt $timeout) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                try {
                    $msg = $line | ConvertFrom-Json
                    $messages += $msg
                } catch {
                    Write-Host "  [WARN] Non-JSON line: $line" -ForegroundColor Yellow
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }
    
    return $messages
}

try {
    # ============================================
    # STEP 1: Connect and Get Device List
    # ============================================
    Write-Host "[STEP 1] Connecting to hub..." -ForegroundColor Yellow
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    Write-Host "  ✓ Connected" -ForegroundColor Green
    Write-Host ""

    # ============================================
    # STEP 2: Get Devices
    # ============================================
    Write-Host "[STEP 2] Getting device list..." -ForegroundColor Yellow
    
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "poll_investigation"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    $stream.Flush()
    
    # Wait and collect all messages
    $messages = Read-AllMessages -reader $reader -stream $stream -timeoutMs 5000
    
    $devices = $messages | Where-Object { $_.type -eq "DEVICE_FOUND" }
    Write-Host "  ✓ Found $($devices.Count) devices" -ForegroundColor Green
    
    if ($devices.Count -eq 0) {
        Write-Host "  ✗ No devices found - cannot continue" -ForegroundColor Red
        exit 1
    }
    
    # Pick first device with dim capability
    $testDevice = $devices | Where-Object { $_.data.capabilities -match "dim" } | Select-Object -First 1
    
    if ($testDevice -eq $null) {
        $testDevice = $devices | Select-Object -First 1
    }
    
    Write-Host "  Device selected: $($testDevice.data.name)" -ForegroundColor Gray
    Write-Host "    UUID: $($testDevice.data.uuid)" -ForegroundColor Gray
    Write-Host "    Initial state: power=$($testDevice.data.state.power), dim=$($testDevice.data.state.dim)" -ForegroundColor Gray
    Write-Host ""
    
    # ============================================
    # STEP 3: Clear Message Buffer
    # ============================================
    Write-Host "[STEP 3] Clearing message buffer..." -ForegroundColor Yellow
    Start-Sleep -Milliseconds 500
    
    $cleared = 0
    while ($stream.DataAvailable) {
        $null = $reader.ReadLine()
        $cleared++
    }
    
    Write-Host "  ✓ Cleared $cleared pending messages" -ForegroundColor Green
    Write-Host ""
    
    # ============================================
    # STEP 4: Change Device State
    # ============================================
    Write-Host "[STEP 4] Changing device state to known value..." -ForegroundColor Yellow
    Write-Host "  Setting: power=true, dim=50" -ForegroundColor Gray
    
    $controlRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "CONTROL"
        dst = "deako"
        src = "poll_investigation"
        data = @{
            target = $testDevice.data.uuid
            state = @{
                power = $true
                dim = 50
            }
        }
    } | ConvertTo-Json -Compress

    $writer.WriteLine($controlRequest)
    $stream.Flush()
    
    # Wait for response
    $controlResponse = Read-AllMessages -reader $reader -stream $stream -timeoutMs 2000
    $controlOk = $controlResponse | Where-Object { $_.status -eq "ok" }
    
    if ($controlOk) {
        Write-Host "  ✓ State change confirmed" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ No confirmation received" -ForegroundColor Yellow
    }
    Write-Host ""
    
    # ============================================
    # STEP 5: Wait and Clear Buffer Again
    # ============================================
    Write-Host "[STEP 5] Waiting for state to settle..." -ForegroundColor Yellow
    Start-Sleep -Milliseconds 1000
    
    $cleared2 = 0
    while ($stream.DataAvailable) {
        $null = $reader.ReadLine()
        $cleared2++
    }
    Write-Host "  ✓ Cleared $cleared2 messages (EVENTs, etc.)" -ForegroundColor Green
    Write-Host ""
    
    # ============================================
    # STEP 6: Test DEVICE_POLL (Format 1)
    # ============================================
    Write-Host "[STEP 6] Testing DEVICE_POLL - Format 1 (target in data)" -ForegroundColor Yellow
    
    $tid1 = [guid]::NewGuid().ToString()
    $pollRequest1 = @{
        transactionId = $tid1
        type = "DEVICE_POLL"
        dst = "deako"
        src = "poll_investigation"
        data = @{
            target = $testDevice.data.uuid
        }
    } | ConvertTo-Json -Compress

    Write-Host "  Request: $pollRequest1" -ForegroundColor DarkGray
    $writer.WriteLine($pollRequest1)
    $stream.Flush()
    
    # Wait for response
    $pollResponses1 = Read-AllMessages -reader $reader -stream $stream -timeoutMs 3000
    
    Write-Host "  Received $($pollResponses1.Count) message(s)" -ForegroundColor Gray
    
    $matchingTxn = $pollResponses1 | Where-Object { $_.transactionId -eq $tid1 }
    $deviceFound = $pollResponses1 | Where-Object { $_.type -eq "DEVICE_FOUND" }
    
    if ($matchingTxn) {
        Write-Host "  ✓ Got response matching transactionId" -ForegroundColor Green
        Write-Host "    Type: $($matchingTxn.type)" -ForegroundColor Gray
        Write-Host "    Status: $($matchingTxn.status)" -ForegroundColor Gray
    } elseif ($deviceFound) {
        Write-Host "  ⚠ Got DEVICE_FOUND without matching transactionId" -ForegroundColor Yellow
        Write-Host "    Device: $($deviceFound.data.name)" -ForegroundColor Gray
        Write-Host "    UUID: $($deviceFound.data.uuid)" -ForegroundColor Gray
        Write-Host "    State: power=$($deviceFound.data.state.power), dim=$($deviceFound.data.state.dim)" -ForegroundColor Gray
    } else {
        Write-Host "  ✗ No response received" -ForegroundColor Red
        Write-Host ""
        
        # Try Format 2
        Write-Host "[STEP 7] Testing DEVICE_POLL - Format 2 (target at root)" -ForegroundColor Yellow
        
        Start-Sleep -Milliseconds 500
        while ($stream.DataAvailable) { $null = $reader.ReadLine() }
        
        $tid2 = [guid]::NewGuid().ToString()
        $pollRequest2 = @{
            transactionId = $tid2
            type = "DEVICE_POLL"
            dst = "deako"
            src = "poll_investigation"
            target = $testDevice.data.uuid
        } | ConvertTo-Json -Compress

        Write-Host "  Request: $pollRequest2" -ForegroundColor DarkGray
        $writer.WriteLine($pollRequest2)
        $stream.Flush()
        
        $pollResponses2 = Read-AllMessages -reader $reader -stream $stream -timeoutMs 3000
        
        Write-Host "  Received $($pollResponses2.Count) message(s)" -ForegroundColor Gray
        
        $matchingTxn2 = $pollResponses2 | Where-Object { $_.transactionId -eq $tid2 }
        $deviceFound2 = $pollResponses2 | Where-Object { $_.type -eq "DEVICE_FOUND" }
        
        if ($matchingTxn2) {
            Write-Host "  ✓ Got response matching transactionId" -ForegroundColor Green
            Write-Host "    Type: $($matchingTxn2.type)" -ForegroundColor Gray
            Write-Host "    Status: $($matchingTxn2.status)" -ForegroundColor Gray
        } elseif ($deviceFound2) {
            Write-Host "  ⚠ Got DEVICE_FOUND without matching transactionId" -ForegroundColor Yellow
            Write-Host "    Device: $($deviceFound2.data.name)" -ForegroundColor Gray
            Write-Host "    UUID: $($deviceFound2.data.uuid)" -ForegroundColor Gray
            Write-Host "    State: power=$($deviceFound2.data.state.power), dim=$($deviceFound2.data.state.dim)" -ForegroundColor Gray
        } else {
            Write-Host "  ✗ No response received" -ForegroundColor Red
        }
    }
    
    Write-Host ""
    Write-Host "=== ANALYSIS ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "DEVICE_POLL is documented in API.md section 3.5" -ForegroundColor Gray
    Write-Host "User confirms it worked in prior testing" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Possible explanations for no response:" -ForegroundColor Yellow
    Write-Host "  1. Hub firmware version doesn't support DEVICE_POLL" -ForegroundColor Gray
    Write-Host "  2. Message format incorrect (despite matching API docs)" -ForegroundColor Gray
    Write-Host "  3. Hub requires specific timing/sequence before DEVICE_POLL" -ForegroundColor Gray
    Write-Host "  4. Connection state issue (need different client src?)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  - Check hub firmware version" -ForegroundColor Gray
    Write-Host "  - Try DEVICE_POLL immediately after DEVICE_LIST" -ForegroundColor Gray
    Write-Host "  - Try with different client src names" -ForegroundColor Gray
    Write-Host "  - Consult user about firmware version and when they used DEVICE_POLL" -ForegroundColor Gray
    
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
