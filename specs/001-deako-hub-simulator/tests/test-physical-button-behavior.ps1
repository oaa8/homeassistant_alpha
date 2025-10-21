# Physical Button Behavior Test
# Date: October 18, 2025
# Purpose: Test how hub responds to physical button presses on devices
# Gap: Need to understand EVENT broadcasting, timing, command interaction

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub Physical Button Behavior Test ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "⚠️  This test requires MANUAL INTERACTION" -ForegroundColor Yellow
Write-Host "You will be prompted to press physical buttons on switches" -ForegroundColor Yellow
Write-Host ""

$response = Read-Host "Ready to proceed? (y/n)"
if ($response -ne "y") {
    Write-Host "Test cancelled" -ForegroundColor Gray
    exit 0
}

Write-Host ""

try {
    # Connect
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIp, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    Write-Host "Connected to hub" -ForegroundColor Green
    Write-Host ""

    # Get device list
    Write-Host "[1] Getting device list..." -ForegroundColor Yellow
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "button_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    Start-Sleep -Milliseconds 3000
    
    $devices = @()
    while ($stream.DataAvailable) {
        $line = $reader.ReadLine()
        if ($line) {
            $msg = $line | ConvertFrom-Json
            if ($msg.type -eq "DEVICE_FOUND") {
                $devices += @{
                    Name = $msg.data.name
                    UUID = $msg.data.uuid
                    Capabilities = $msg.data.capabilities
                }
            }
        }
    }
    
    Write-Host "Found $($devices.Count) devices:" -ForegroundColor Green
    for ($i = 0; $i -lt $devices.Count; $i++) {
        Write-Host "  [$i] $($devices[$i].Name) ($($devices[$i].Capabilities))" -ForegroundColor Gray
    }
    Write-Host ""
    
    # Select device
    $deviceIndex = Read-Host "Select device number for testing"
    $testDevice = $devices[[int]$deviceIndex]
    
    Write-Host ""
    Write-Host "Testing with: $($testDevice.Name)" -ForegroundColor Cyan
    Write-Host "UUID: $($testDevice.UUID)" -ForegroundColor Gray
    Write-Host ""
    
    # ============================================
    # TEST 1: Basic button press detection
    # ============================================
    Write-Host "[TEST 1] Press the physical button NOW" -ForegroundColor Yellow
    Write-Host "Listening for EVENT messages for 10 seconds..." -ForegroundColor Gray
    Write-Host ""
    
    $startTime = [DateTime]::Now
    $timeout = $startTime.AddSeconds(10)
    $events = @()
    
    while ([DateTime]::Now -lt $timeout) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $msg = $line | ConvertFrom-Json
                
                if ($msg.type -eq "EVENT") {
                    $elapsed = ([DateTime]::Now - $startTime).TotalMilliseconds
                    $events += @{
                        Time = $elapsed
                        EventType = $msg.data.eventType
                        Target = $msg.data.target
                        State = $msg.data.state
                    }
                    
                    Write-Host "  [$(($elapsed / 1000).ToString('F3'))s] EVENT received:" -ForegroundColor Cyan
                    Write-Host "    Type: $($msg.data.eventType)" -ForegroundColor White
                    Write-Host "    Target: $($msg.data.target)" -ForegroundColor White
                    Write-Host "    State: $($msg.data.state | ConvertTo-Json -Compress)" -ForegroundColor White
                }
            }
        }
        Start-Sleep -Milliseconds 50
    }
    
    Write-Host ""
    Write-Host "Received $($events.Count) EVENT(s)" -ForegroundColor $(if ($events.Count -gt 0) { "Green" } else { "Yellow" })
    Write-Host ""
    
    if ($events.Count -eq 0) {
        Write-Host "⚠️  No events detected. Did you press the button?" -ForegroundColor Yellow
        Write-Host "   Button may not have been pressed, or hub may not broadcast events" -ForegroundColor Gray
    }
    
    # ============================================
    # TEST 2: Rapid button presses (debouncing)
    # ============================================
    Write-Host "[TEST 2] Press the button rapidly 5 times" -ForegroundColor Yellow
    Write-Host "Testing for debouncing behavior..." -ForegroundColor Gray
    Write-Host ""
    
    Read-Host "Press ENTER when ready, then press button 5 times quickly"
    
    $startTime2 = [DateTime]::Now
    $timeout2 = $startTime2.AddSeconds(10)
    $rapidEvents = @()
    
    while ([DateTime]::Now -lt $timeout2) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $msg = $line | ConvertFrom-Json
                
                if ($msg.type -eq "EVENT") {
                    $elapsed = ([DateTime]::Now - $startTime2).TotalMilliseconds
                    $rapidEvents += @{
                        Time = $elapsed
                    }
                    Write-Host "  [$(($elapsed / 1000).ToString('F3'))s] EVENT #$($rapidEvents.Count)" -ForegroundColor Cyan
                }
            }
        }
        Start-Sleep -Milliseconds 50
    }
    
    Write-Host ""
    Write-Host "Received $($rapidEvents.Count) EVENT(s) from 5 presses" -ForegroundColor Cyan
    
    if ($rapidEvents.Count -gt 1) {
        $intervals = @()
        for ($i = 1; $i -lt $rapidEvents.Count; $i++) {
            $interval = $rapidEvents[$i].Time - $rapidEvents[$i-1].Time
            $intervals += $interval
        }
        
        $avgInterval = ($intervals | Measure-Object -Average).Average
        $minInterval = ($intervals | Measure-Object -Minimum).Minimum
        
        Write-Host "  Average interval: $($avgInterval.ToString('F0'))ms" -ForegroundColor Gray
        Write-Host "  Minimum interval: $($minInterval.ToString('F0'))ms" -ForegroundColor Gray
        
        if ($minInterval -gt 100) {
            Write-Host "  Possible debouncing detected (min > 100ms)" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    
    # ============================================
    # TEST 3: Command vs Physical Button
    # ============================================
    Write-Host "[TEST 3] Command override test" -ForegroundColor Yellow
    Write-Host "Will send command, then you press button immediately" -ForegroundColor Gray
    Write-Host ""
    
    Read-Host "Press ENTER when ready"
    
    # Clear buffer
    while ($stream.DataAvailable) { $null = $reader.ReadLine() }
    
    Write-Host "Sending command to turn light ON..." -ForegroundColor Gray
    $controlRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "CONTROL"
        dst = "deako"
        src = "button_test"
        data = @{
            target = $testDevice.UUID
            state = @{
                power = $true
            }
        }
    } | ConvertTo-Json -Compress

    $startTime3 = [DateTime]::Now
    $writer.WriteLine($controlRequest)
    $stream.Flush()
    
    Write-Host "Command sent - NOW press the physical button!" -ForegroundColor Yellow
    Write-Host "Watching for 5 seconds..." -ForegroundColor Gray
    Write-Host ""
    
    $timeout3 = $startTime3.AddSeconds(5)
    $sequence = @()
    
    while ([DateTime]::Now -lt $timeout3) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $msg = $line | ConvertFrom-Json
                $elapsed = ([DateTime]::Now - $startTime3).TotalMilliseconds
                
                if ($msg.type -eq "CONTROL") {
                    $sequence += "[$(($elapsed).ToString('F0'))ms] CONTROL response (status: $($msg.status))"
                    Write-Host "  [$(($elapsed / 1000).ToString('F3'))s] CONTROL response" -ForegroundColor Green
                }
                elseif ($msg.type -eq "EVENT") {
                    $sequence += "[$(($elapsed).ToString('F0'))ms] EVENT ($($msg.data.state | ConvertTo-Json -Compress))"
                    Write-Host "  [$(($elapsed / 1000).ToString('F3'))s] EVENT" -ForegroundColor Cyan
                }
            }
        }
        Start-Sleep -Milliseconds 50
    }
    
    Write-Host ""
    Write-Host "Message sequence:" -ForegroundColor Cyan
    foreach ($item in $sequence) {
        Write-Host "  $item" -ForegroundColor Gray
    }
    Write-Host ""
    
    # ============================================
    # SUMMARY
    # ============================================
    Write-Host "=== TEST SUMMARY ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Test 1 (Button detection): $($events.Count) EVENT(s)" -ForegroundColor Gray
    Write-Host "Test 2 (Rapid presses): $($rapidEvents.Count) EVENT(s) from 5 presses" -ForegroundColor Gray
    Write-Host "Test 3 (Command vs Button): $($sequence.Count) message(s) in sequence" -ForegroundColor Gray
    Write-Host ""
    
    if ($events.Count -gt 0) {
        Write-Host "✓ Physical button presses generate EVENT messages" -ForegroundColor Green
    } else {
        Write-Host "? Unable to confirm EVENT generation (button may not have been pressed)" -ForegroundColor Yellow
    }
    
    if ($rapidEvents.Count -gt 0) {
        Write-Host "✓ Hub broadcasts EVENTs for each button press" -ForegroundColor Green
        if ($rapidEvents.Count -lt 5) {
            Write-Host "  Note: Received fewer events than presses (possible debouncing)" -ForegroundColor Yellow
        }
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

Write-Host ""
Write-Host "Note: This test requires manual interaction and may have incomplete results" -ForegroundColor Gray
Write-Host "if buttons weren't pressed at the right times." -ForegroundColor Gray
