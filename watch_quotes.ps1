[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$OutputEncoding = [System.Text.Encoding]::UTF8

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.ServicePointManager]::SecurityProtocol

$ErrorActionPreference = "Stop"

# �� 字�名常�?(东财 push2 / 新浪通用) ��

$F_PRICE      = 'f2'   # �新价

$F_PCT_CHG    = 'f3'   # 涨跌�?%)

$F_CHG        = 'f4'   # 涨跌�?

$F_VOL        = 'f5'   # 成交�?�?

$F_AMT        = 'f6'   # 成交�?�?

$F_TURNOVER   = 'f8'   # 换手�?%)

$F_VOL_RATIO  = 'f10'  # 量比

$F_CODE       = 'f12'  # 代码

$F_MARKET     = 'f13'  # 市场 (0=�? 1=�?

$F_NAME       = 'f14'  # 名称

$F_HIGH       = 'f15'  # �高价

$F_LOW        = 'f16'  # �低价

$F_OPEN       = 'f17'  # 今开

$F_PREV_CLOSE = 'f18'  # 昨收

# ---------- 字�集合（按模式精简请求�?----------

$FULL_FIELDS    = 'f12,f13,f14,f2,f3,f4,f5,f6,f8,f10,f15,f16,f17,f18,f20,f21,f30'

$STEALTH_FIELDS = 'f2,f3,f4,f6,f8,f10,f12,f13,f14,f20,f21,f30'  # f6 留给指数计算三市成交额

# ---------- 基�工具 ----------

function Fetch-Json($url, $timeout = 15, $retries = 1) {

    $headers = @{

        'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

        'Referer' = 'https://quote.eastmoney.com/'

    }

    $lastErr = $null

    for ($i = 0; $i -lt $retries; $i++) {

        try {

            return Invoke-RestMethod -Uri $url -TimeoutSec $timeout -UseBasicParsing -Headers $headers

        } catch {

            $lastErr = $_

            if ($i -lt $retries - 1) {

                Start-Sleep -Milliseconds (200 * ($i + 1))

            }

        }

    }

    throw $lastErr

}

function Convert-SecidToSinaCode($secid) {

    $market = '0'; $code = $secid

    if ($secid -match '^(\d+)\.(.+)$') {

        $market = $matches[1]

        $code = $matches[2]

    }

    $prefix = switch ($market) {

        '0' { 'sz' }

        '1' { 'sh' }

        default { 'bj' }

    }

    $isShIndex = ($market -eq '1') -and ($code -match '^000(001|688)$')

    $isSzOrBjIndex = ($market -eq '0') -and ($code -match '^(399|899|930)\d{3}$')

    if ($isShIndex -or $isSzOrBjIndex) { $prefix = 's_' + $prefix }

    return "$prefix$code"

}

function Parse-SinaQuoteResponse($text) {

    $rows = @()

    foreach ($line in ($text -split "`r?`n")) {

        if ($line -notmatch 'var hq_str_([a-z_]+(\d+))="([^"]*)";') { continue }

        $sinaCode = $matches[1]

        $content = $matches[3]

        if ([string]::IsNullOrWhiteSpace($content)) { continue }

        $parts = $content -split ','

        $code = $matches[2]

        $marketNum = switch -Regex ($sinaCode) {

            '^s?_?sh' { '1' }

            '^s?_?sz' { '0' }

            '^s?_?bj' { 'other' }

            default { '1' }

        }

        $row = [ordered]@{

            f12 = $code

            f13 = $marketNum

            f14 = $parts[0]

            f8 = '-'

            f10 = '-'

        }

        if ($sinaCode -match '^s_') {

            if ($parts.Count -lt 4) { continue }

            $row.f2 = $parts[1]

            $row.f4 = $parts[2]

            $row.f3 = $parts[3]

            $row.f5 = if ($parts.Count -gt 4) { $parts[4] } else { '-' }

            $row.f6 = if ($parts.Count -gt 5) { $parts[5] } else { '-' }

            $row.f15 = '-'

            $row.f16 = '-'

            $row.f17 = '-'

            $row.f18 = '-'

            try {

                $p = [double]$parts[1]

                $c = [double]$parts[2]

                $row.f18 = [math]::Round($p - $c, 4)

            } catch {}

        } else {

            if ($parts.Count -lt 6) { continue }

            $row.f2 = $parts[3]

            $row.f18 = $parts[2]

            $row.f17 = $parts[1]

            $row.f15 = $parts[4]

            $row.f16 = $parts[5]

            $row.f5 = if ($parts.Count -gt 8 -and $parts[8] -match '^\d+$') { [math]::Floor([double]$parts[8] / 100) } else { '-' }

            $row.f6 = if ($parts.Count -gt 9) { $parts[9] } else { '-' }

            try {

                $p = [double]$parts[3]

                $pc = [double]$parts[2]

                $row.f4 = [math]::Round($p - $pc, 3)

                $row.f3 = if ($pc -ne 0) { [math]::Round(($p - $pc) / $pc * 100, 2) } else { 0 }

            } catch {

                $row.f4 = '-'

                $row.f3 = '-'

            }

        }

        $rows += [PSCustomObject]$row

    }

    return $rows

}

function Fetch-Quotes-Sina($secids) {

    if ($secids.Count -eq 0) { return @() }

    $sinaCodes = $secids | ForEach-Object { Convert-SecidToSinaCode $_ }

    $list = $sinaCodes -join ','

    $url = "https://hq.sinajs.cn/list=$list"

    $headers = @{ Referer = 'https://finance.sina.com.cn/' }

    $lastErr = $null

    for ($retry = 0; $retry -lt 2; $retry++) {

        try {

            $resp = Invoke-WebRequest -Uri $url -Headers $headers -UseBasicParsing -TimeoutSec 15

            $bytes = $resp.RawContentStream.ToArray()

            # 使用 gbk 解码（gb2312 的超集，更安兼�

            $text = [System.Text.Encoding]::GetEncoding('gbk').GetString($bytes)

            return Parse-SinaQuoteResponse $text

        } catch {

            $lastErr = $_

            if ($retry -lt 1) {

                Start-Sleep -Milliseconds (300 * ($retry + 1))

            }

        }

    }

    throw $lastErr

}

function Format-Number($v, $digits = 2, $divisor = 1) {

    # 注意：PowerShell �?0 -eq '' 会因类型强制而为 true，所以先轭�符串判断

    if ($v -eq $null) { return '-' }

    $sv = "$v"

    if ($sv -eq '' -or $sv -eq '-') { return '-' }

    try {

        $f = [double]$v / $divisor

        if ($digits -eq 0) {

            return "{0:N0}" -f $f

        }

        return "{0:N$digits}" -f $f

    } catch {

        return "$v"

    }

}

function Format-Yi($v) {

    try { return "{0:F2}" -f ([double]$v / 1e8) } catch { return '-' }

}


function Format-WanYi($v) {

    try { return "{0:F2}" -f ([double]$v / 1e12) } catch { return '-' }

}


function Format-LatestVol($v) {

    try { return "{0:N0}" -f ([math]::Abs([double]$v)) } catch { return '-' }

}


function Test-IsETF($row) {

    return "$($row.f14)".ToUpper().Contains('ETF')

}

function Measure-DisplayWidth($s) {

    $str = "$s"

    $w = 0

    foreach ($c in $str.ToCharArray()) {

        if ([int]$c -gt 127) { $w += 2 } else { $w += 1 }

    }

    return $w

}

function Pad-Right($s, $width) {

    $pad = $width - (Measure-DisplayWidth $s)

    if ($pad -lt 0) { $pad = 0 }

    return $s + (' ' * $pad)

}

function Pad-Left($s, $width) {

    $pad = $width - (Measure-DisplayWidth $s)

    if ($pad -lt 0) { $pad = 0 }

    return (' ' * $pad) + $s

}

function Truncate-Name($s, $maxWidth = 8) {

    $str = "$s"

    $w = 0

    $result = ""

    foreach ($c in $str.ToCharArray()) {

        $cw = if ([int]$c -gt 127) { 2 } else { 1 }

        if ($w + $cw -le $maxWidth) {

            $w += $cw

            $result += $c

        } else {

            break

        }

    }

    return $result

}

# ---------- 缓存：name -> secid ----------

$script:secidCachePath = Join-Path $PSScriptRoot '.secids_cache.json'

$script:secidCache = @{}

function Load-SecidCache {

    if (Test-Path $script:secidCachePath) {

        try {

            $json = Get-Content $script:secidCachePath -Encoding UTF8 | ConvertFrom-Json

            foreach ($p in $json.PSObject.Properties) {

                $script:secidCache[$p.Name] = $p.Value

            }

        } catch {

            # 缓存损坏时忽略，重新搜索

        }

    }

}

function Save-SecidCache {

    try {

        $script:secidCache | ConvertTo-Json | Set-Content $script:secidCachePath -Encoding UTF8

    } catch {

        # 保存失败不影响主流程

    }

}

# ---------- 缓存：secid -> half-year pct ----------

$script:hyCachePath = Join-Path $PSScriptRoot '.hy_pct_cache.json'

$script:hyCache = @{}              # secid -> @{ pct; date }

$script:hyUpdateJob = $null        # background update job

$script:hyStartInterval = 0        # 半年涨跌�始刷新的间隔（��?

$script:nextHyStartTime = $null    # 下��始半年涨跌刷新的时间

function Load-HyCache {

    if (Test-Path $script:hyCachePath) {

        try {

            $json = Get-Content $script:hyCachePath -Encoding UTF8 | ConvertFrom-Json

            foreach ($p in $json.PSObject.Properties) {

                $script:hyCache[$p.Name] = $p.Value

            }

        } catch {

            # 缓存损坏时忽略，重新获取

        }

    }

}

function Save-HyCache {

    try {

        $script:hyCache | ConvertTo-Json | Set-Content $script:hyCachePath -Encoding UTF8

    } catch {

        # 保存失败不影响主流程

    }

}

# ---------- 缓存：三市成交�� ----------

$script:marketTotalCachePath = Join-Path $PSScriptRoot '.market_total_cache.json'

$script:marketTotalCache = @{}    # secid -> date -> amount

function Load-MarketTotalCache {

    if (Test-Path $script:marketTotalCachePath) {

        try {

            $json = Get-Content $script:marketTotalCachePath -Encoding UTF8 | ConvertFrom-Json

            $script:marketTotalCache = @{}

            foreach ($p in $json.PSObject.Properties) {

                $script:marketTotalCache[$p.Name] = @{}

                foreach ($dp in $p.Value.PSObject.Properties) {

                    $script:marketTotalCache[$p.Name][$dp.Name] = [double]$dp.Value

                }

            }

        } catch {

            # 缓存损坏时忽略，重新获取

            $script:marketTotalCache = @{}

        }

    }

}

function Save-MarketTotalCache {

    try {

        $script:marketTotalCache | ConvertTo-Json | Set-Content $script:marketTotalCachePath -Encoding UTF8

    } catch {

        # 保存失败不影响主流程

    }

}

# ---------- 展示层缓存（�?secid 存储，避免刷新间隙空白） ----------

$script:stockQuoteCache = @{}   # secid -> row

$script:indexQuoteCache = @{}   # secid -> row

function Update-Caches($rows) {

    $indexSet = @{}

    foreach ($s in $script:indexSecids) { $indexSet[$s] = $true }

    foreach ($r in $rows) {

        $secid = "$($r.f13).$($r.f12)"

        if ($indexSet.ContainsKey($secid)) {

            $script:indexQuoteCache[$secid] = $r

        } else {

            $script:stockQuoteCache[$secid] = $r

        }

    }

}

function Get-CachedRows($cache, $secids) {

    # �?watchlist.json 业� secid 顺序返回，避�?Hashtable 打乱顺序

    $rows = @()

    foreach ($secid in $secids) {

        if ($cache.ContainsKey($secid)) {

            $rows += $cache[$secid]

        }

    }

    return $rows

}

function Apply-HalfYearPct($rows) {

    foreach ($r in $rows) {

        $secid = "$($r.f13).$($r.f12)"

        $cached = $script:hyCache[$secid]

        if ($cached -ne $null) {

            $r | Add-Member -MemberType NoteProperty -Name 'hyPct' -Value $cached.pct -Force

        } else {

            $r | Add-Member -MemberType NoteProperty -Name 'hyPct' -Value $null -Force

        }

    }

}

# ---------- 网络接口 ----------

function Search-SecIds($names) {

    $secids = @()

    $missing = @()

    foreach ($name in $names) {

        if ($script:secidCache.ContainsKey($name)) {

            $secids += $script:secidCache[$name]

        } else {

            $missing += $name

        }

    }

    if ($missing.Count -gt 0) {

        foreach ($name in $missing) {

            try {

                $encoded = [System.Web.HttpUtility]::UrlEncode($name)

                $url = "https://searchapi.eastmoney.com/api/suggest/get?input=$encoded&type=14&count=5"

                $data = Fetch-Json $url 10

                $items = $data.QuotationCodeTable.Data

                $item = $null

                foreach ($it in $items) {

                    if ($it.Name -eq $name) {

                        $item = $it

                        break

                    }

                }

                if ($item -eq $null -and $items.Count -gt 0) {

                    $item = $items[0]

                }

                if ($item -ne $null) {

                    $script:secidCache[$name] = $item.QuoteID

                    $secids += $item.QuoteID

                }

            } catch {

                continue

            }

        }

        Save-SecidCache

    }

    return $secids

}

function Fetch-AllQuotes($secids, $stealth) {

    if ($secids.Count -eq 0) { return @() }

    # 1) 主数捺�：东方财�?

    try {

        $fields = if ($stealth) { $STEALTH_FIELDS } else { $FULL_FIELDS }

        $secidStr = $secids -join ','

        $url = "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=$fields&secids=$secidStr"

        $data = Fetch-Json $url 15 2

        if ($data.data.diff.Count -gt 0) {

            return $data.data.diff

        }

    } catch {

        Write-Host "[warn] EastMoney quote fetch failed: $_" -ForegroundColor DarkGray

    }

    # 2) 兜底数据源：新浪财经

    try {

        $rows = Fetch-Quotes-Sina $secids

        if ($rows.Count -gt 0) {

            Write-Host "[info] switched to Sina fallback ($($rows.Count)/$($secids.Count) symbols)" -ForegroundColor DarkGray

            return $rows

        }

    } catch {

        Write-Host "[warn] Sina quote fetch failed: $_" -ForegroundColor DarkGray

    }

    throw "�有�情数捺�均不叔�（东贁新浼�"

}

function Parse-SinaDepthResponse($text, $sinaCode, $name = $null) {

    # 解析新浪盘口返回�?

    # var hq_str_sh688981="名称,今开,昨收,��?��?��?�?�?�?�?成交�?�?,成交�?

    #                       �?�?�?�?�?�?�?�?...,�?�?�?�?

    #                       �?�?�?�?�?�?�?�?...,�?�?�?�?日期,时间,状�?;

    if ($text -notmatch "var hq_str_$sinaCode=`"([^`"]*)`";") { return $null }

    $parts = $matches[1] -split ','

    if ($parts.Count -lt 33) { return $null }

    function _num($idx) {

        $v = $parts[$idx]

        if ($v -eq $null -or $v -eq '' -or $v -eq '-') { return $null }

        try { return [double]$v } catch { return $null }

    }

    function _vol($idx) {

        # 新浪返回的委托量是股数，转成手数（1手=100股）

        $v = _num $idx

        if ($v -eq $null) { return $null }

        return [int]($v / 100)

    }

    $price = _num 3

    $prev  = _num 2

    $change = if ($price -ne $null -and $prev -ne $null) { [math]::Round($price - $prev, 4) } else { $null }

    $pct = if ($change -ne $null -and $prev -ne $null -and $prev -ne 0) { [math]::Round($change / $prev * 100, 2) } else { $null }

    $volShares = _num 8

    $volume = if ($volShares -ne $null) { [math]::Floor($volShares / 100) } else { $null }

    return [PSCustomObject]@{

        name       = if ([string]::IsNullOrWhiteSpace($name)) { $parts[0] } else { $name }

        code       = ($sinaCode -replace '^[a-z_]+', '')

        price      = $price

        prev_close = $prev

        open       = _num 1

        high       = _num 4

        low        = _num 5

        volume     = $volume

        amount     = _num 9

        turnover   = $null

        change     = $change

        pct_chg    = $pct

        asks       = @(

            , @((_num 21), (_vol 20))   # 卖1

            , @((_num 23), (_vol 22))   # 卖2

            , @((_num 25), (_vol 24))   # 卖3

            , @((_num 27), (_vol 26))   # 卖4

            , @((_num 29), (_vol 28))   # 卖5

        )

        bids       = @(

            , @((_num 11), (_vol 10))   # 买1

            , @((_num 13), (_vol 12))   # 买2

            , @((_num 15), (_vol 14))   # 买3

            , @((_num 17), (_vol 16))   # 买4

            , @((_num 19), (_vol 18))   # 买5

        )

    }

}

function Fetch-DepthData($secid, $name = $null) {

    # 新浪提供完整五档 + 基�行情；东�?details 提供逐笔成交

    $sinaCode = Convert-SecidToSinaCode $secid

    $sinaUrl = "https://hq.sinajs.cn/list=$sinaCode"

    $sinaHeaders = @{

        'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

        'Referer'    = 'https://finance.sina.com.cn'

    }

    try {

        $sinaText = Invoke-RestMethod -Uri $sinaUrl -TimeoutSec 10 -UseBasicParsing -Headers $sinaHeaders

    } catch {

        Write-Host "[warn] sina depth fetch failed: $_" -ForegroundColor DarkGray

        return $null

    }

    $d = Parse-SinaDepthResponse $sinaText $sinaCode $name

    if ($d -eq $null) {

        Write-Host "[warn] sina depth parse failed" -ForegroundColor DarkGray

        return $null

    }

    # 东财逐笔成交（details/get �?PS 5.1 下可正常访问�?

    try {

        $dfUrl = "https://push2.eastmoney.com/api/qt/stock/details/get?secid=$secid&fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54"

        $dfHeaders = @{

            'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

            'Referer'    = 'https://quote.eastmoney.com/'

        }

        $df = Invoke-RestMethod -Uri $dfUrl -TimeoutSec 10 -UseBasicParsing -Headers $dfHeaders

        if ($df.data -and $df.data.details -and $df.data.details.Count -gt 0) {

            $last = $df.data.details[-1] -split ','

            if ($last.Count -ge 3) {

                $d | Add-Member -NotePropertyName 'last_trade_time'   -NotePropertyValue $last[0]       -Force

                $d | Add-Member -NotePropertyName 'last_trade_price'  -NotePropertyValue ([double]$last[1]) -Force

                $d | Add-Member -NotePropertyName 'last_trade_volume' -NotePropertyValue ([int]$last[2])    -Force

            }

        }

    } catch {

        Write-Host "[warn] details fetch failed: $_" -ForegroundColor DarkGray

    }

    return $d

}

function Get-HalfYearPct($secid) {

    try {

        $url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=$secid&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=0&end=20500101&lmt=200"

        $data = Fetch-Json $url 15

        $klines = $data.data.klines

        if ($klines -eq $null -or $klines.Count -eq 0) { return $null }

        $latest = $klines[-1].Split(',')

        try {

            $latestDate = [DateTime]::ParseExact($latest[0], 'yyyy-MM-dd', $null)

        } catch {

            Write-Host "[warn] kline date parse failed for $secid : $_" -ForegroundColor DarkGray

            return $null

        }

        $targetDate = $latestDate.AddMonths(-6)

        $targetPrice = $null

        foreach ($k in $klines) {

            $parts = $k.Split(',')

            $d = [DateTime]::ParseExact($parts[0], 'yyyy-MM-dd', $null)

            if ($d -ge $targetDate) {

                $targetPrice = [double]$parts[2]

                break

            }

        }

        if ($targetPrice -eq $null -or $targetPrice -eq 0) { return $null }

        $currentPrice = [double]$latest[2]

        return [math]::Round(($currentPrice - $targetPrice) / $targetPrice * 100, 2)

    } catch {

        return $null

    }

}

function Fetch-IndexKlineAmounts($secid, $days = 20) {

    # 获取指数日线成交额历史（f51=日期, f57=成交额）�?

    try {

        $today = Get-Date

        $beg = $today.AddDays(-($days + 5)).ToString('yyyyMMdd')

        $end = $today.AddDays(1).ToString('yyyyMMdd')

        $url = (

            "https://push2his.eastmoney.com/api/qt/stock/kline/get?" +

            "secid=$secid&fields1=f1,f2,f3,f4,f5,f6&" +

            "fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&" +

            "klt=101&fqt=0&beg=$beg&end=$end"

        )

        $data = Fetch-Json $url 15

        $klines = $data.data.klines

        if ($klines -eq $null -or $klines.Count -eq 0) { return @() }

        $result = @()

        foreach ($k in $klines) {

            $parts = $k.Split(',')

            if ($parts.Count -ge 7) {

                $result += ,@($parts[0], [double]$parts[6])

            }

        }

        return $result

    } catch {

        Write-Host "[warn] market total kline fetch failed for $secid : $_" -ForegroundColor DarkGray

        return @()

    }

}

function Get-TradingElapsedMinutes($timeStr) {

    # 计算从开盘到指定时刻的累计交易分钟数（A�?09:30-11:30, 13:00-15:00，共240分钟）�?

    $parts = $timeStr.Split(':')

    $h = [int]$parts[0]

    $m = [int]$parts[1]

    $minutes = $h * 60 + $m

    $amStart = 9 * 60 + 30   # 570

    $amEnd = 11 * 60 + 30    # 690

    $pmStart = 13 * 60       # 780

    $pmEnd = 15 * 60         # 900

    if ($minutes -le $amStart) { return 0 }

    if ($minutes -le $amEnd) { return $minutes - $amStart }

    if ($minutes -le $pmStart) { return $amEnd - $amStart }

    if ($minutes -le $pmEnd) { return ($amEnd - $amStart) + ($minutes - $pmStart) }

    return ($amEnd - $amStart) + ($pmEnd - $pmStart)  # 240

}

function Get-MarketTotalAmounts($indexRows) {

    # 计算沷�亸�市场今日成交总�及量比�?

    # 量比 = (今日�成交�?/ 已交易分钟数) / (过去5日日均成交� / 240)�?

    $marketSecids = [ordered]@{

        'sh' = '1.000001'

        'sz' = '0.399001'

        'bj' = '0.899050'

    }

    $secidList = $marketSecids.Values

    # 从已有指数�情中提取今日成交�?

    $todayAmounts = @{}

    foreach ($r in $indexRows) {

        $secid = "$($r.f13).$($r.f12)"

        if ($secid -in $secidList) {

            try {

                $todayAmounts[$secid] = [double]$r.f6

            } catch {

                $todayAmounts[$secid] = 0

            }

        }

    }

    if ($todayAmounts.Count -ne 3) { return $null }

    foreach ($v in $todayAmounts.Values) {

        if ($v -le 0) { return $null }

    }

    # 加载/刷新日线成交额缓�?

    Load-MarketTotalCache

    $todayStr = (Get-Date).ToString('yyyy-MM-dd')

    $needSave = $false

    foreach ($secid in $secidList) {

        if ($script:marketTotalCache[$secid] -eq $null) {

            $script:marketTotalCache[$secid] = @{}

        }

        $cache = $script:marketTotalCache[$secid]

        $beforeToday = $cache.Keys | Where-Object { $_ -lt $todayStr }

        if ($beforeToday.Count -lt 5) {

            $klines = Fetch-IndexKlineAmounts $secid 20

            foreach ($k in $klines) {

                $cache[$k[0]] = $k[1]

            }

            $needSave = $true

        }

    }

    if ($needSave) { Save-MarketTotalCache }

    # 计算过去5为�易日三市场合计日均成交�

    $totalByDay = @(0.0, 0.0, 0.0, 0.0, 0.0)

    $valid = $true

    foreach ($secid in $secidList) {

        $cache = $script:marketTotalCache[$secid]

        $dates = @($cache.Keys | Where-Object { $_ -lt $todayStr } | Sort-Object -Descending | Select-Object -First 5)

        if ($dates.Count -lt 5) { $valid = $false; break }

        for ($i = 0; $i -lt 5; $i++) {

            $totalByDay[$i] += $cache[$dates[$i]]

        }

    }

    if (-not $valid) { return $null }

    $avg = ($totalByDay | Measure-Object -Average).Average

    $todayTotal = 0.0

    foreach ($v in $todayAmounts.Values) { $todayTotal += $v }

    $currentTime = (Get-Date).ToString('HH:mm')

    $elapsed = Get-TradingElapsedMinutes $currentTime

    if ($elapsed -le 0) { return $null }

    $totalMinutes = 240

    $ratio = if ($avg -gt 0) { ($todayTotal / $elapsed) / ($avg / $totalMinutes) } else { $null }

    return @{

        total_yi = [math]::Round($todayTotal / 1e8, 2)

        ratio = if ($ratio -ne $null) { [math]::Round($ratio, 2) } else { $null }

    }

}

# ---------- 数据组� ----------

function Get-Quotes($stealth) {

    $scriptDir = $PSScriptRoot

    $wl = Get-Content -Path (Join-Path $scriptDir 'watchlist.json') -Encoding UTF8 | ConvertFrom-Json

    $stocks = $wl.stocks

    $indices = $wl.indices

    $stockSecids = Search-SecIds $stocks

    $indexSecids = Search-SecIds $indices

    if ($stockSecids.Count -eq 0 -and $indexSecids.Count -eq 0) {

        return $null, $null, "no stocks or indices"

    }

    # 合并�次�求，减少接口调用

    $allSecids = @($stockSecids) + @($indexSecids)

    try {

        $allRows = @(Fetch-AllQuotes $allSecids $stealth)

    } catch {

        return @(), @(), "行情获取失败: $_"

    }

    $indexSet = @{}

    foreach ($s in $indexSecids) { $indexSet[$s] = $true }

    $stockRows = @()

    $indexRows = @()

    foreach ($r in $allRows) {

        $secid = "$($r.f13).$($r.f12)"

        if ($indexSet.ContainsKey($secid)) {

            $indexRows += $r

        } else {

            $stockRows += $r

        }

    }

    return $stockRows, $indexRows, $null

}

# ---------- 分块增量刷新 ----------

$script:stockSecids = @()

$script:indexSecids = @()

$script:chunkSize = 0

$script:chunkIndex = 0

$script:chunkInterval = 0

$script:nextChunkTime = $null

function Initialize-Quotes($stealth) {

    $scriptDir = $PSScriptRoot

    $wl = Get-Content -Path (Join-Path $scriptDir 'watchlist.json') -Encoding UTF8 | ConvertFrom-Json

    $stocks = $wl.stocks

    $indices = $wl.indices

    $script:stockSecids = @(Search-SecIds $stocks)

    $script:indexSecids = @(Search-SecIds $indices)

    if ($script:stockSecids.Count -eq 0 -and $script:indexSecids.Count -eq 0) {

        return "no stocks or indices"

    }

    # 首�全量拉取，填满缓�?

    $allSecids = @($script:stockSecids) + @($script:indexSecids)

    try {

        $allRows = @(Fetch-AllQuotes $allSecids $stealth)

    } catch {

        return "行情获取失败: $_"

    }

    $script:stockQuoteCache = @{}

    $script:indexQuoteCache = @{}

    Update-Caches $allRows

    # 计算分块参数：希望每块间隔约 3 秒，但至�?1 块�不超过股票总数�?

    # 保证 totalChunks * chunkInterval == interval，即�丈�新周期内正好把所有股票更新一遍�?

    $desiredChunkInterval = 3

    $stockCount = $script:stockSecids.Count

    if ($stockCount -le 0) {

        $script:chunkSize = 0

        $script:chunkIndex = 0

        $script:chunkInterval = $interval

    } else {

        $chunkCount = [math]::Floor($interval / $desiredChunkInterval)

        if ($chunkCount -lt 1) { $chunkCount = 1 }

        if ($chunkCount -gt $stockCount) { $chunkCount = $stockCount }

        $script:chunkSize = [math]::Max(1, [math]::Ceiling($stockCount / $chunkCount))

        $script:chunkIndex = 0

        $totalChunks = [math]::Ceiling($stockCount / $script:chunkSize)

        $script:chunkInterval = $interval / $totalChunks

        if ($script:chunkInterval -lt 0.5) { $script:chunkInterval = 0.5 }

    }

    $script:nextChunkTime = (Get-Date).AddSeconds($script:chunkInterval)

    # 初�化半年涨跌刷新�划：间隔为自动刷新间隔的 4 倍�?

    # 若当天已有缓存则按�划等待；若缓存缺�?过期则立即在首�徎�吊�后台更新�?

    # 保证先展示缓存数捼�再尽忡�齐真实数�?

    $script:hyStartInterval = $interval * 4

    $today = (Get-Date).ToString('yyyy-MM-dd')

    $needsHyUpdate = $false

    foreach ($secid in $script:stockSecids) {

        $cached = $script:hyCache[$secid]

        if ($cached -eq $null -or $cached.date -ne $today) {

            $needsHyUpdate = $true

            break

        }

    }

    if ($needsHyUpdate) {

        $script:nextHyStartTime = (Get-Date)

    } else {

        $script:nextHyStartTime = (Get-Date).AddSeconds($script:hyStartInterval)

    }

    return $null

}

function Update-NextChunk($stealth) {

    $stockCount = $script:stockSecids.Count

    if ($stockCount -eq 0) {

        # 叜�指数时，按固�?interval 刷新指数

        if ($script:indexSecids.Count -gt 0) {

            try {

                $rows = @(Fetch-AllQuotes $script:indexSecids $stealth)

                Update-Caches $rows

            } catch {

                Write-Host "[warn] index refresh failed: $_" -ForegroundColor DarkGray

            }

        }

        $script:nextChunkTime = (Get-Date).AddSeconds($interval)

        return

    }

    $totalChunks = [math]::Ceiling($stockCount / $script:chunkSize)

    $start = $script:chunkIndex * $script:chunkSize

    $end = [math]::Min($start + $script:chunkSize, $stockCount)

    $chunkSecids = $script:stockSecids[$start..($end - 1)]

    # 每轮笸�块顺带刷新指�?

    $allSecids = @($chunkSecids)

    if ($script:chunkIndex -eq 0 -and $script:indexSecids.Count -gt 0) {

        $allSecids += $script:indexSecids

    }

    try {

        $rows = @(Fetch-AllQuotes $allSecids $stealth)

        Update-Caches $rows

    } catch {

        Write-Host "[warn] chunk $($script:chunkIndex + 1)/$totalChunks fetch failed: $_" -ForegroundColor DarkGray

    }

    $script:chunkIndex++

    if ($script:chunkIndex -ge $totalChunks) {

        $script:chunkIndex = 0

    }

    $script:nextChunkTime = (Get-Date).AddSeconds($script:chunkInterval)

}

function Update-HalfYearCache($rows) {

    $today = (Get-Date).ToString('yyyy-MM-dd')

    foreach ($r in $rows) {

        $secid = "$($r.f13).$($r.f12)"

        $cached = $script:hyCache[$secid]

        if ($cached -ne $null -and $cached.date -eq $today) { continue }

        $pct = Get-HalfYearPct $secid

        if ($pct -ne $null) {

            $script:hyCache[$secid] = @{ pct = $pct; date = $today }

        }

    }

    Save-HyCache

}

$script:hyUpdateJobScript = {

    param($secids)

    # 并发抓取半年涨跌：每�?secid ��?runspace，最�?8 丹�发�?

    # 使用 here-string �?worker 逻辑完整传给每个 runspace，避免作用域��?

    $workerSource = @'

param($s)

function Fetch-Json($url, $timeout = 15, $retries = 1) {

    $headers = @{

        'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

        'Referer' = 'https://quote.eastmoney.com/'

    }

    $lastErr = $null

    for ($i = 0; $i -lt $retries; $i++) {

        try {

            return Invoke-RestMethod -Uri $url -TimeoutSec $timeout -UseBasicParsing -Headers $headers

        } catch {

            $lastErr = $_

            if ($i -lt $retries - 1) {

                Start-Sleep -Milliseconds (200 * ($i + 1))

            }

        }

    }

    throw $lastErr

}

function Get-HalfYearPct($secid) {

    try {

        $url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=$secid&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=0&end=20500101&lmt=200"

        $data = Fetch-Json $url 15

        $klines = $data.data.klines

        if ($klines -eq $null -or $klines.Count -eq 0) { return $null }

        $latest = $klines[-1].Split(',')

        try {

            $latestDate = [DateTime]::ParseExact($latest[0], 'yyyy-MM-dd', $null)

        } catch {

            return $null

        }

        $targetDate = $latestDate.AddMonths(-6)

        $targetPrice = $null

        foreach ($k in $klines) {

            $parts = $k.Split(',')

            $d = [DateTime]::ParseExact($parts[0], 'yyyy-MM-dd', $null)

            if ($d -ge $targetDate) {

                $targetPrice = [double]$parts[2]

                break

            }

        }

        if ($targetPrice -eq $null -or $targetPrice -eq 0) { return $null }

        $currentPrice = [double]$latest[2]

        return [math]::Round(($currentPrice - $targetPrice) / $targetPrice * 100, 2)

    } catch {

        return $null

    }

}

$pct = Get-HalfYearPct $s

if ($pct -ne $null) { @{ secid = $s; pct = $pct } } else { $null }

'@

    $result = @{}

    if ($secids.Count -eq 0) { return $result }

    $maxConcurrency = [Math]::Min(8, $secids.Count)

    $pool = [runspacefactory]::CreateRunspacePool(1, $maxConcurrency)

    $pool.Open()

    $powershells = New-Object System.Collections.ArrayList

    $handles = New-Object System.Collections.ArrayList

    foreach ($secid in $secids) {

        $ps = [powershell]::Create()

        $ps.RunspacePool = $pool

        [void]$ps.AddScript($workerSource).AddArgument($secid)

        [void]$powershells.Add($ps)

        [void]$handles.Add($ps.BeginInvoke())

    }

    for ($i = 0; $i -lt $powershells.Count; $i++) {

        $r = $powershells[$i].EndInvoke($handles[$i])

        if ($r -ne $null -and $r -is [hashtable] -and $r.ContainsKey('pct')) {

            $result[$r.secid] = $r.pct

        }

        $powershells[$i].Dispose()

    }

    $pool.Close()

    $pool.Dispose()

    return $result

}

function Start-HalfYearUpdate($rows) {

    if (-not $fetchHy) { return }

    # 若已有后台任务在运�，则不重复启劼�避免世�尚未完成的抓�?

    if ($script:hyUpdateJob -ne $null -and $script:hyUpdateJob.State -eq 'Running') { return }

    $today = (Get-Date).ToString('yyyy-MM-dd')

    $secidsToUpdate = @()

    foreach ($r in $rows) {

        $secid = "$($r.f13).$($r.f12)"

        $cached = $script:hyCache[$secid]

        if ($cached -eq $null -or $cached.date -ne $today) {

            $secidsToUpdate += $secid

        }

    }

    if ($secidsToUpdate.Count -eq 0) { return }

    $script:hyUpdateJob = Start-Job -ScriptBlock $script:hyUpdateJobScript -ArgumentList (,$secidsToUpdate)

}

function Complete-HalfYearUpdate {

    if ($script:hyUpdateJob -eq $null) { return }

    if ($script:hyUpdateJob.State -in @('Completed', 'Failed')) {

        if ($script:hyUpdateJob.State -eq 'Completed') {

            $result = Receive-Job $script:hyUpdateJob

            $today = (Get-Date).ToString('yyyy-MM-dd')

            if ($result -ne $null) {

                foreach ($secid in $result.Keys) {

                    $script:hyCache[$secid] = @{ pct = $result[$secid]; date = $today }

                }

                Save-HyCache

            }

        }

        Remove-Job $script:hyUpdateJob -Force -ErrorAction SilentlyContinue

        $script:hyUpdateJob = $null

    }

}

# ---------- 显示 ----------

function Get-OpenPriceWithArrow($openVal, $prevCloseVal, $digits = 2) {

    $price = Format-Number $openVal $digits

    try {

        $o = [double]$openVal

        $p = [double]$prevCloseVal

        if ($o -gt $p) { return $price, '▲' }

        if ($o -lt $p) { return $price, '▼' }

        return $price, '-'

    } catch {}

    return $price, ' '

}

function Print-StockRowAt($r, $j, $stealth, $hasCursor) {

    # 在当前光标位罉�印单行股祼�调用前需先用 SetCursorPosition 定位�?

    if ($stealth) {

        $cursor = if ($hasCursor) { '>' } else { ' ' }

        $digits = if (Test-IsETF $r) { 3 } else { 2 }

        $price = Format-Number $r.f2 $digits

        $change = Format-Number $r.f4 $digits

        $pct = Format-Number $r.f3

        $turnover = Format-Number $r.f8

        $vr = Format-Number $r.f10

        $line = $cursor + (Pad-Left $r.f12 7) + ' ' + (Pad-Right (Truncate-Name $r.f14) 8) + ' ' + (Pad-Left "$pct%" 9) + ' ' + (Pad-Left $change 9) + ' ' + (Pad-Left $price 8) + ' ' + (Pad-Left $vr 8) + ' ' + (Pad-Left $turnover 8)

        Write-Host $line -ForegroundColor Gray

    } else {

        $bg = if ($j % 2 -eq 0) { 'Black' } else { 'DarkGray' }

        $cursor = if ($hasCursor) { '>' } else { ' ' }

        $digits = if (Test-IsETF $r) { 3 } else { 2 }

        $code = $r.f12

        $name = Truncate-Name $r.f14

        $price = Format-Number $r.f2 $digits

        $prevClose = Format-Number $r.f18 $digits

        $openPrice, $openArrow = Get-OpenPriceWithArrow $r.f17 $r.f18 $digits

        $high = Format-Number $r.f15 $digits

        $low = Format-Number $r.f16 $digits

        $change = Format-Number $r.f4 $digits

        $pct = Format-Number $r.f3

        $turnover = Format-Number $r.f8

        $vr = Format-Number $r.f10

        $amount = Format-Number $r.f6 2 100000000

        $hyPct = Format-Number $r.hyPct

        $prefix = $cursor + (Pad-Left $code 7) + ' ' + (Pad-Right $name 8) + ' '

        $pctStr = Pad-Left "$pct%" 9

        $suffix = ' ' + (Pad-Left $change 9) + ' ' + (Pad-Left $price 8) + ' ' + (Pad-Left $prevClose 8) + ' ' + (Pad-Left $openPrice 8) + $openArrow + ' ' + (Pad-Left $high 8) + ' ' + (Pad-Left $low 8) + ' ' + (Pad-Left $vr 8) + ' ' + (Pad-Left $turnover 8) + ' ' + (Pad-Left $amount 9) + ' ' + (Pad-Left "$hyPct%" 10)

        Write-Host $prefix -ForegroundColor White -BackgroundColor $bg -NoNewline

        Write-Host $pctStr -ForegroundColor White -BackgroundColor $bg -NoNewline

        Write-Host $suffix -ForegroundColor White -BackgroundColor $bg

    }

}

function Print-StockRows($rows, $stealth, $cursorIndex = -1) {

    # 记录表头�在屏幕�号，用于后续仅重绘游标所在��?

    if ($script:hasConsole) {

        try { $script:stockTableHeaderY = [Console]::CursorPosition.Y } catch {}

    }

    if ($stealth) {

        $headerPrefix = ' ' + (Pad-Left 'Code' 7) + ' ' + (Pad-Right 'Name' 8)

        $header = $headerPrefix + ' ' + (Pad-Left 'Chg%' 9) + ' ' + (Pad-Left 'Chg' 9) + ' ' + (Pad-Left 'Last' 8) + ' ' + (Pad-Left 'VolR' 8) + ' ' + (Pad-Left 'Turn%' 8)

        Write-Host $header -ForegroundColor Gray

        Write-Host ('-' * 64) -ForegroundColor DarkGray

    } else {

        $header = ' ' + (Pad-Left '代码' 7) + ' ' + (Pad-Right '名称' 8) + ' ' + (Pad-Left '涨跌幅' 9) + ' ' + (Pad-Left '涨跌额' 9) + ' ' + (Pad-Left '最新' 8) + ' ' + (Pad-Left '昨收' 8) + ' ' + (Pad-Left '今开' 9) + ' ' + (Pad-Left '最高' 8) + ' ' + (Pad-Left '最低' 8) + ' ' + (Pad-Left '量比' 8) + ' ' + (Pad-Left '换手%' 8) + ' ' + (Pad-Left '成交额' 9) + ' ' + (Pad-Left '半年涨跌' 10)

        Write-Host $header

        Write-Host ('-' * 122)

    }

    $j = 0

    foreach ($r in $rows) {

        Print-StockRowAt $r $j $stealth ($j -eq $cursorIndex)

        $j++

    }

}

function Update-Cursor($oldIndex, $newIndex, $rows, $stealth) {

    # 仅更新�首的游标字�，避免重绘整行带来的闃�与延迟�?

    # 使用 [Console]::Write 直接输出，确保立即刷新到屏幕�?

    if ($script:stockTableHeaderY -eq $null -or -not $rows -or $rows.Count -eq 0) { return }

    $rowsStartY = $script:stockTableHeaderY + 2

    $fg = if ($stealth) { [ConsoleColor]::Gray } else { [ConsoleColor]::White }

    foreach ($idx in @($oldIndex, $newIndex)) {

        if ($idx -lt 0 -or $idx -ge $rows.Count) { continue }

        try {

            [Console]::SetCursorPosition(0, $rowsStartY + $idx)

        } catch { continue }

        $prevFg = [Console]::ForegroundColor

        $prevBg = [Console]::BackgroundColor

        try {

            if (-not $stealth) {

                [Console]::BackgroundColor = if ($idx % 2 -eq 0) { [ConsoleColor]::Black } else { [ConsoleColor]::DarkGray }

            }

            [Console]::ForegroundColor = $fg

            $ch = if ($idx -eq $newIndex) { '>' } else { ' ' }

            [Console]::Write($ch)

        } finally {

            [Console]::ForegroundColor = $prevFg

            [Console]::BackgroundColor = $prevBg

        }

    }

}

function Print-IndexRows($rows, $stealth) {

    if ($rows.Count -eq 0) { return }

    $tableWidth = if ($stealth) { 64 } else { 122 }

    Write-Host ('-' * $tableWidth) -ForegroundColor DarkGray

    if ($stealth) {

        $j = 0

        foreach ($r in $rows) {

            $name = Truncate-Name "$($r.f14)"

            $price = Format-Number $r.f2

            $change = Format-Number $r.f4

            $pct = Format-Number $r.f3

            $line = (Pad-Right $name 8) + ' ' + (Pad-Left $price 10) + ' ' + (Pad-Left "$change / $pct%" 20)

            Write-Host $line -ForegroundColor Gray

            $j++

        }

        return

    }

    $perRow = 5

    $sep = ' | '

    $sepW = Measure-DisplayWidth $sep

    $boxes = @()

    $minBoxW = 0

    foreach ($r in $rows) {

        $name = Truncate-Name "$($r.f14)"

        $price = Format-Number $r.f2

        $change = Format-Number $r.f4

        $pct = Format-Number $r.f3

        $right2 = "$change / $pct%"

        $boxes += ,@($name, $price, $right2)

        $minBoxW = [math]::Max($minBoxW, [math]::Max((Measure-DisplayWidth ($name + $price)), (Measure-DisplayWidth $right2)))

    }

    $boxW = [math]::Floor(($tableWidth - ($perRow - 1) * $sepW) / $perRow)

    if ($boxW -lt $minBoxW) { $boxW = $minBoxW }

    for ($i = 0; $i -lt $boxes.Count; $i += $perRow) {

        $line1 = ""

        $line2 = ""

        for ($j = 0; $j -lt $perRow; $j++) {

            if ($i + $j -ge $boxes.Count) { break }

            $box = $boxes[$i + $j]

            $name = $box[0]

            $price = $box[1]

            $right2 = $box[2]

            $nameW = Measure-DisplayWidth $name

            $priceW = Measure-DisplayWidth $price

            $pad1 = $boxW - $nameW - $priceW

            if ($pad1 -lt 0) { $pad1 = 0 }

            $part1 = $name + (' ' * $pad1) + $price

            $right2W = Measure-DisplayWidth $right2

            $pad2 = $boxW - $right2W

            if ($pad2 -lt 0) { $pad2 = 0 }

            $part2 = (' ' * $pad2) + $right2

            if ($j -gt 0) {

                $line1 += $sep

                $line2 += $sep

            }

            $line1 += $part1

            $line2 += $part2

        }

        Write-Host (Pad-Right $line1 $tableWidth)

        Write-Host (Pad-Right $line2 $tableWidth)

    }

}

function Get-SortedRows($rows, $sortState) {

    if ($sortState.c -ne 0) {

        $field = $F_PCT_CHG

        $desc = ($sortState.c -eq 1)

    } elseif ($sortState.v -ne 0) {

        $field = $F_VOL_RATIO

        $desc = ($sortState.v -eq 1)

    } else {

        return $rows

    }

    $rows | Sort-Object {

        $v = $_.$field

        try {

            [double]$v

        } catch {

            if ($desc) { [double]::MinValue } else { [double]::MaxValue }

        }

    } -Descending:$desc

}

function Get-SortHint($sortState) {

    $parts = @()

    if ($sortState.c -eq 1) { $parts += 'C=涨跌幅↓' }

    elseif ($sortState.c -eq 2) { $parts += 'C=涨跌幅↑' }

    if ($sortState.v -eq 1) { $parts += 'V=量比↓' }

    elseif ($sortState.v -eq 2) { $parts += 'V=量比↑' }

    return $parts -join ' '

}

function Print-MarketTotal($info, $stealth) {

    # 在指数方块下方打印沪深京三市场成交��与量比�?

    if ($info -eq $null -or $info.total_yi -eq $null -or $info.ratio -eq $null) { return }

    $tableWidth = if ($stealth) { 64 } else { 122 }

    $label = "三市总额/量比 "

    $amountStr = "$($info.total_yi)"

    $value = "$amountStr / $($info.ratio)"

    if ($stealth) {

        # 让数值斜杠与 stealth 指数�?"change / pct%" 的斜杠��?

        # 指数行斜杠位于显示列 33�?-based），�倒推前�空格

        $targetSlashPos = 32  # 斜杠前所有字符的显示宽度�?-based�?

        $spacesNeeded = $targetSlashPos - (Measure-DisplayWidth $label) - (Measure-DisplayWidth $amountStr)

        if ($spacesNeeded -lt 0) { $spacesNeeded = 0 }

        $line = $label + (' ' * $spacesNeeded) + $value

    } else {

        $line = $label + $value

    }

    Write-Host (Pad-Right $line $tableWidth)

}

function Print-Quotes($stockRows, $indexRows, $showIndex, $stealth, $cursorIndex = -1) {

    $now = Get-Date -Format "HH:mm:ss"

    if ($stealth) {

        Write-Host "System Monitor  |  Last update: $now (Refresh: ${interval}s)" -ForegroundColor Gray

    } else {

        Write-Host "自选股行情 ($($stockRows.Count) 只)    刷新时间: $now (${interval} 秒自动刷新)"

    }

    if ($stockRows.Count -gt 0) {

        Print-StockRows $stockRows $stealth $cursorIndex

    }

    $rowsToShow = @()

    if ($stealth) {

        $rowsToShow = $indexRows | Where-Object { $_.f14 -eq '上证指数' -or $_.f14 -eq '深证成指' }

    } elseif ($showIndex) {

        $rowsToShow = $indexRows

    }

    if ($rowsToShow.Count -gt 0) {

        Print-IndexRows $rowsToShow $stealth

        $marketInfo = Get-MarketTotalAmounts $indexRows

        Print-MarketTotal $marketInfo $stealth

    }

}

function Enter-DepthMode($row, $stockRows, $startIndex) {

    $script:depthMode = $true

    $script:depthRow = $row

    $script:depthSecid = "$($row.f13).$($row.f12)"

    $script:depthStockRows = $stockRows

    $script:depthStockIndex = $startIndex

    $script:depthNextRefreshTime = (Get-Date).AddSeconds(5)

    $script:lastDepthVolume = $null

    $script:depthViewDrawn = $false

    $script:depthViewLast = $null

    Clear-Host

}

function Exit-DepthMode {

    $script:depthMode = $false

    $script:depthSecid = $null

    $script:depthRow = $null

    $script:depthStockRows = $null

    $script:depthStockIndex = $null

    $script:depthNextRefreshTime = $null

    $script:lastDepthVolume = $null

    $script:depthViewDrawn = $false

    $script:depthViewLast = $null

    Clear-Host

}

function Show-DepthView($row, $stealth) {

    $secid = "$($row.f13).$($row.f12)"

    $d = Fetch-DepthData $secid $row.f14

    if ($d -eq $null) {

        if (-not $script:depthViewDrawn) {

            Clear-Host

            Write-Host "[错误] 无法获取盘口数据" -ForegroundColor Red

        }

        return $false

    }

    $name = $d.name

    $code = $d.code

    $digits = if ($name -and $name.ToUpper().Contains('ETF')) { 3 } else { 2 }

    $hasQuote = $false

    try { if ([double]$d.price -ne 0) { $hasQuote = $true } } catch {}

    $normalFg = if ($stealth) { 'Gray' } else { 'White' }

    $redFg = if ($stealth) { 'Gray' } else { 'Red' }

    $greenFg = if ($stealth) { 'Gray' } else { 'Green' }

    $mainSep = '-' * 53

    $rightSep = '-' * 28

    $lines = @()

    # 标题行：名称 代码 最新价▲▼ 涨跌额 涨跌幅

    if ($hasQuote) {

        $price = Format-Number $d.price $digits

        $change = Format-Number $d.change $digits

        $pct = Format-Number $d.pct_chg

        if ($d.change -gt 0) { $arrow = '▲'; $headerFg = $redFg }

        elseif ($d.change -lt 0) { $arrow = '▼'; $headerFg = $greenFg }

        else { $arrow = '─'; $headerFg = $normalFg }

        $pricePart = $price + ' ' + $arrow

        $pricePartPadded = $pricePart + (' ' * (12 - (Measure-DisplayWidth $pricePart)))

        $changePadded = $change + (' ' * (9 - (Measure-DisplayWidth $change)))

        $header = (Pad-Right $name 8) + '    ' + (Pad-Right $code 6) + '        ' + $pricePartPadded + $changePadded + $pct + '%'

    } else {

        $headerFg = if ($stealth) { 'Gray' } else { 'DarkGray' }

        $header = (Pad-Right $name 8) + '    ' + (Pad-Right $code 6) + '        未开盘'

    }

    $lines += [PSCustomObject]@{ Text = $header; Color = $headerFg }

    if ($hasQuote) {

        $lines += [PSCustomObject]@{ Text = $mainSep; Color = 'DarkGray' }

        # 涨停跌停

        $isETF = $name -and $name.ToUpper().Contains('ETF')

        $limitUp = $null

        $limitDown = $null

        if (-not $isETF -and $d.prev_close -ne $null -and $d.prev_close -ne 0) {

            $limitRatio = 0.10

            if ($name -match 'ST') { $limitRatio = 0.05 }

            elseif ($code -match '^688') { $limitRatio = 0.20 }

            elseif ($code -match '^(300|301)') { $limitRatio = 0.20 }

            elseif ($code -match '^(8|4)') { $limitRatio = 0.30 }

            $limitUp = [math]::Round($d.prev_close * (1 + $limitRatio), 2)

            $limitDown = [math]::Round($d.prev_close * (1 - $limitRatio), 2)

        }

        # 左侧信息

        $leftLabels = @('最新', '现手', '昨收', '今开', '最高', '最低', '涨停', '跌停', '换手', '成交', '量比')

        $leftValues = @(
            (Format-Number $d.price $digits),
            (Format-LatestVol $row.f30),
            (Format-Number $d.prev_close $digits),
            (Format-Number $d.open $digits),
            (Format-Number $d.high $digits),
            (Format-Number $d.low $digits),
            (Format-Number $limitUp $digits),
            (Format-Number $limitDown $digits),
            ((Format-Number $row.f8) + '%'),
            ((Format-Yi $row.f6) + '亿'),
            (Format-Number $row.f10)
        )

        # 右侧盘口

        $rightLines = @()

        $hasDepth = $false

        for ($i = 4; $i -ge 0; $i--) {

            $p = Format-Number $d.asks[$i][0] $digits

            $v = Format-Number $d.asks[$i][1] 0

            if ($p -ne '-' -and $v -ne '-') { $hasDepth = $true }

            $rightLines += (Pad-Right "卖$($i + 1)" 4) + ' ' + (Pad-Left $p 10) + ' ' + (Pad-Left $v 12)

        }

        $rightLines += $rightSep

        for ($i = 0; $i -lt 5; $i++) {

            $p = Format-Number $d.bids[$i][0] $digits

            $v = Format-Number $d.bids[$i][1] 0

            if ($p -ne '-' -and $v -ne '-') { $hasDepth = $true }

            $rightLines += (Pad-Right "买$($i + 1)" 4) + ' ' + (Pad-Left $p 10) + ' ' + (Pad-Left $v 12)

        }

        if (-not $hasDepth) {

            $lines += [PSCustomObject]@{ Text = '  暂无盘口数据'; Color = 'DarkGray' }

        } else {

            for ($i = 0; $i -lt $leftLabels.Count; $i++) {

                $left = (Pad-Right $leftLabels[$i] 6) + ' ' + (Pad-Left $leftValues[$i] 14)

                $lines += [PSCustomObject]@{ Text = ($left + '    ' + $rightLines[$i]); Color = $normalFg }

            }

        }

        $lines += [PSCustomObject]@{ Text = $mainSep; Color = 'DarkGray' }

        # 市值 + 流通

        $totalCap = Format-WanYi $row.f20

        $floatCap = Format-Yi $row.f21

        $capLine = (Pad-Right '市值' 6) + ' ' + (Pad-Left ($totalCap + '万亿') 14) + '        ' + (Pad-Right '流通' 6) + ' ' + (Pad-Left ($floatCap + '亿') 14)

        $lines += [PSCustomObject]@{ Text = $capLine; Color = $normalFg }

        $lines += [PSCustomObject]@{ Text = ''; Color = $normalFg }

    } else {

        $lines += [PSCustomObject]@{ Text = '  暂无行情'; Color = 'DarkGray' }

    }

    # 增量渲染：首次全屏绘制，之后只重写变化的行

    try {

        if (-not $script:depthViewDrawn) {

            Clear-Host

            for ($i = 0; $i -lt $lines.Count; $i++) {

                [Console]::SetCursorPosition(0, $i)

                $text = $lines[$i].Text

                $pad = [Console]::WindowWidth - (Measure-DisplayWidth $text)

                if ($pad -gt 0) { $text += ' ' * $pad }

                Write-Host $text -ForegroundColor $lines[$i].Color -NoNewline

            }

            $script:depthViewDrawn = $true

        } else {

            for ($i = 0; $i -lt $lines.Count; $i++) {

                $prev = $script:depthViewLast[$i]

                if ($prev -eq $null -or $lines[$i].Text -ne $prev.Text -or $lines[$i].Color -ne $prev.Color) {

                    [Console]::SetCursorPosition(0, $i)

                    $text = $lines[$i].Text

                    $pad = [Console]::WindowWidth - (Measure-DisplayWidth $text)

                    if ($pad -gt 0) { $text += ' ' * $pad }

                    Write-Host $text -ForegroundColor $lines[$i].Color -NoNewline

                }

            }

            # 清除旧的、不再使用的行（多清一行，防止旧按键提示残留）

            if ($script:depthViewLast.Count -gt $lines.Count) {

                for ($i = $lines.Count; $i -le $script:depthViewLast.Count; $i++) {

                    [Console]::SetCursorPosition(0, $i)

                    [Console]::Write(' ' * [Console]::WindowWidth)

                }

            }

        }

        # 把光标移到最后一行末尾，保证后续按键提示能接在盘口下方

        $lastIdx = $lines.Count - 1

        [Console]::SetCursorPosition((Measure-DisplayWidth $lines[$lastIdx].Text), $lastIdx)

    } catch {

        # 非控制台环境（如输出被重定向）回退到普通输出

        Clear-Host

        foreach ($line in $lines) {

            Write-Host $line.Text -ForegroundColor $line.Color

        }

        $script:depthViewDrawn = $true

    }

    $script:depthViewLast = $lines

    $script:lastDepthVolume = $d.volume

    return $true

}

function Show-FakeScreen {

    Clear-Host

    $t = Get-Date -Format "HH:mm:ss"

    Write-Host "> npm run build" -ForegroundColor Gray

    Write-Host ""

    Write-Host "> project@1.0.0 build D:\project" -ForegroundColor Gray

    Write-Host "> tsc && vite build" -ForegroundColor Gray

    Write-Host ""

    Write-Host "vite v5.0.0 building for production..." -ForegroundColor Gray

    Write-Host "�?128 modules transformed." -ForegroundColor Gray

    Write-Host "dist/index.html                   0.45 kB" -ForegroundColor Gray

    Write-Host "dist/assets/index-a1b2c3d4.js   142.31 kB" -ForegroundColor Gray

    Write-Host "�?built in 3.42s" -ForegroundColor Gray

    Write-Host ""

    Write-Host "[$t] Watching for changes..." -ForegroundColor DarkGray

}

function Show-ButtonBar($stealth, $depthMode = $false) {

    $barY = -1

    try { $barY = $host.UI.RawUI.CursorPosition.Y } catch {}

    $buttons = if ($depthMode) {

        @(

            @{ Key='R'; Stealth='R refresh'; Normal='R 刷新' },

            @{ Key='Down'; Stealth='↑↓ switch'; Normal='↑↓ 切换' },

            @{ Key='Left'; Stealth='← back'; Normal='← 返回' }

        )

    } else {

        @(

            @{ Key='R'; Stealth='R refresh'; Normal='R 刷新' },

            @{ Key='C'; Stealth='C sort%'; Normal='C 涨跌幅排序' },

            @{ Key='V'; Stealth='V sortVR'; Normal='V 量比排序' },

            @{ Key='B'; Stealth='B hide'; Normal='B 伪装' },

            @{ Key='S'; Stealth='S mode'; Normal='S 切换' },

            @{ Key='Esc'; Stealth='Esc exit'; Normal='Esc 退出' }

        )

    }

    $regions = @()

    $x = 0

    $sep = ' '

    $sepW = Measure-DisplayWidth $sep

    $bg = if ($stealth) { $null } else { 'Gray' }

    $fg = if ($stealth) { 'Gray' } else { 'Black' }

    for ($i = 0; $i -lt $buttons.Count; $i++) {

        $b = $buttons[$i]

        $labelText = if ($stealth) { $b.Stealth } else { $b.Normal }

        $label = "[$labelText]"

        $labelW = Measure-DisplayWidth $label

        $regions += [PSCustomObject]@{

            Key = $b.Key

            StartX = $x

            EndX = $x + $labelW - 1

            Y = $barY

        }

        if ($stealth) {

            Write-Host $label -ForegroundColor $fg -NoNewline

        } else {

            Write-Host $label -ForegroundColor $fg -BackgroundColor $bg -NoNewline

        }

        $x += $labelW

        if ($i -lt $buttons.Count - 1) {

            Write-Host $sep -NoNewline

            $x += $sepW

        }

    }

    Write-Host ""

    return $regions

}

# ---------- 控制台输入（攌�鼠标点击�?----------

$script:consoleInputInitialized = $false

$script:hInput = [IntPtr]::Zero

$script:originalConsoleMode = $null

function Initialize-ConsoleInput {

    if ($script:consoleInputInitialized) { return $true }

    try {

        Add-Type -TypeDefinition @"

using System;

using System.Runtime.InteropServices;

public class ConsoleInputHelper {

    public const int STD_INPUT_HANDLE = -10;

    public const uint ENABLE_MOUSE_INPUT = 0x0010;

    public const uint ENABLE_EXTENDED_FLAGS = 0x0080;

    public const uint ENABLE_QUICK_EDIT_MODE = 0x0040;

    public const ushort KEY_EVENT = 1;

    public const ushort MOUSE_EVENT = 2;

    public const uint MOUSE_LEFT_BUTTON = 0x0001;

    [DllImport("kernel32.dll", SetLastError = true)]

    public static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]

    public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);

    [DllImport("kernel32.dll", SetLastError = true)]

    public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);

    [DllImport("kernel32.dll", SetLastError = true)]

    public static extern bool GetNumberOfConsoleInputEvents(IntPtr hConsoleInput, out uint lpNumberOfEvents);

    [DllImport("kernel32.dll", SetLastError = true)]

    public static extern bool ReadConsoleInput(IntPtr hConsoleInput, [Out] INPUT_RECORD[] lpBuffer, uint nLength, out uint lpNumberOfEventsRead);

    [StructLayout(LayoutKind.Explicit)]

    public struct INPUT_RECORD {

        [FieldOffset(0)] public ushort EventType;

        [FieldOffset(4)] public KEY_EVENT_RECORD KeyEvent;

        [FieldOffset(4)] public MOUSE_EVENT_RECORD MouseEvent;

    }

    [StructLayout(LayoutKind.Explicit)]

    public struct KEY_EVENT_RECORD {

        [FieldOffset(0)] public int bKeyDown;

        [FieldOffset(4)] public ushort wRepeatCount;

        [FieldOffset(6)] public ushort wVirtualKeyCode;

        [FieldOffset(8)] public ushort wVirtualScanCode;

        [FieldOffset(10)] public char UnicodeChar;

        [FieldOffset(12)] public uint dwControlKeyState;

    }

    [StructLayout(LayoutKind.Explicit)]

    public struct MOUSE_EVENT_RECORD {

        [FieldOffset(0)] public COORD dwMousePosition;

        [FieldOffset(4)] public uint dwButtonState;

        [FieldOffset(8)] public uint dwControlKeyState;

        [FieldOffset(12)] public uint dwEventFlags;

    }

    [StructLayout(LayoutKind.Sequential)]

    public struct COORD {

        public short X;

        public short Y;

    }

}

"@

        -ErrorAction Stop

    } catch {

        try { [void][ConsoleInputHelper] } catch { return $false }

    }

    $h = [ConsoleInputHelper]::GetStdHandle([ConsoleInputHelper]::STD_INPUT_HANDLE)

    if ($h -eq [IntPtr]::Zero -or $h -eq [IntPtr]::new(-1)) { return $false }

    $mode = 0

    if (-not [ConsoleInputHelper]::GetConsoleMode($h, [ref]$mode)) { return $false }

    $script:originalConsoleMode = $mode

    $newMode = ($mode -band -bnot [ConsoleInputHelper]::ENABLE_QUICK_EDIT_MODE) -bor [ConsoleInputHelper]::ENABLE_EXTENDED_FLAGS -bor [ConsoleInputHelper]::ENABLE_MOUSE_INPUT

    if (-not [ConsoleInputHelper]::SetConsoleMode($h, $newMode)) { return $false }

    $script:hInput = $h

    $script:consoleInputInitialized = $true

    return $true

}

function Read-ConsoleInputEvent {

    if (-not $script:consoleInputInitialized) { return $null }

    $events = 0

    if (-not [ConsoleInputHelper]::GetNumberOfConsoleInputEvents($script:hInput, [ref]$events)) { return $null }

    if ($events -eq 0) { return $null }

    $records = New-Object ConsoleInputHelper+INPUT_RECORD[] 1

    $read = 0

    if (-not [ConsoleInputHelper]::ReadConsoleInput($script:hInput, $records, 1, [ref]$read)) { return $null }

    if ($read -eq 0) { return $null }

    $rec = $records[0]

    if ($rec.EventType -eq [ConsoleInputHelper]::KEY_EVENT -and $rec.KeyEvent.bKeyDown -ne 0) {

        $vk = [int]$rec.KeyEvent.wVirtualKeyCode

        if (-not [Enum]::IsDefined([ConsoleKey], $vk)) { return $null }

        return [PSCustomObject]@{

            Type = 'Key'

            Key = [ConsoleKey]$vk

        }

    }

    elseif ($rec.EventType -eq [ConsoleInputHelper]::MOUSE_EVENT) {

        $btn = $rec.MouseEvent.dwButtonState

        $flags = $rec.MouseEvent.dwEventFlags

        if (($btn -band [ConsoleInputHelper]::MOUSE_LEFT_BUTTON) -ne 0 -and $flags -eq 0) {

            return [PSCustomObject]@{

                Type = 'Mouse'

                X = [int]$rec.MouseEvent.dwMousePosition.X

                Y = [int]$rec.MouseEvent.dwMousePosition.Y

                Button = 'Left'

            }

        }

    }

    return $null

}

function Restore-ConsoleInput {

    if ($script:consoleInputInitialized -and $script:hInput -ne [IntPtr]::Zero -and $script:originalConsoleMode -ne $null) {

        [void][ConsoleInputHelper]::SetConsoleMode($script:hInput, $script:originalConsoleMode)

    }

}

# ---------- 参数解析 ----------

if ($args -contains '--help' -or $args -contains '-h') {

    Write-Host "Usage: watch.cmd [interval] [--index on|off] [--stealth on|off] [--hy on|off] [--once]"

    Write-Host ""

    Write-Host "List view keys:"

    Write-Host "  R          refresh quotes"

    Write-Host "  C          sort by change% (high->low->low->high->original)"

    Write-Host "  V          sort by volume ratio (high->low->low->high->original)"

    Write-Host "  S          toggle stealth/home mode"

    Write-Host "  B / F9     toggle boss mode (fake npm build log)"

    Write-Host "  Up/Down    move cursor"

    Write-Host "  Right      enter depth view (5-level bid/ask)"

    Write-Host "  Esc        exit"

    Write-Host ""

    Write-Host "Depth view keys:"

    Write-Host "  R          refresh depth"

    Write-Host "  Up/Down    previous/next stock in list order"

    Write-Host "  Left/Esc   back to list"

    exit 0

}

$interval = 15

$showIndex = $false

$stealth = $true

$fetchHy = $false

$once = $false

$i = 0

while ($i -lt $args.Count) {

    $arg = $args[$i]

    if ($arg -eq '--index' -or $arg -eq '-index') {

        $i++

        if ($i -lt $args.Count -and ($args[$i] -eq 'on' -or $args[$i] -eq 'true')) {

            $showIndex = $true

        } else {

            $showIndex = $false

        }

    } elseif ($arg -eq '--stealth' -or $arg -eq '-stealth') {

        $i++

        if ($i -lt $args.Count -and ($args[$i] -eq 'off' -or $args[$i] -eq 'false')) {

            $stealth = $false

        } else {

            $stealth = $true

        }

    } elseif ($arg -eq '--hy' -or $arg -eq '-hy') {

        $i++

        if ($i -lt $args.Count -and ($args[$i] -eq 'on' -or $args[$i] -eq 'true')) {

            $fetchHy = $true

        } else {

            $fetchHy = $false

        }

    } elseif ($arg -eq '--once' -or $arg -eq '-once') {

        $once = $true

    } else {

        try {

            $parsed = [int]$arg

            if ($parsed -gt 0) {

                $interval = $parsed

            }

        } catch {

            # ignore non-integer argument

        }

    }

    $i++

}

# ---------- 初��?----------

Load-SecidCache

Load-HyCache

Load-MarketTotalCache

$hasConsole = $false

try {

    [void][Console]::CursorVisible

    $hasConsole = $true

} catch {

    $hasConsole = $false

}

if ($hasConsole -and $stealth) {

    try { $host.ui.RawUI.WindowTitle = "System" } catch {}

}

# ---------- 主流�?----------

if ($once) {

    $stockRows, $indexRows, $err = Get-Quotes $stealth

    if ($err) {

        Write-Host $err

        exit 1

    }

    Apply-HalfYearPct $stockRows

    Print-Quotes $stockRows $indexRows $showIndex $stealth 0

    if ($fetchHy) {

        Update-HalfYearCache $stockRows

    }

    exit 0

}

$initErr = Initialize-Quotes $stealth

if ($initErr) {

    Write-Host $initErr

    exit 1

}

try {

    if ($hasConsole) { [Console]::CursorVisible = $false }

    $first = $true

    $bossMode = $false

    $sortState = @{ c = 0; v = 0 }  # 0=原样, 1=从高到低, 2=从低到高

    $cursorIndex = 0                  # 游标默�在��参��?

    $depthMode = $false               # 昐�处于丂�盘口详情�?

    $depthSecid = $null

    $depthRow = $null

    $depthNextRefreshTime = $null

    $lastDepthVolume = $null

    :main while ($true) {

        try {

            if ($first) {

                Clear-Host

                $first = $false

            } elseif ($hasConsole -and -not $bossMode -and -not $depthMode) {

                try {

                    [Console]::SetCursorPosition(0, 0)

                } catch {

                    Clear-Host

                }

            } elseif (-not $hasConsole) {

                Clear-Host

            }

            if ($bossMode) {

                Show-FakeScreen

            } elseif ($depthMode) {

                if ((Get-Date) -ge $depthNextRefreshTime) {

                    $depthNextRefreshTime = (Get-Date).AddSeconds(5)

                }

                $null = Show-DepthView $depthRow $stealth

            } else {

                $stockRows = @(Get-CachedRows $script:stockQuoteCache $script:stockSecids)

                $indexRows = @(Get-CachedRows $script:indexQuoteCache $script:indexSecids)

                Apply-HalfYearPct $stockRows

                $displayRows = Get-SortedRows $stockRows $sortState

                if ($cursorIndex -lt 0) { $cursorIndex = 0 }

                if ($cursorIndex -ge $displayRows.Count) { $cursorIndex = [math]::Max(0, $displayRows.Count - 1) }

                Print-Quotes $displayRows $indexRows $showIndex $stealth $cursorIndex

            }

            if ($fetchHy -and $script:stockQuoteCache.Count -gt 0) {

                # 每�徎�先应用已完成的后台结果，硿�缓存数据尽快�

                Complete-HalfYearUpdate

                # 实际发起新的半年涨跌请求则按 4 倍自动刷新间隔控�?

                if ((Get-Date) -ge $script:nextHyStartTime) {

                    Start-HalfYearUpdate $stockRows

                    $script:nextHyStartTime = (Get-Date).AddSeconds($script:hyStartInterval)

                }

            }

        } catch {

            if ($first) { Clear-Host; $first = $false }

            Write-Host "[error] display failed: $_"

        }

        $buttonRegions = $null

        if (-not $bossMode) {

            Write-Host ""

            if ($depthMode) { Write-Host "" }

            $buttonRegions = Show-ButtonBar $stealth $depthMode

        }

        if ($hasConsole) {

            $useConsoleInput = Initialize-ConsoleInput

            $slept = 0

            :poll while ($slept -lt $interval * 1000) {

                Start-Sleep -Milliseconds 10

                $slept += 10

                # 盘口详情�?5 秒自动刷�?

                if ($depthMode -and (Get-Date) -ge $depthNextRefreshTime) {

                    $depthNextRefreshTime = (Get-Date).AddSeconds(5)

                    break

                }

                # 分块增量刷新：到点就拉取下一块并立即重绘（盘口页内暂停）

                if (-not $bossMode -and -not $depthMode -and (Get-Date) -ge $script:nextChunkTime) {

                    Update-NextChunk $stealth

                    break

                }

                $inputEvent = $null

                if ($useConsoleInput) {

                    $inputEvent = Read-ConsoleInputEvent

                } elseif ([Console]::KeyAvailable) {

                    $inputEvent = [PSCustomObject]@{ Type = 'Key'; Key = [Console]::ReadKey($true).Key }

                }

                if ($inputEvent -ne $null) {

                    $action = $null

                    if ($inputEvent.Type -eq 'Key') {

                        switch ($inputEvent.Key) {

                            ([ConsoleKey]::Escape) { $action = if ($depthMode) { 'DepthExit' } else { 'Exit' } }

                            ([ConsoleKey]::R) { $action = 'Refresh' }

                            ([ConsoleKey]::B) { $action = 'Hide' }

                            ([ConsoleKey]::F9) { $action = 'Hide' }

                            ([ConsoleKey]::S) { $action = if ($depthMode) { $null } else { 'Mode' } }

                            ([ConsoleKey]::C) { $action = if ($depthMode) { $null } else { 'SortPct' } }

                            ([ConsoleKey]::V) { $action = if ($depthMode) { $null } else { 'SortVR' } }

                            ([ConsoleKey]::UpArrow) { $action = if ($depthMode) { 'DepthPrev' } else { 'CursorUp' } }

                            ([ConsoleKey]::DownArrow) { $action = if ($depthMode) { 'DepthNext' } else { 'CursorDown' } }

                            ([ConsoleKey]::RightArrow) { $action = if ($depthMode) { $null } else { 'DepthEnter' } }

                            ([ConsoleKey]::LeftArrow) { $action = if ($depthMode) { 'DepthExit' } else { $null } }

                        }

                    } elseif ($inputEvent.Type -eq 'Mouse' -and $inputEvent.Button -eq 'Left') {

                        $clicked = $null

                        if ($buttonRegions -ne $null) {

                            $clicked = $buttonRegions | Where-Object {

                                $inputEvent.Y -eq $_.Y -and $inputEvent.X -ge $_.StartX -and $inputEvent.X -le $_.EndX

                            } | Select-Object -First 1

                        }

                        if ($clicked -ne $null) {

                            switch ($clicked.Key) {

                                'R' { $action = 'Refresh' }

                                'C' { $action = 'SortPct' }

                                'V' { $action = 'SortVR' }

                                'B' { $action = 'Hide' }

                                'S' { $action = 'Mode' }

                                'Esc' { if (-not $depthMode) { $action = 'Exit' } }

                                'Left' { $action = 'DepthExit' }

                                'Up' { $action = 'DepthPrev' }

                                'Down' { $action = 'DepthNext' }

                            }

                        }

                    }

                    if ($action -ne $null) {

                        switch ($action) {

                            'Exit' { break main }

                            'Refresh' {

                                if ($depthMode) {

                                    $depthNextRefreshTime = (Get-Date).AddSeconds(5)

                                    break poll

                                } else {

                                    $err = Initialize-Quotes $stealth

                                    if ($err) {

                                        Clear-Host

                                        Write-Host $err

                                    } else {

                                        Clear-Host

                                    }

                                    break poll

                                }

                            }

                            'Hide' {

                                $bossMode = -not $bossMode

                                if ($bossMode) {

                                    Show-FakeScreen

                                } else {

                                    Clear-Host

                                }

                                break poll

                            }

                            'Mode' {

                                $stealth = -not $stealth

                                $showIndex = -not $showIndex

                                if ($hasConsole) {

                                    try {

                                        if ($stealth) { $host.ui.RawUI.WindowTitle = "System" }

                                        else { $host.ui.RawUI.WindowTitle = "行情监控" }

                                    } catch {}

                                }

                                # 切换模式后重新初始化，避免字段不匹配

                                Initialize-Quotes $stealth | Out-Null

                                Clear-Host

                                break poll

                            }

                            'SortPct' {

                                $sortState.c = if ($sortState.c -eq 0) { 1 } else { 0 }

                                $sortState.v = 0

                                Clear-Host

                                break poll

                            }

                            'SortVR' {

                                $sortState.v = if ($sortState.v -eq 0) { 1 } else { 0 }

                                $sortState.c = 0

                                Clear-Host

                                break poll

                            }

                            'CursorUp' {

                                $cursorIndex = if ($displayRows.Count -gt 0) { ($cursorIndex - 1 + $displayRows.Count) % $displayRows.Count } else { 0 }

                                break poll

                            }

                            'CursorDown' {

                                $cursorIndex = if ($displayRows.Count -gt 0) { ($cursorIndex + 1) % $displayRows.Count } else { 0 }

                                break poll

                            }

                            'DepthEnter' {

                                if (-not $depthMode -and $displayRows.Count -gt 0) {

                                    Enter-DepthMode $displayRows[$cursorIndex] $displayRows $cursorIndex

                                }

                                break poll

                            }

                            'DepthExit' {

                                if ($depthMode) { Exit-DepthMode }

                                break poll

                            }

                            'DepthPrev' {

                                if ($depthMode -and $script:depthStockRows -ne $null -and $script:depthStockRows.Count -gt 0) {

                                    $script:depthStockIndex = ($script:depthStockIndex - 1 + $script:depthStockRows.Count) % $script:depthStockRows.Count

                                    $script:depthRow = $script:depthStockRows[$script:depthStockIndex]

                                    $script:depthSecid = "$($script:depthRow.f13).$($script:depthRow.f12)"

                                    $script:depthNextRefreshTime = (Get-Date).AddSeconds(5)

                                    $script:depthViewDrawn = $false

                                    $script:depthViewLast = $null

                                }

                                break poll

                            }

                            'DepthNext' {

                                if ($depthMode -and $script:depthStockRows -ne $null -and $script:depthStockRows.Count -gt 0) {

                                    $script:depthStockIndex = ($script:depthStockIndex + 1) % $script:depthStockRows.Count

                                    $script:depthRow = $script:depthStockRows[$script:depthStockIndex]

                                    $script:depthSecid = "$($script:depthRow.f13).$($script:depthRow.f12)"

                                    $script:depthNextRefreshTime = (Get-Date).AddSeconds(5)

                                    $script:depthViewDrawn = $false

                                    $script:depthViewLast = $null

                                }

                                break poll

                            }

                        }

                    }

                }

            }

        } else {

            # 非控制台�下仍然分块刷�?

            $slept = 0

            while ($slept -lt $interval * 1000) {

                Start-Sleep -Milliseconds 100

                $slept += 100

                if ((Get-Date) -ge $script:nextChunkTime) {

                    Update-NextChunk $stealth

                    break

                }

            }

        }

    }

} finally {

    Restore-ConsoleInput

    if ($script:hyUpdateJob -ne $null) {

        Stop-Job $script:hyUpdateJob -ErrorAction SilentlyContinue

        Remove-Job $script:hyUpdateJob -Force -ErrorAction SilentlyContinue

        $script:hyUpdateJob = $null

    }

    if ($hasConsole) {

        [Console]::CursorVisible = $true

        try { $host.ui.RawUI.WindowTitle = "Windows PowerShell" } catch {}

    }

    Clear-Host

    Write-Host "Exited"

}
