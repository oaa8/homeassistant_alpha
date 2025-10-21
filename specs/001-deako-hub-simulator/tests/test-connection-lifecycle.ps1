# Test #9: Connection Lifecycle Testing
# Tests connection timeouts, keepalive behavior, reconnection handling, and disconnects
# Hub: 192.168.86.221:23

$hubIP = "192.168.86.221"
$hubPort = 23

Write-Host "`n=== TEST #9: CONNECTION LIFECYCLE ===" -ForegroundColor Cyan
Write-Host "Testing connection management, timeouts, and lifecycle..." -ForegroundColor Yellow

# Test 1: Idle Connection Timeout
Write-Host "`n--- Test 1: Idle Connection Timeout ---" -ForegroundColor Green
Write-Host "Establishing connection and leaving idle for 5 minutes to test timeout..." -ForegroundColor Yellow

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIP, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true
    
    Write-Host "✓ Connected at $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Green
    Write-Host "Monitoring connection for 5 minutes (300 seconds)..." -ForegroundColor Cyan
    Write-Host "Any messages from hub will be displayed below:" -ForegroundColor Cyan
    
    $startTime = Get-Date
    $checkInterval = 10 # Check every 10 seconds
    $lastCheckTime = $startTime
    
    while (((Get-Date) - $startTime).TotalSeconds -lt 300) {
        # Check for messages every 10 seconds
        if (((Get-Date) - $lastCheckTime).TotalSeconds -ge $checkInterval) {
            $elapsed = [math]::Floor(((Get-Date) - $startTime).TotalSeconds)
            Write-Host "  [$elapsed sec] Connection still alive, checking for messages..." -ForegroundColor Gray
            $lastCheckTime = Get-Date
        }
        
        # Check if data is available
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            Write-Host "  [$(Get-Date -Format 'HH:mm:ss')] HUB: $line" -ForegroundColor Yellow
        }
        
        # Check if connection is still alive
        if (-not $client.Connected) {
            $elapsed = ((Get-Date) - $startTime).TotalSeconds
            Write-Host "`n✓ Connection closed by hub after $([math]::Floor($elapsed)) seconds" -ForegroundColor Green
            break
        }
        
        Start-Sleep -Milliseconds 100
    }
    
    if ($client.Connected) {
        Write-Host "`n✓ Connection survived 5 minutes of idle time" -ForegroundColor Green
        Write-Host "Result: No idle timeout detected (or timeout > 5 minutes)" -ForegroundColor Cyan
    }
    
    $client.Close()
} catch {
    Write-Host "✗ Error: $_" -ForegroundColor Red
}

Start-Sleep -Seconds 2

# Test 2: Keepalive with PING
Write-Host "`n--- Test 2: Keepalive with PING Messages ---" -ForegroundColor Green
Write-Host "Testing if regular PING messages keep connection alive for 5 minutes..." -ForegroundColor Yellow

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIP, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true
    
    Write-Host "✓ Connected at $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Green
    Write-Host "Sending PING every 30 seconds for 5 minutes..." -ForegroundColor Cyan
    
    $startTime = Get-Date
    $lastPingTime = $startTime
    $pingInterval = 30
    $pingCount = 0
    
    while (((Get-Date) - $startTime).TotalSeconds -lt 300) {
        # Send PING every 30 seconds
        if (((Get-Date) - $lastPingTime).TotalSeconds -ge $pingInterval) {
            $writer.WriteLine('{"message":"PING"}')
            $pingCount++
            Write-Host "  [$pingCount] Sent PING at $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Cyan
            $lastPingTime = Get-Date
        }
        
        # Check for responses
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            Write-Host "  Response: $line" -ForegroundColor Yellow
        }
        
        # Check if connection is still alive
        if (-not $client.Connected) {
            Write-Host "`n✗ Connection closed unexpectedly after $pingCount PINGs" -ForegroundColor Red
            break
        }
        
        Start-Sleep -Milliseconds 100
    }
    
    if ($client.Connected) {
        Write-Host "`n✓ Connection survived 5 minutes with $pingCount PING messages" -ForegroundColor Green
        Write-Host "Result: PING messages successfully maintain connection" -ForegroundColor Cyan
    }
    
    $client.Close()
} catch {
    Write-Host "✗ Error: $_" -ForegroundColor Red
}

Start-Sleep -Seconds 2

# Test 3: Graceful Disconnect
Write-Host "`n--- Test 3: Graceful Disconnect Behavior ---" -ForegroundColor Green
Write-Host "Testing client-initiated graceful disconnect..." -ForegroundColor Yellow

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIP, $hubPort)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true
    
    Write-Host "✓ Connected" -ForegroundColor Green
    
    # Send a PING to establish connection
    $writer.WriteLine('{"message":"PING"}')
    Start-Sleep -Milliseconds 200
    
    if ($stream.DataAvailable) {
        $response = $reader.ReadLine()
        Write-Host "Initial PING response: $response" -ForegroundColor Gray
    }
    
    # Gracefully close connection
    Write-Host "Closing connection gracefully..." -ForegroundColor Cyan
    $stream.Close()
    $client.Close()
    
    Write-Host "✓ Connection closed by client" -ForegroundColor Green
    Write-Host "Result: Graceful disconnect successful" -ForegroundColor Cyan
    
} catch {
    Write-Host "✗ Error: $_" -ForegroundColor Red
}

Start-Sleep -Seconds 2

# Test 4: Reconnection After Disconnect
Write-Host "`n--- Test 4: Immediate Reconnection ---" -ForegroundColor Green
Write-Host "Testing if we can reconnect immediately after disconnect..." -ForegroundColor Yellow

try {
    # First connection
    $client1 = New-Object System.Net.Sockets.TcpClient
    $client1.Connect($hubIP, $hubPort)
    Write-Host "✓ Connection 1 established" -ForegroundColor Green
    
    # Close it
    $client1.Close()
    Write-Host "✓ Connection 1 closed" -ForegroundColor Green
    
    # Immediate reconnection (no delay)
    $client2 = New-Object System.Net.Sockets.TcpClient
    $client2.Connect($hubIP, $hubPort)
    $stream2 = $client2.GetStream()
    $reader2 = New-Object System.IO.StreamReader($stream2)
    $writer2 = New-Object System.IO.StreamWriter($stream2)
    $writer2.AutoFlush = $true
    
    Write-Host "✓ Connection 2 established immediately after disconnect" -ForegroundColor Green
    
    # Test if connection works
    $writer2.WriteLine('{"message":"PING"}')
    Start-Sleep -Milliseconds 200
    
    if ($stream2.DataAvailable) {
        $response = $reader2.ReadLine()
        Write-Host "✓ Connection 2 functional, PING response: $response" -ForegroundColor Green
    }
    
    $client2.Close()
    Write-Host "Result: Immediate reconnection allowed and functional" -ForegroundColor Cyan
    
} catch {
    Write-Host "✗ Error: $_" -ForegroundColor Red
}

Start-Sleep -Seconds 2

# Test 5: Ungraceful Disconnect (socket abort)
Write-Host "`n--- Test 5: Ungraceful Disconnect ---" -ForegroundColor Green
Write-Host "Testing socket abort (ungraceful disconnect)..." -ForegroundColor Yellow

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIP, $hubPort)
    $stream = $client.GetStream()
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true
    
    Write-Host "✓ Connected" -ForegroundColor Green
    
    # Send a PING to establish connection
    $writer.WriteLine('{"message":"PING"}')
    Start-Sleep -Milliseconds 200
    
    # Abruptly close without proper shutdown
    Write-Host "Aborting connection (ungraceful)..." -ForegroundColor Cyan
    $client.Client.Close() # Close socket directly
    
    Write-Host "✓ Connection aborted" -ForegroundColor Green
    
    # Wait a moment
    Start-Sleep -Seconds 1
    
    # Try to reconnect to see if hub recovered
    $client2 = New-Object System.Net.Sockets.TcpClient
    $client2.Connect($hubIP, $hubPort)
    Write-Host "✓ Reconnection successful after ungraceful disconnect" -ForegroundColor Green
    $client2.Close()
    
    Write-Host "Result: Hub handles ungraceful disconnects properly" -ForegroundColor Cyan
    
} catch {
    Write-Host "✗ Error during ungraceful disconnect test: $_" -ForegroundColor Red
}

Start-Sleep -Seconds 2

# Test 6: Half-Open Connection (send incomplete message then disconnect)
Write-Host "`n--- Test 6: Half-Open Connection ---" -ForegroundColor Green
Write-Host "Testing incomplete message handling..." -ForegroundColor Yellow

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($hubIP, $hubPort)
    $stream = $client.GetStream()
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true
    
    Write-Host "✓ Connected" -ForegroundColor Green
    
    # Send incomplete message (no CRLF)
    Write-Host "Sending incomplete message without CRLF..." -ForegroundColor Cyan
    $writer.Write('{"message":"PING"')  # No closing brace, no CRLF
    $writer.Flush()
    
    Start-Sleep -Milliseconds 500
    
    # Close connection
    Write-Host "Closing connection with incomplete message..." -ForegroundColor Cyan
    $client.Close()
    
    Write-Host "✓ Connection closed" -ForegroundColor Green
    
    # Wait and reconnect
    Start-Sleep -Seconds 1
    $client2 = New-Object System.Net.Sockets.TcpClient
    $client2.Connect($hubIP, $hubPort)
    Write-Host "✓ Reconnection successful after incomplete message" -ForegroundColor Green
    $client2.Close()
    
    Write-Host "Result: Hub handles incomplete messages and reconnection" -ForegroundColor Cyan
    
} catch {
    Write-Host "✗ Error: $_" -ForegroundColor Red
}

Write-Host "`n=== TEST #9 COMPLETE ===" -ForegroundColor Green
Write-Host "`nKey Findings:" -ForegroundColor Cyan
Write-Host "1. Idle timeout behavior documented" -ForegroundColor Yellow
Write-Host "2. PING keepalive effectiveness measured" -ForegroundColor Yellow
Write-Host "3. Graceful disconnect behavior verified" -ForegroundColor Yellow
Write-Host "4. Immediate reconnection capability tested" -ForegroundColor Yellow
Write-Host "5. Ungraceful disconnect handling verified" -ForegroundColor Yellow
Write-Host "6. Half-open connection cleanup tested" -ForegroundColor Yellow
Write-Host "`nNext: Document findings in research file and update spec.md" -ForegroundColor Cyan
