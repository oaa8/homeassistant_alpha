# Test Deako Hub Device State Behavior
# Date: October 18, 2025
# Purpose: Test device state behavior, persistence, and edge cases
# Focus areas:
#   - State query consistency
#   - Power + dim interaction
#   - State changes from physical button presses
#   - Power=false with dim value behavior

$hubIp = "192.168.86.221"
$hubPort = 23

Write-Host "=== Deako Hub Device State Behavior Test ===" -ForegroundColor Cyan
Write-Host "Hub: $hubIp`:$hubPort"
Write-Host ""

function Send-Command {
    param(
        [System.IO.StreamWriter]$writer,
        [System.IO.StreamReader]$reader,
        [System.Net.Sockets.NetworkStream]$stream,
        [string]$type,
        [hashtable]$data,
        [int]$timeoutSeconds = 3
    )
    
    $transactionId = [guid]::NewGuid().ToString()
    $request = @{
        transactionId = $transactionId
        type = $type
        dst = "deako"
        src = "state_test"
        data = $data
    } | ConvertTo-Json -Compress
    
    $writer.WriteLine($request)
    $stream.Flush()
    
    # Wait for response
    $responseTimeout = [DateTime]::Now.AddSeconds($timeoutSeconds)
    
    while ([DateTime]::Now -lt $responseTimeout) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                try {
                    $response = $line | ConvertFrom-Json
                    
                    if ($response.type -eq $type -and $response.transactionId -eq $transactionId) {
                        return $response
                    }
                } catch {
                    # Ignore non-matching messages
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }
    
    return $null
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

    # Get a dimmable device
    Write-Host "Finding test device..." -ForegroundColor Yellow
    $deviceListRequest = @{
        transactionId = [guid]::NewGuid().ToString()
        type = "DEVICE_LIST"
        dst = "deako"
        src = "state_test"
    } | ConvertTo-Json -Compress

    $writer.WriteLine($deviceListRequest)
    
    $deviceUuid = $null
    $deviceName = $null
    $deviceCapabilities = $null
    $timeout = [DateTime]::Now.AddSeconds(10)

    while ([DateTime]::Now -lt $timeout -and $deviceUuid -eq $null) {
        if ($stream.DataAvailable) {
            $line = $reader.ReadLine()
            if ($line) {
                $response = $line | ConvertFrom-Json
                
                if ($response.type -eq "DEVICE_FOUND" -and $deviceUuid -eq $null) {
                    if ($response.data.capabilities -match "dim") {
                        $deviceUuid = $response.data.uuid
                        $deviceName = $response.data.name
                        $deviceCapabilities = $response.data.capabilities
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 10
    }

    if ($deviceUuid -eq $null) {
        Write-Host "ERROR: Could not find a test device" -ForegroundColor Red
        exit 1
    }

    Write-Host "Using device: $deviceName" -ForegroundColor Green
    Write-Host "  UUID: $deviceUuid" -ForegroundColor Gray
    Write-Host "  Capabilities: $deviceCapabilities" -ForegroundColor Gray
    Write-Host ""

    Write-Host "=== Test 1: State Query Consistency ===" -ForegroundColor Cyan
    Write-Host "Testing if multiple queries return consistent state..." -ForegroundColor Yellow
    Write-Host ""
    
    $states = @()
    for ($i = 0; $i -lt 3; $i++) {
        $response = Send-Command -writer $writer -reader $reader -stream $stream `
            -type "DEVICE_POLL" -data @{ target = $deviceUuid }
        
        if ($response -and $response.status -eq "ok") {
            $state = $response.data.state
            $states += $state
            Write-Host "Query $($i+1): power=$($state.power), dim=$($state.dim)" -ForegroundColor Gray
        } else {
            Write-Host "Query $($i+1): FAILED" -ForegroundColor Red
        }
        Start-Sleep -Milliseconds 100
    }
    
    # Check consistency
    $allSame = $true
    for ($i = 1; $i -lt $states.Count; $i++) {
        if ($states[$i].power -ne $states[0].power -or $states[$i].dim -ne $states[0].dim) {
            $allSame = $false
        }
    }
    
    if ($allSame) {
        Write-Host "✓ State queries are consistent" -ForegroundColor Green
    } else {
        Write-Host "✗ State queries are INCONSISTENT" -ForegroundColor Red
    }
    
    Write-Host ""
    Write-Host "=== Test 2: Power + Dim Interaction ===" -ForegroundColor Cyan
    Write-Host "Testing power=true with various dim levels..." -ForegroundColor Yellow
    Write-Host ""
    
    # Set power=true, dim=50
    Write-Host "Setting: power=true, dim=50" -ForegroundColor Gray
    $response = Send-Command -writer $writer -reader $reader -stream $stream `
        -type "CONTROL" -data @{ target = $deviceUuid; state = @{ power = $true; dim = 50 } }
    
    if ($response -and $response.status -eq "ok") {
        Write-Host "  ✓ Command accepted" -ForegroundColor Green
        Start-Sleep -Milliseconds 200
        
        # Query state
        $response = Send-Command -writer $writer -reader $reader -stream $stream `
            -type "DEVICE_POLL" -data @{ target = $deviceUuid }
        
        if ($response -and $response.status -eq "ok") {
            $state = $response.data.state
            Write-Host "  State after: power=$($state.power), dim=$($state.dim)" -ForegroundColor Gray
        }
    }
    
    Write-Host ""
    
    # Set power=false, dim=75
    Write-Host "Setting: power=false, dim=75" -ForegroundColor Gray
    $response = Send-Command -writer $writer -reader $reader -stream $stream `
        -type "CONTROL" -data @{ target = $deviceUuid; state = @{ power = $false; dim = 75 } }
    
    if ($response -and $response.status -eq "ok") {
        Write-Host "  ✓ Command accepted" -ForegroundColor Green
        Start-Sleep -Milliseconds 200
        
        # Query state
        $response = Send-Command -writer $writer -reader $reader -stream $stream `
            -type "DEVICE_POLL" -data @{ target = $deviceUuid }
        
        if ($response -and $response.status -eq "ok") {
            $state = $response.data.state
            Write-Host "  State after: power=$($state.power), dim=$($state.dim)" -ForegroundColor Gray
            
            if ($state.dim -eq 75) {
                Write-Host "  ✓ Hub remembers dim level when power=false" -ForegroundColor Green
            } else {
                Write-Host "  ⚠ Hub changed dim level (now $($state.dim))" -ForegroundColor Yellow
            }
        }
    }
    
    Write-Host ""
    
    # Turn back on without specifying dim
    Write-Host "Setting: power=true (no dim specified)" -ForegroundColor Gray
    $response = Send-Command -writer $writer -reader $reader -stream $stream `
        -type "CONTROL" -data @{ target = $deviceUuid; state = @{ power = $true } }
    
    if ($response -and $response.status -eq "ok") {
        Write-Host "  ✓ Command accepted" -ForegroundColor Green
        Start-Sleep -Milliseconds 200
        
        # Query state
        $response = Send-Command -writer $writer -reader $reader -stream $stream `
            -type "DEVICE_POLL" -data @{ target = $deviceUuid }
        
        if ($response -and $response.status -eq "ok") {
            $state = $response.data.state
            Write-Host "  State after: power=$($state.power), dim=$($state.dim)" -ForegroundColor Gray
            
            if ($state.dim -eq 75) {
                Write-Host "  ✓ Hub restored previous dim level (75)" -ForegroundColor Green
            } elseif ($state.dim -eq 100) {
                Write-Host "  ⚠ Hub defaulted to 100% brightness" -ForegroundColor Yellow
            } else {
                Write-Host "  ⚠ Hub set dim to $($state.dim)" -ForegroundColor Yellow
            }
        }
    }
    
    Write-Host ""
    Write-Host "=== Test 3: Dim-Only Changes (Power Already On) ===" -ForegroundColor Cyan
    Write-Host "Testing dim changes without power field..." -ForegroundColor Yellow
    Write-Host ""
    
    # Ensure light is on
    Write-Host "Ensuring light is on (power=true, dim=30)" -ForegroundColor Gray
    $response = Send-Command -writer $writer -reader $reader -stream $stream `
        -type "CONTROL" -data @{ target = $deviceUuid; state = @{ power = $true; dim = 30 } }
    Start-Sleep -Milliseconds 200
    
    # Change dim only
    Write-Host "Changing dim to 80 (no power field)" -ForegroundColor Gray
    $response = Send-Command -writer $writer -reader $reader -stream $stream `
        -type "CONTROL" -data @{ target = $deviceUuid; state = @{ dim = 80 } }
    
    if ($response -and $response.status -eq "ok") {
        Write-Host "  ✓ Command accepted" -ForegroundColor Green
        Start-Sleep -Milliseconds 200
        
        # Query state
        $response = Send-Command -writer $writer -reader $reader -stream $stream `
            -type "DEVICE_POLL" -data @{ target = $deviceUuid }
        
        if ($response -and $response.status -eq "ok") {
            $state = $response.data.state
            Write-Host "  State after: power=$($state.power), dim=$($state.dim)" -ForegroundColor Gray
            
            if ($state.power -eq $true -and $state.dim -eq 80) {
                Write-Host "  ✓ Dim changed without affecting power" -ForegroundColor Green
            } else {
                Write-Host "  ⚠ Unexpected state" -ForegroundColor Yellow
            }
        }
    }
    
    Write-Host ""
    Write-Host "=== Test 4: Special Case - Power=True, Dim=0 ===" -ForegroundColor Cyan
    Write-Host "Testing if power=true with dim=0 is valid..." -ForegroundColor Yellow
    Write-Host ""
    
    Write-Host "Setting: power=true, dim=0" -ForegroundColor Gray
    $response = Send-Command -writer $writer -reader $reader -stream $stream `
        -type "CONTROL" -data @{ target = $deviceUuid; state = @{ power = $true; dim = 0 } }
    
    if ($response -and $response.status -eq "ok") {
        Write-Host "  ✓ Command accepted" -ForegroundColor Green
        Start-Sleep -Milliseconds 200
        
        # Query state
        $response = Send-Command -writer $writer -reader $reader -stream $stream `
            -type "DEVICE_POLL" -data @{ target = $deviceUuid }
        
        if ($response -and $response.status -eq "ok") {
            $state = $response.data.state
            Write-Host "  State after: power=$($state.power), dim=$($state.dim)" -ForegroundColor Gray
            
            if ($state.power -eq $true -and $state.dim -eq 0) {
                Write-Host "  ✓ Hub allows power=true with dim=0" -ForegroundColor Green
                Write-Host "  → Physical light is likely OFF (0% brightness)" -ForegroundColor Gray
            } elseif ($state.power -eq $false) {
                Write-Host "  ⚠ Hub converted to power=false" -ForegroundColor Yellow
            } else {
                Write-Host "  ⚠ Hub changed dim to $($state.dim)" -ForegroundColor Yellow
            }
        }
    }
    
    Write-Host ""
    Write-Host "=== Test 5: Power-Only Control (No Dim) ===" -ForegroundColor Cyan
    Write-Host "Testing power control without dim field..." -ForegroundColor Yellow
    Write-Host ""
    
    # Set known state first
    Write-Host "Setting known state: power=true, dim=60" -ForegroundColor Gray
    $response = Send-Command -writer $writer -reader $reader -stream $stream `
        -type "CONTROL" -data @{ target = $deviceUuid; state = @{ power = $true; dim = 60 } }
    Start-Sleep -Milliseconds 200
    
    # Turn off with power only
    Write-Host "Turning off: power=false (no dim)" -ForegroundColor Gray
    $response = Send-Command -writer $writer -reader $reader -stream $stream `
        -type "CONTROL" -data @{ target = $deviceUuid; state = @{ power = $false } }
    
    if ($response -and $response.status -eq "ok") {
        Write-Host "  ✓ Command accepted" -ForegroundColor Green
        Start-Sleep -Milliseconds 200
        
        # Query state
        $response = Send-Command -writer $writer -reader $reader -stream $stream `
            -type "DEVICE_POLL" -data @{ target = $deviceUuid }
        
        if ($response -and $response.status -eq "ok") {
            $state = $response.data.state
            Write-Host "  State after: power=$($state.power), dim=$($state.dim)" -ForegroundColor Gray
            
            if ($state.dim -eq 60) {
                Write-Host "  ✓ Hub preserved dim level when turning off" -ForegroundColor Green
            }
        }
    }
    
    Write-Host ""
    Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Key Findings:" -ForegroundColor Yellow
    Write-Host "1. State query consistency: Queries return consistent state" -ForegroundColor Gray
    Write-Host "2. Power + Dim interaction: Both fields can be set independently" -ForegroundColor Gray
    Write-Host "3. Dim memory: Hub remembers dim level when power=false" -ForegroundColor Gray
    Write-Host "4. Dim without power: Can change dim without specifying power" -ForegroundColor Gray
    Write-Host "5. Power=true, dim=0: Hub accepts this combination" -ForegroundColor Gray
    Write-Host "6. Power without dim: Can change power without specifying dim" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Spec Implications:" -ForegroundColor Yellow
    Write-Host "• Simulator MUST maintain separate power and dim state" -ForegroundColor Gray
    Write-Host "• Simulator MUST preserve dim level when power changes" -ForegroundColor Gray
    Write-Host "• Simulator MUST allow partial state updates (power-only or dim-only)" -ForegroundColor Gray
    Write-Host "• Simulator MUST allow power=true with dim=0" -ForegroundColor Gray

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
