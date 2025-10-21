# Test Deako Hub Multi-Connection Behavior
# Date: October 18, 2025
# Purpose: Determine if hub supports multiple simultaneous connections or single-connection-only
# Expected: User reports single-connection-only behavior

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub Multi-Connection Test ===" -ForegroundColor Cyan
Write-Host "Hub: $hubIp`:$hubPort"
Write-Host "Test: Attempting multiple simultaneous connections"
Write-Host ""

try {
    # First connection
    Write-Host "Opening Connection 1..." -ForegroundColor Yellow
    $client1 = New-Object System.Net.Sockets.TcpClient
    $client1.Connect($hubIp, $hubPort)
    $stream1 = $client1.GetStream()
    $reader1 = New-Object System.IO.StreamReader($stream1)
    $writer1 = New-Object System.IO.StreamWriter($stream1)
    $writer1.AutoFlush = $true
    
    Write-Host "✓ Connection 1 established successfully" -ForegroundColor Green
    Write-Host "  Local endpoint: $($client1.Client.LocalEndPoint)"
    Write-Host "  Remote endpoint: $($client1.Client.RemoteEndPoint)"
    Write-Host ""
    
    # Try to establish second connection
    Write-Host "Opening Connection 2 (while Connection 1 is active)..." -ForegroundColor Yellow
    $client2 = $null
    $connection2Success = $false
    $connection2Error = $null
    
    try {
        $client2 = New-Object System.Net.Sockets.TcpClient
        $connectionTask = $client2.ConnectAsync($hubIp, $hubPort)
        
        # Wait up to 5 seconds for connection
        $timeout = [DateTime]::Now.AddSeconds(5)
        while (-not $connectionTask.IsCompleted -and [DateTime]::Now -lt $timeout) {
            Start-Sleep -Milliseconds 100
        }
        
        if ($connectionTask.IsCompleted) {
            if ($connectionTask.IsFaulted) {
                $connection2Error = $connectionTask.Exception.InnerException.Message
                Write-Host "✗ Connection 2 FAILED: $connection2Error" -ForegroundColor Red
            } else {
                $connection2Success = $true
                Write-Host "✓ Connection 2 established successfully" -ForegroundColor Green
                Write-Host "  Local endpoint: $($client2.Client.LocalEndPoint)"
                Write-Host "  Remote endpoint: $($client2.Client.RemoteEndPoint)"
            }
        } else {
            $connection2Error = "Connection timeout after 5 seconds"
            Write-Host "✗ Connection 2 FAILED: $connection2Error" -ForegroundColor Red
        }
    } catch {
        $connection2Error = $_.Exception.Message
        Write-Host "✗ Connection 2 FAILED: $connection2Error" -ForegroundColor Red
    }
    
    Write-Host ""
    
    if ($connection2Success) {
        Write-Host "=== BOTH CONNECTIONS ACTIVE ===" -ForegroundColor Green
        Write-Host ""
        
        # Test if both connections work independently
        Write-Host "Testing if both connections can send/receive messages..." -ForegroundColor Yellow
        
        # Get device list on connection 1
        Write-Host "Connection 1: Requesting DEVICE_LIST..." -ForegroundColor Cyan
        $deviceListRequest1 = @{
            transactionId = [guid]::NewGuid().ToString()
            type = "DEVICE_LIST"
            dst = "deako"
            src = "multi_conn_test_1"
        } | ConvertTo-Json -Compress
        
        $writer1.WriteLine($deviceListRequest1)
        Start-Sleep -Milliseconds 500
        
        # Check for response on connection 1
        $gotResponse1 = $false
        if ($stream1.DataAvailable) {
            $line = $reader1.ReadLine()
            Write-Host "  Connection 1 received: $($line.Substring(0, [Math]::Min(80, $line.Length)))..." -ForegroundColor Green
            $gotResponse1 = $true
        } else {
            Write-Host "  Connection 1: No response" -ForegroundColor Red
        }
        
        Write-Host ""
        
        # Get device list on connection 2
        $stream2 = $client2.GetStream()
        $reader2 = New-Object System.IO.StreamReader($stream2)
        $writer2 = New-Object System.IO.StreamWriter($stream2)
        $writer2.AutoFlush = $true
        
        Write-Host "Connection 2: Requesting DEVICE_LIST..." -ForegroundColor Cyan
        $deviceListRequest2 = @{
            transactionId = [guid]::NewGuid().ToString()
            type = "DEVICE_LIST"
            dst = "deako"
            src = "multi_conn_test_2"
        } | ConvertTo-Json -Compress
        
        $writer2.WriteLine($deviceListRequest2)
        Start-Sleep -Milliseconds 500
        
        # Check for response on connection 2
        $gotResponse2 = $false
        if ($stream2.DataAvailable) {
            $line = $reader2.ReadLine()
            Write-Host "  Connection 2 received: $($line.Substring(0, [Math]::Min(80, $line.Length)))..." -ForegroundColor Green
            $gotResponse2 = $true
        } else {
            Write-Host "  Connection 2: No response" -ForegroundColor Red
        }
        
        Write-Host ""
        Write-Host "=== RESULTS: MULTI-CONNECTION SUPPORTED ===" -ForegroundColor Green
        Write-Host "✓ Hub accepts multiple simultaneous connections" -ForegroundColor Green
        Write-Host "  Connection 1: $(if ($gotResponse1) { "Functional" } else { "Not responding" })"
        Write-Host "  Connection 2: $(if ($gotResponse2) { "Functional" } else { "Not responding" })"
        
        Write-Host ""
        Write-Host "=== SPEC IMPACT ===" -ForegroundColor Yellow
        Write-Host "• Update FR-072: Change from single-connection to multi-connection support"
        Write-Host "• Update User Story 6: Remove [PENDING HARDWARE VALIDATION] marker"
        Write-Host "• Simulator MUST support multiple simultaneous telnet connections"
        Write-Host "• Each connection MUST have independent message streams"
        
        # Close connection 2
        if ($client2 -ne $null) {
            $client2.Close()
            Write-Host ""
            Write-Host "Connection 2 closed" -ForegroundColor Gray
        }
        
    } else {
        Write-Host "=== RESULTS: SINGLE-CONNECTION ONLY ===" -ForegroundColor Yellow
        Write-Host "✓ Hub enforces single-connection limit (expected behavior per user report)" -ForegroundColor Green
        Write-Host "✗ Second connection was rejected/failed" -ForegroundColor Yellow
        Write-Host "  Error: $connection2Error"
        Write-Host ""
        
        # Check if connection 1 is still alive
        Write-Host "Verifying Connection 1 still works..." -ForegroundColor Yellow
        $deviceListRequest = @{
            transactionId = [guid]::NewGuid().ToString()
            type = "DEVICE_LIST"
            dst = "deako"
            src = "multi_conn_test"
        } | ConvertTo-Json -Compress
        
        $writer1.WriteLine($deviceListRequest)
        Start-Sleep -Milliseconds 500
        
        if ($stream1.DataAvailable) {
            $line = $reader1.ReadLine()
            Write-Host "✓ Connection 1 still functional after Connection 2 attempt" -ForegroundColor Green
            Write-Host "  Received: $($line.Substring(0, [Math]::Min(80, $line.Length)))..."
        } else {
            Write-Host "✗ Connection 1 not responding" -ForegroundColor Red
        }
        
        Write-Host ""
        Write-Host "=== SPEC STATUS ===" -ForegroundColor Green
        Write-Host "✓ FR-072 is CORRECT: Single-connection limit is confirmed" -ForegroundColor Green
        Write-Host "✓ User Story 6 remains [PENDING HARDWARE VALIDATION] - now VALIDATED"
        Write-Host "✓ Simulator MUST enforce single-connection limit"
        Write-Host "✓ Simulator MUST reject additional connection attempts"
        Write-Host ""
        
        Write-Host "=== CONNECTION REJECTION MECHANISM ===" -ForegroundColor Cyan
        if ($connection2Error -match "forcibly closed|refused|reset") {
            Write-Host "Mechanism: TCP RST (forcible rejection)" -ForegroundColor Yellow
            Write-Host "• Hub immediately resets/refuses the connection"
            Write-Host "• Simulator should use socket.close() immediately after accept()"
        } elseif ($connection2Error -match "timeout") {
            Write-Host "Mechanism: Silent ignore (connection timeout)" -ForegroundColor Yellow
            Write-Host "• Hub doesn't respond to SYN packets while connection active"
            Write-Host "• Simulator should not accept() while connection exists"
        } else {
            Write-Host "Mechanism: Unknown - error was: $connection2Error" -ForegroundColor Yellow
            Write-Host "• Simulator should test both approaches"
        }
        
        Write-Host ""
        Write-Host "Testing connection recovery..." -ForegroundColor Yellow
        
        # Close connection 1
        Write-Host "Closing Connection 1..." -ForegroundColor Gray
        $client1.Close()
        Start-Sleep -Seconds 2
        
        # Try to open connection 2 again
        Write-Host "Attempting Connection 2 after Connection 1 closed..." -ForegroundColor Yellow
        $client2Retry = $null
        
        try {
            $client2Retry = New-Object System.Net.Sockets.TcpClient
            $client2Retry.Connect($hubIp, $hubPort)
            Write-Host "✓ Connection 2 successful after Connection 1 closed" -ForegroundColor Green
            Write-Host "✓ Hub properly releases connection slot" -ForegroundColor Green
            
            $client2Retry.Close()
        } catch {
            Write-Host "✗ Connection 2 still failed: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "⚠ Hub may have cooldown period or persistent lock" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-Host "=== TEST COMPLETE ===" -ForegroundColor Cyan

} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
} finally {
    # Clean up all connections
    if ($client1 -ne $null) {
        try { $client1.Close() } catch {}
    }
    if ($client2 -ne $null) {
        try { $client2.Close() } catch {}
    }
    if ($client2Retry -ne $null) {
        try { $client2Retry.Close() } catch {}
    }
    Write-Host ""
    Write-Host "All connections closed" -ForegroundColor Gray
}
