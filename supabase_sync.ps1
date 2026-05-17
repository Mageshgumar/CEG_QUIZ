# 1. Load SUPABASE_URL and SUPABASE_KEY from .env
if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match "^(?<key>[^=]+)=(?<value>.+)$") {
            $ExecutionContext.SessionState.PSVariable.Set($Matches.key, $Matches.value)
        }
    }
}

$headers = @{
    "apikey" = $SUPABASE_KEY
    "Authorization" = "Bearer $SUPABASE_KEY"
    "Content-Type" = "application/json"
    "Prefer" = "return=minimal"
}

function Invoke-SupabaseRequest {
    param($Method, $Uri, $Body)
    try {
        $params = @{
            Method = $Method
            Uri = "$SUPABASE_URL$Uri"
            Headers = $headers
        }
        if ($Body) { $params.Body = $Body }
        $response = Invoke-WebRequest @params -ErrorAction Stop
        Write-Host "$Method $Uri : $($response.StatusCode)"
    } catch {
        Write-Host "$Method $Uri : $($_.Exception.Response.StatusCode.value__)"
        $body = [System.Text.Encoding]::UTF8.GetString($_.Exception.Response.GetResponseStream().ToArray())
        if ($body) { Write-Host "Response: $body" }
    }
}

# 2. GET /rest/v1/tests?select=id,name&limit=1
Invoke-SupabaseRequest -Method Get -Uri "/rest/v1/tests?select=id,name&limit=1"

# 3. POST insert one tiny test row
$testId = "test_" + [Guid]::NewGuid().ToString().Substring(0,8)
$testBody = @{ id = $testId; name = "Temporary Test" } | ConvertTo-Json
Invoke-SupabaseRequest -Method Post -Uri "/rest/v1/tests" -Body $testBody

# 4. POST insert one attempt row
$attemptBody = @{
    attempt_id = [Guid]::NewGuid().ToString()
    submitted_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    test_id = $testId
    test_name = "Temporary Test"
    student = "bot"
    score = 0
    total_questions = 0
} | ConvertTo-Json
Invoke-SupabaseRequest -Method Post -Uri "/rest/v1/attempts" -Body $attemptBody

# 5. POST upsert one parent row
$parentHeaders = $headers.Clone()
$parentHeaders["Prefer"] = "resolution=merge-duplicates"
$parentBody = @{
    parent_id = "@bot_parent"
    phone_number = "1234567890"
} | ConvertTo-Json
try {
    $response = Invoke-WebRequest -Method Post -Uri "$SUPABASE_URL/rest/v1/parents" -Headers $parentHeaders -Body $parentBody -ErrorAction Stop
    Write-Host "POST /rest/v1/parents (upsert) : $($response.StatusCode)"
} catch {
    Write-Host "POST /rest/v1/parents (upsert) : $($_.Exception.Response.StatusCode.value__)"
    $body = [System.Text.Encoding]::UTF8.GetString($_.Exception.Response.GetResponseStream().ToArray())
    if ($body) { Write-Host "Response: $body" }
}

# 6. DELETE the inserted test row
Invoke-SupabaseRequest -Method Delete -Uri "/rest/v1/tests?id=eq.$testId"
