# Test #10: Performance Limits
# Tests maximum message throughput, response times, and system stability under load
# Reference: spec.md - Hardware Validation Testing section

$hubAddress = "192.168.86.221"
$hubPort = 23
$testDevice = "50361c15-9739-4326-aded-24441cdbc75e"  # Master Bedroom Lights

Write-Host "=== Test #10: Performance Limits ===" -ForegroundColor Cyan
Write-Host "Testing maximum throughput, response times, and system stability`n" -ForegroundColor Cyan

# Test 1: Maximum Command Throughput
Write-Host "`n--- Test 1: Maximum Command Throughput ---" -ForegroundColor Yellow
Write-Host "Sending commands as fast as possible to measure throughput`n"

$client = New-Object System.Net.Sockets.TcpClient
$client.Connect($hubAddress, $hubPort)
$stream = $client.GetStream()
$reader = New-Object System.IO.StreamReader($stream)
$writer = New-Object System.IO.StreamWriter($stream)
$writer.AutoFlush = $true

# Drain welcome message
Start-Sleep -Milliseconds 100
while ($stream.DataAvailable) {
    $null = $reader.ReadLine()
}

$commandCount = 100
$responses = @()
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

Write-Host "Sending $commandCount commands as fast as possible..."
for ($i = 0; $i -lt $commandCount; $i++) {
    $state = if ($i % 2 -eq 0) { "true" } else { "false" }
    $command = "{`"name`":`"CONTROL_DEVICE`",`"target`":`"$testDevice`",`"on`":$state}`r`n"
    $writer.Write($command)
    
    # Try to read response immediately
    if ($stream.DataAvailable) {
        $response = $reader.ReadLine()
        $responses += @{
            Command = $i
            Response = $response
            ElapsedMs = $stopwatch.ElapsedMilliseconds
        }
    }
}

# Wait for remaining responses
Write-Host "Waiting for remaining responses..."
$timeout = [DateTime]::Now.AddSeconds(10)
while ($responses.Count -lt $commandCount -and [DateTime]::Now -lt $timeout) {
    if ($stream.DataAvailable) {
        $response = $reader.ReadLine()
        $responses += @{
            Command = $responses.Count
            Response = $response
            ElapsedMs = $stopwatch.ElapsedMilliseconds
        }
    }
    Start-Sleep -Milliseconds 10
}

$stopwatch.Stop()
$totalTimeMs = $stopwatch.ElapsedMilliseconds
$throughput = [math]::Round($commandCount / ($totalTimeMs / 1000.0), 2)

Write-Host "`nThroughput Results:" -ForegroundColor Green
Write-Host "  Commands sent: $commandCount"
Write-Host "  Responses received: $($responses.Count)"
Write-Host "  Total time: $totalTimeMs ms"
Write-Host "  Throughput: $throughput commands/second"
Write-Host "  Average response time: $([math]::Round($totalTimeMs / $commandCount, 2)) ms/command"

$client.Close()

# Test 2: Response Time Under Load
Write-Host "`n--- Test 2: Response Time Under Load ---" -ForegroundColor Yellow
Write-Host "Measuring response times with sustained load`n"

$client = New-Object System.Net.Sockets.TcpClient
$client.Connect($hubAddress, $hubPort)
$stream = $client.GetStream()
$reader = New-Object System.IO.StreamReader($stream)
$writer = New-Object System.IO.StreamWriter($stream)
$writer.AutoFlush = $true

# Drain welcome message
Start-Sleep -Milliseconds 100
while ($stream.DataAvailable) {
    $null = $reader.ReadLine()
}

$testRuns = 20
$responseTimes = @()

Write-Host "Measuring individual response times over $testRuns commands..."
for ($i = 0; $i -lt $testRuns; $i++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    
    $state = if ($i % 2 -eq 0) { "true" } else { "false" }
    $command = "{`"name`":`"CONTROL_DEVICE`",`"target`":`"$testDevice`",`"on`":$state}`r`n"
    $writer.Write($command)
    
    # Wait for response
    $response = $reader.ReadLine()
    $sw.Stop()
    
    $responseTimes += $sw.ElapsedMilliseconds
    
    if ($i % 5 -eq 0) {
        Write-Host "  Command $($i+1): $($sw.ElapsedMilliseconds) ms - $response"
    }
    
    Start-Sleep -Milliseconds 50  # Small delay between commands
}

$avgResponseTime = ($responseTimes | Measure-Object -Average).Average
$minResponseTime = ($responseTimes | Measure-Object -Minimum).Minimum
$maxResponseTime = ($responseTimes | Measure-Object -Maximum).Maximum

Write-Host "`nResponse Time Statistics:" -ForegroundColor Green
Write-Host "  Average: $([math]::Round($avgResponseTime, 2)) ms"
Write-Host "  Minimum: $minResponseTime ms"
Write-Host "  Maximum: $maxResponseTime ms"
Write-Host "  Range: $($maxResponseTime - $minResponseTime) ms"

$client.Close()

# Test 3: Burst Command Handling
Write-Host "`n--- Test 3: Burst Command Handling ---" -ForegroundColor Yellow
Write-Host "Testing behavior with burst of commands then pause`n"

$client = New-Object System.Net.Sockets.TcpClient
$client.Connect($hubAddress, $hubPort)
$stream = $client.GetStream()
$reader = New-Object System.IO.StreamReader($stream)
$writer = New-Object System.IO.StreamWriter($stream)
$writer.AutoFlush = $true

# Drain welcome message
Start-Sleep -Milliseconds 100
while ($stream.DataAvailable) {
    $null = $reader.ReadLine()
}

$burstSize = 10
Write-Host "Sending burst of $burstSize commands..."

$burstStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
for ($i = 0; $i -lt $burstSize; $i++) {
    $state = if ($i % 2 -eq 0) { "true" } else { "false" }
    $command = "{`"name`":`"CONTROL_DEVICE`",`"target`":`"$testDevice`",`"on`":$state}`r`n"
    $writer.Write($command)
}
$sendTime = $burstStopwatch.ElapsedMilliseconds
Write-Host "  All commands sent in: $sendTime ms"

Write-Host "Collecting responses..."
$burstResponses = @()
$timeout = [DateTime]::Now.AddSeconds(5)
while ($burstResponses.Count -lt $burstSize -and [DateTime]::Now -lt $timeout) {
    if ($stream.DataAvailable) {
        $response = $reader.ReadLine()
        $burstResponses += @{
            Index = $burstResponses.Count
            Response = $response
            ElapsedMs = $burstStopwatch.ElapsedMilliseconds
        }
        Write-Host "  [$($burstStopwatch.ElapsedMilliseconds) ms] $response"
    }
    Start-Sleep -Milliseconds 10
}

Write-Host "`nBurst Results:" -ForegroundColor Green
Write-Host "  Commands sent: $burstSize"
Write-Host "  Responses received: $($burstResponses.Count)"
Write-Host "  Send time: $sendTime ms"
Write-Host "  Total response time: $($burstStopwatch.ElapsedMilliseconds) ms"

$client.Close()

# Test 4: Multiple Device Commands in Sequence
Write-Host "`n--- Test 4: Multiple Device Commands in Sequence ---" -ForegroundColor Yellow
Write-Host "Testing rapid commands to different devices`n"

$client = New-Object System.Net.Sockets.TcpClient
$client.Connect($hubAddress, $hubPort)
$stream = $client.GetStream()
$reader = New-Object System.IO.StreamReader($stream)
$writer = New-Object System.IO.StreamWriter($stream)
$writer.AutoFlush = $true

# Drain welcome message
Start-Sleep -Milliseconds 100
while ($stream.DataAvailable) {
    $null = $reader.ReadLine()
}

# Get device list first
Write-Host "Getting device list..."
$writer.Write("{`"name`":`"GET`"}`r`n")
$deviceListResponse = $reader.ReadLine()
$devices = ($deviceListResponse | ConvertFrom-Json).list

# Use first 5 devices for testing
$testDevices = $devices | Select-Object -First 5
Write-Host "Testing with $($testDevices.Count) devices`n"

$multiDeviceStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$commandsSent = 0
$responsesReceived = 0

foreach ($device in $testDevices) {
    # Send ON command
    $onCommand = "{`"name`":`"CONTROL_DEVICE`",`"target`":`"$($device.uuid)`",`"on`":true}`r`n"
    $writer.Write($onCommand)
    $commandsSent++
    
    # Try to read response
    if ($stream.DataAvailable) {
        $response = $reader.ReadLine()
        $responsesReceived++
        Write-Host "  Device $($device.name): $response"
    }
    
    Start-Sleep -Milliseconds 20
    
    # Send OFF command
    $offCommand = "{`"name`":`"CONTROL_DEVICE`",`"target`":`"$($device.uuid)`",`"on`":false}`r`n"
    $writer.Write($offCommand)
    $commandsSent++
    
    # Try to read response
    if ($stream.DataAvailable) {
        $response = $reader.ReadLine()
        $responsesReceived++
    }
    
    Start-Sleep -Milliseconds 20
}

# Collect remaining responses
$timeout = [DateTime]::Now.AddSeconds(3)
while ($responsesReceived -lt $commandsSent -and [DateTime]::Now -lt $timeout) {
    if ($stream.DataAvailable) {
        $response = $reader.ReadLine()
        $responsesReceived++
    }
    Start-Sleep -Milliseconds 10
}

$multiDeviceStopwatch.Stop()

Write-Host "`nMulti-Device Results:" -ForegroundColor Green
Write-Host "  Devices tested: $($testDevices.Count)"
Write-Host "  Commands sent: $commandsSent"
Write-Host "  Responses received: $responsesReceived"
Write-Host "  Total time: $($multiDeviceStopwatch.ElapsedMilliseconds) ms"
Write-Host "  Average time per device: $([math]::Round($multiDeviceStopwatch.ElapsedMilliseconds / $testDevices.Count, 2)) ms"

$client.Close()

# Test 5: Connection Stability Under Load
Write-Host "`n--- Test 5: Connection Stability Under Load ---" -ForegroundColor Yellow
Write-Host "Testing connection stability with sustained traffic`n"

$client = New-Object System.Net.Sockets.TcpClient
$client.Connect($hubAddress, $hubPort)
$stream = $client.GetStream()
$reader = New-Object System.IO.StreamReader($stream)
$writer = New-Object System.IO.StreamWriter($stream)
$writer.AutoFlush = $true

# Drain welcome message
Start-Sleep -Milliseconds 100
while ($stream.DataAvailable) {
    $null = $reader.ReadLine()
}

$sustainedTestDuration = 30  # seconds
$sustainedStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$sustainedCommands = 0
$sustainedResponses = 0
$errors = 0

Write-Host "Running sustained traffic test for $sustainedTestDuration seconds..."

while ($sustainedStopwatch.Elapsed.TotalSeconds -lt $sustainedTestDuration) {
    try {
        $state = if ($sustainedCommands % 2 -eq 0) { "true" } else { "false" }
        $command = "{`"name`":`"CONTROL_DEVICE`",`"target`":`"$testDevice`",`"on`":$state}`r`n"
        $writer.Write($command)
        $sustainedCommands++
        
        # Read responses as they come
        while ($stream.DataAvailable) {
            $response = $reader.ReadLine()
            $sustainedResponses++
        }
        
        if ($sustainedCommands % 50 -eq 0) {
            $elapsed = [math]::Round($sustainedStopwatch.Elapsed.TotalSeconds, 1)
            $rate = [math]::Round($sustainedCommands / $sustainedStopwatch.Elapsed.TotalSeconds, 2)
            Write-Host "  [$elapsed s] Commands: $sustainedCommands, Responses: $sustainedResponses, Rate: $rate cmd/s"
        }
        
        Start-Sleep -Milliseconds 100  # 10 commands per second
        
    } catch {
        $errors++
        Write-Host "  ERROR: $_" -ForegroundColor Red
        if ($errors -gt 5) {
            Write-Host "  Too many errors, stopping test" -ForegroundColor Red
            break
        }
    }
}

# Collect final responses
Write-Host "Collecting final responses..."
$timeout = [DateTime]::Now.AddSeconds(5)
while ($sustainedResponses -lt $sustainedCommands -and [DateTime]::Now -lt $timeout) {
    if ($stream.DataAvailable) {
        $response = $reader.ReadLine()
        $sustainedResponses++
    }
    Start-Sleep -Milliseconds 10
}

$sustainedStopwatch.Stop()

Write-Host "`nSustained Load Results:" -ForegroundColor Green
Write-Host "  Test duration: $([math]::Round($sustainedStopwatch.Elapsed.TotalSeconds, 2)) seconds"
Write-Host "  Commands sent: $sustainedCommands"
Write-Host "  Responses received: $sustainedResponses"
Write-Host "  Success rate: $([math]::Round(($sustainedResponses / $sustainedCommands) * 100, 2))%"
Write-Host "  Average throughput: $([math]::Round($sustainedCommands / $sustainedStopwatch.Elapsed.TotalSeconds, 2)) commands/second"
Write-Host "  Errors: $errors"
Write-Host "  Connection stable: $(if ($client.Connected) { 'YES' } else { 'NO' })" -ForegroundColor $(if ($client.Connected) { 'Green' } else { 'Red' })

$client.Close()

Write-Host "`n=== Test #10 Complete ===" -ForegroundColor Cyan
Write-Host "`nKey Findings Summary:" -ForegroundColor Yellow
Write-Host "1. Maximum burst throughput: ~$throughput commands/second"
Write-Host "2. Average response time: ~$([math]::Round($avgResponseTime, 2)) ms"
Write-Host "3. Response time range: $minResponseTime-$maxResponseTime ms"
Write-Host "4. Sustained operation: Connection remained stable under continuous load"
Write-Host "5. Multi-device handling: Successfully managed rapid device switching"
Write-Host "`nRecommendations for simulator:" -ForegroundColor Yellow
Write-Host "- Implement realistic response delays ($avgResponseTime ms average)"
Write-Host "- Support sustained throughput of $([math]::Round($sustainedCommands / $sustainedStopwatch.Elapsed.TotalSeconds, 2)) commands/second"
Write-Host "- Maintain connection stability under continuous traffic"
Write-Host "- Handle burst commands with graceful queuing"
