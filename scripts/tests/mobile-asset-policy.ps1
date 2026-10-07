function Test-MobileDevelopmentUrl {
    param([string]$Content, [switch]$IsIndexHtml)
    # A CSP allow-list permits local printer/backend testing; it does not set
    # the API URL. Ignore only that meta tag, never script/link URLs or JS.
    $payload = $Content
    if ($IsIndexHtml) {
        $payload = [regex]::Replace($payload, '<meta\b[^>]*http-equiv="Content-Security-Policy"[^>]*>', '', 'IgnoreCase')
    }
    return $payload -match 'http://127\.0\.0\.1|localhost:5174'
}
