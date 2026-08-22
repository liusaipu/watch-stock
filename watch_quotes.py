"""
股票行情监视器（Python 跨平台版）
用法:
  python watch_quotes.py [刷新秒数] [--index on|off] [--stealth on|off] [--hy on|off] [--once] [-h]

快捷键:
  Esc        退出程序或返回上一层
  R          立即刷新
  C          按涨跌幅排序（第一次高到低，第二次低到高，第三次恢复）
  V          按量比排序（第一次高到低，第二次低到高，第三次恢复）
  S          切换简化模式 / 详情模式
  B / F9     切换 npm 构建日志外观 / 正常行情
  ↑ / ↓      移动光标（盘口页：切换上一只 / 下一只）
  →          进入选中股票的盘口详情
  ←          盘口页返回列表
  Ctrl+C     强制退出
"""

import json
import os
import sys
import time
import traceback

from quotes_core import (
    BASE_DIR, F_CODE, F_MARKET, F_NAME, F_PRICE, F_PCT_CHG, F_CHG,
    F_VOL, F_AMT, F_TURNOVER, F_VOL_RATIO, F_HIGH, F_LOW, F_OPEN, F_PREV_CLOSE,
    F_TOTAL_CAP, F_FLOAT_CAP, F_LATEST_VOL,
    search_secids, fetch_quote_rows, get_key, truncate_name, is_etf,
    fmt_num, fmt_open_price, display_width, pad_left, pad_right,
    get_market_total_amounts, fetch_depth_data,
    enter_raw_mode, restore_terminal,
    apply_half_year_pct, start_half_year_update, complete_half_year_update,
)


# ── ANSI 颜色/控制 ──────────────────────────────────────────
_C_RESET = '\033[0m'
_C_RED = '\033[91m'
_C_GREEN = '\033[92m'
_C_WHITE = '\033[97m'
_C_GRAY = '\033[90m'
_C_BLACK_BG = '\033[40m'
_C_DARKGRAY_BG = '\033[100m'
_C_HIDE_CURSOR = '\033[?25l'
_C_SHOW_CURSOR = '\033[?25h'


def _color(s, c):
    return f'{c}{s}{_C_RESET}'


def _set_title(title):
    """通过 ANSI OSC 序列设置终端窗口标题。"""
    try:
        print(f'\033]0;{title}\007', end='')
        sys.stdout.flush()
    except Exception:
        pass


def clear_screen():
    """清屏并把光标移到左上角。"""
    print('\033[2J\033[H', end='')
    sys.stdout.flush()


def hide_cursor():
    print(_C_HIDE_CURSOR, end='')
    sys.stdout.flush()


def show_cursor():
    print(_C_SHOW_CURSOR, end='')
    sys.stdout.flush()


# ── 行情获取 ────────────────────────────────────────────────
def get_quotes(fetch_hy=False):
    """读取自选股并拉取行情，可选地触发半年涨跌后台更新。"""
    wl_path = os.path.join(BASE_DIR, 'watchlist.json')
    with open(wl_path, 'r', encoding='utf-8') as f:
        wl = json.load(f)
    stocks = wl.get('stocks', [])
    indices = wl.get('indices', [])

    stock_secids = search_secids(stocks)
    index_secids = search_secids(indices)

    if not stock_secids and not index_secids:
        return None, None, '没有可查询的股票或指数'

    all_secids = stock_secids + index_secids
    rows = fetch_quote_rows(all_secids)

    stock_rows = []
    index_rows = []
    index_set = set(index_secids)
    for r in rows:
        secid = f"{r.get(F_MARKET, '0')}.{r.get(F_CODE, '')}"
        if secid in index_set:
            index_rows.append(r)
        else:
            stock_rows.append(r)

    if fetch_hy and stock_secids:
        start_half_year_update(stock_secids)

    return stock_rows, index_rows, None


# ── 列表格式化 ──────────────────────────────────────────────
def _fmt_row_stealth(r):
    """简化模式单行格式化（与 PowerShell 版字段/顺序/宽度一致）。"""
    digits = 3 if is_etf(r) else 2
    code = r.get(F_CODE, '')
    name = truncate_name(r.get(F_NAME, ''))
    pct = fmt_num(r.get(F_PCT_CHG))
    change = fmt_num(r.get(F_CHG), digits=digits)
    price = fmt_num(r.get(F_PRICE), digits=digits)
    vr = fmt_num(r.get(F_VOL_RATIO))
    turnover = fmt_num(r.get(F_TURNOVER))
    return (
        f"{pad_left(code, 7)} {pad_right(name, 8)} "
        f"{pad_left(f'{pct}%', 9)} {pad_left(change, 9)} "
        f"{pad_left(price, 8)} {pad_left(vr, 8)} {pad_left(turnover, 8)}"
    )


def _fmt_row_normal(r):
    """详情模式单行格式化（与 PowerShell 版字段/顺序/宽度一致）。"""
    digits = 3 if is_etf(r) else 2
    code = r.get(F_CODE, '')
    name = truncate_name(r.get(F_NAME, ''))
    pct = fmt_num(r.get(F_PCT_CHG))
    change = fmt_num(r.get(F_CHG), digits=digits)
    price = fmt_num(r.get(F_PRICE), digits=digits)
    prev_close = fmt_num(r.get(F_PREV_CLOSE), digits=digits)
    open_price, open_arrow = fmt_open_price(r.get(F_OPEN), r.get(F_PREV_CLOSE), digits=digits)
    high = fmt_num(r.get(F_HIGH), digits=digits)
    low = fmt_num(r.get(F_LOW), digits=digits)
    vr = fmt_num(r.get(F_VOL_RATIO))
    turnover = fmt_num(r.get(F_TURNOVER))
    amount = fmt_num(r.get(F_AMT), divisor=100000000)
    hy_pct = fmt_num(r.get('hyPct'))
    return (
        f"{pad_left(code, 7)} {pad_right(name, 8)} "
        f"{pad_left(f'{pct}%', 9)} {pad_left(change, 9)} "
        f"{pad_left(price, 8)} {pad_left(prev_close, 8)} {pad_left(open_price, 8)}{open_arrow} "
        f"{pad_left(high, 8)} {pad_left(low, 8)} {pad_left(vr, 8)} "
        f"{pad_left(turnover, 8)} {pad_left(amount, 9)} {pad_left(f'{hy_pct}%', 10)}"
    )


def print_stocks(rows, stealth, highlight_idx=-1):
    """打印自选股列表。"""
    if stealth:
        header = (
            ' ' + pad_left('Code', 7) + ' ' + pad_right('Name', 8) + ' ' +
            pad_left('Chg%', 9) + ' ' + pad_left('Chg', 9) + ' ' +
            pad_left('Last', 8) + ' ' + pad_left('VolR', 8) + ' ' + pad_left('Turn%', 8)
        )
        width = 64
        print(_color(header, _C_WHITE))
        print(_color('-' * width, _C_WHITE))
        for i, r in enumerate(rows):
            prefix = '>' if i == highlight_idx else ' '
            line = prefix + _fmt_row_stealth(r)
            print(_color(line, _C_WHITE))
    else:
        header = (
            ' ' + pad_left('代码', 7) + ' ' + pad_right('名称', 8) + ' ' +
            pad_left('涨跌幅', 9) + ' ' + pad_left('涨跌额', 9) + ' ' +
            pad_left('最新', 8) + ' ' + pad_left('昨收', 8) + ' ' + pad_left('今开', 9) + ' ' +
            pad_left('最高', 8) + ' ' + pad_left('最低', 8) + ' ' + pad_left('量比', 8) + ' ' +
            pad_left('换手%', 8) + ' ' + pad_left('成交额', 9) + ' ' + pad_left('半年涨跌', 10)
        )
        width = 122
        print(header)
        print('-' * width)
        for i, r in enumerate(rows):
            prefix = '>' if i == highlight_idx else ' '
            line = prefix + _fmt_row_normal(r)
            # 与 Windows 版一致：白字 + 隔行 黑/深灰 背景铺满整行
            pad = width - display_width(line)
            if pad > 0:
                line += ' ' * pad
            bg = _C_BLACK_BG if i % 2 == 0 else _C_DARKGRAY_BG
            print(f'{_C_WHITE}{bg}{line}{_C_RESET}')


def print_quotes(stock_rows, index_rows, show_index, stealth, highlight_idx=-1):
    """打印完整行情页。"""
    now = time.strftime('%H:%M:%S')
    if stealth:
        print(_color(f'System Monitor  |  Last update: {now} (Refresh: {interval}s)', _C_WHITE))
    else:
        print(f"自选股行情 ({len(stock_rows)} 只)    刷新时间: {now} ({interval} 秒自动刷新)")

    if stock_rows:
        print_stocks(stock_rows, stealth, highlight_idx=highlight_idx)

    rows_to_show = []
    if stealth:
        rows_to_show = [r for r in index_rows if r.get(F_NAME) in ('上证指数', '深证成指')]
    elif show_index:
        rows_to_show = index_rows

    if rows_to_show:
        print_index_rows(rows_to_show, stealth)
        market_info = get_market_total_amounts(index_rows)
        print_market_total_row(market_info, stealth)


def print_index_rows(rows, stealth):
    """打印指数行情。"""
    if not rows:
        return
    if stealth:
        width = 64
        print(_color('-' * width, _C_WHITE))
        for r in rows:
            name = truncate_name(r.get(F_NAME, ''))
            price = fmt_num(r.get(F_PRICE))
            change = fmt_num(r.get(F_CHG))
            pct = fmt_num(r.get(F_PCT_CHG))
            right = f'{change} / {pct}%'
            line = pad_right(name, 8) + ' ' + pad_left(price, 10) + ' ' + pad_left(right, 20)
            print(_color(line, _C_WHITE))
        return

    width = 122
    print('-' * width)
    per_row = 5
    sep = ' │ '
    sep_w = display_width(sep)
    boxes = []
    min_box_w = 0
    for r in rows:
        name = truncate_name(r.get(F_NAME, ''))
        price = fmt_num(r.get(F_PRICE))
        change = fmt_num(r.get(F_CHG))
        pct = fmt_num(r.get(F_PCT_CHG))
        right2 = f'{change} / {pct}%'
        boxes.append((name, price, right2))
        min_box_w = max(
            min_box_w,
            display_width(name) + display_width(price),
            display_width(right2),
        )
    box_w = (width - (per_row - 1) * sep_w) // per_row
    if box_w < min_box_w:
        box_w = min_box_w

    def fmt_top(name, price):
        pad = box_w - display_width(name) - display_width(price)
        if pad < 0:
            pad = 0
        return name + ' ' * pad + price

    def fmt_bottom(right2):
        pad = box_w - display_width(right2)
        if pad < 0:
            pad = 0
        return ' ' * pad + right2

    for i in range(0, len(boxes), per_row):
        parts1 = []
        parts2 = []
        for j in range(per_row):
            if i + j >= len(boxes):
                break
            name, price, right2 = boxes[i + j]
            parts1.append(fmt_top(name, price))
            parts2.append(fmt_bottom(right2))
        line1 = sep.join(parts1)
        line2 = sep.join(parts2)
        pad = width - display_width(line1)
        if pad > 0:
            line1 += ' ' * pad
        pad = width - display_width(line2)
        if pad > 0:
            line2 += ' ' * pad
        print(line1)
        print(line2)


def print_market_total_row(info, stealth):
    """打印三市成交总额与量比。"""
    if not info or info.get('total_yi') is None or info.get('ratio') is None:
        return
    width = 64 if stealth else 122
    label = '三市总额/量比 '
    value = f"{info['total_yi']} / {info['ratio']}"
    if stealth:
        # 让斜杠与简化模式指数行的 "change / pct%" 对齐（斜杠前占 32 显示宽度）
        target_slash_pos = 32
        amount_str = str(info['total_yi'])
        spaces_needed = target_slash_pos - display_width(label) - display_width(amount_str)
        if spaces_needed < 0:
            spaces_needed = 0
        line = label + ' ' * spaces_needed + value
        print(_color(pad_right(line, width), _C_WHITE))
    else:
        print(pad_right(label + value, width))


# ── 排序 ────────────────────────────────────────────────────
def _numeric_key(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def apply_sort(rows, sort_state):
    """按当前排序状态对行进行排序，不改变原始顺序。"""
    if sort_state['c'] != 0:
        field = F_PCT_CHG
        reverse = sort_state['c'] == 1
    elif sort_state['v'] != 0:
        field = F_VOL_RATIO
        reverse = sort_state['v'] == 1
    else:
        return rows

    def key(r):
        v = _numeric_key(r.get(field))
        if v is None:
            return float('-inf') if reverse else float('inf')
        return v

    return sorted(rows, key=key, reverse=reverse)
# ── 盘口详情 ────────────────────────────────────────────────
def _fmt_yi(v):
    try:
        return f'{float(v) / 1e8:.2f}'
    except (TypeError, ValueError):
        return '-'


def _fmt_wanyi(v):
    try:
        return f'{float(v) / 1e12:.2f}'
    except (TypeError, ValueError):
        return '-'


def _fmt_latest_vol(v):
    try:
        return f'{abs(int(float(v))):,}'
    except (TypeError, ValueError):
        return '-'


def _row_to_secid(row):
    market = str(row.get(F_MARKET, '0'))
    code = row.get(F_CODE, '')
    return f'{market}.{code}'


def _limit_ratio_for_code(code, name=''):
    """根据股票代码和名称返回涨跌停限制比例（与 Windows 版一致）。"""
    code = str(code)
    name = str(name).upper()
    if 'ST' in name:
        return 0.05
    if code.startswith('688') or code.startswith('300') or code.startswith('301'):
        return 0.20
    if code.startswith('8') or code.startswith('4'):
        return 0.30
    return 0.10


def _left_line(label, value, width=20):
    label = str(label)
    value = str(value)
    label_w = display_width(label)
    value_w = display_width(value)
    label_pad = label + ' ' * max(0, 6 - label_w)
    value_pad = ' ' * max(0, 14 - value_w) + value
    return label_pad + ' ' + value_pad


def _right_line(label, price, vol):
    label = str(label)
    price = str(price)
    vol = str(vol)
    label_pad = label + ' ' * max(0, 4 - display_width(label))
    price_pad = ' ' * max(0, 10 - display_width(price)) + price
    vol_pad = ' ' * max(0, 12 - display_width(vol)) + vol
    return f'{label_pad} {price_pad} {vol_pad}'


def _fmt_depth_title(depth, row):
    """格式化盘口窗口标题行：名称 代码 最新价▲▼ 涨跌额 涨跌幅。"""
    name = depth.get('name') or row.get(F_NAME, '')
    code = depth.get('code') or row.get(F_CODE, '')
    price_digits = 3 if is_etf(row) else 2
    price = fmt_num(depth.get('price') or row.get(F_PRICE), digits=price_digits)
    change = fmt_num(depth.get('change') or row.get(F_CHG), digits=price_digits)
    pct = fmt_num(depth.get('pct_chg') or row.get(F_PCT_CHG))
    try:
        c = float(depth.get('change') if depth.get('change') is not None else row.get(F_CHG))
        if c > 0:
            arrow = '▲'
            header_color = _C_RED
        elif c < 0:
            arrow = '▼'
            header_color = _C_GREEN
        else:
            arrow = '─'
            header_color = _C_WHITE
    except (TypeError, ValueError):
        arrow = '─'
        header_color = _C_WHITE
    name_pad = pad_right(name, 8)
    code_pad = pad_right(code, 6)
    price_part = price + ' ' + arrow
    price_part_padded = price_part + ' ' * (12 - display_width(price_part))
    change_pad = change + ' ' * (9 - display_width(change))
    pct_part = pct + '%'
    title = f'{name_pad}    {code_pad}        {price_part_padded}{change_pad}{pct_part}'
    return _color(title, header_color)


def print_depth(depth, row, stealth=False):
    """打印单只股票盘口详情窗口（与 Windows 版字段/顺序一致）。"""
    if not depth:
        print('盘口数据获取失败')
        return

    print(_fmt_depth_title(depth, row))

    price_digits = 3 if is_etf(row) else 2
    price = fmt_num(depth.get('price'), digits=price_digits)
    prev_close = fmt_num(depth.get('prev_close'), digits=price_digits)
    open_price = fmt_num(depth.get('open'), digits=price_digits)
    high = fmt_num(depth.get('high'), digits=price_digits)
    low = fmt_num(depth.get('low'), digits=price_digits)

    # 涨停跌停按 Windows 版规则手动计算（ETF 不显示）
    name = depth.get('name') or row.get(F_NAME, '')
    code = depth.get('code') or row.get(F_CODE, '')
    is_etf_flag = 'ETF' in str(name).upper()
    limit_up = '-'
    limit_down = '-'
    if (not is_etf_flag and depth.get('prev_close') is not None
            and depth.get('prev_close') != 0):
        ratio = _limit_ratio_for_code(code, name)
        try:
            limit_up = fmt_num(round(depth['prev_close'] * (1 + ratio), 2), digits=price_digits)
            limit_down = fmt_num(round(depth['prev_close'] * (1 - ratio), 2), digits=price_digits)
        except Exception:
            pass

    turnover = fmt_num(row.get(F_TURNOVER))
    vol_ratio = fmt_num(row.get(F_VOL_RATIO))
    amount = _fmt_yi(row.get(F_AMT))
    total_cap = _fmt_wanyi(row.get(F_TOTAL_CAP))
    float_cap = _fmt_yi(row.get(F_FLOAT_CAP))
    latest_vol = _fmt_latest_vol(row.get(F_LATEST_VOL))

    main_sep = '-' * 53
    right_sep = '-' * 28
    print(main_sep)

    left_lines = [
        _left_line('最新', price),
        _left_line('现手', latest_vol),
        _left_line('昨收', prev_close),
        _left_line('今开', open_price),
        _left_line('最高', high),
        _left_line('最低', low),
        _left_line('涨停', limit_up),
        _left_line('跌停', limit_down),
        _left_line('换手', turnover + '%'),
        _left_line('成交', amount + '亿'),
        _left_line('量比', vol_ratio),
    ]

    asks = depth.get('asks', [])
    bids = depth.get('bids', [])
    right_lines = []
    for i in range(5, 0, -1):
        p, v = asks[5 - i] if len(asks) >= i else (None, None)
        right_lines.append(_right_line(f'卖{i}', fmt_num(p, digits=price_digits), fmt_num(v, digits=0)))
    right_lines.append(right_sep)
    for i in range(1, 6):
        p, v = bids[i - 1] if len(bids) >= i else (None, None)
        right_lines.append(_right_line(f'买{i}', fmt_num(p, digits=price_digits), fmt_num(v, digits=0)))

    for i in range(len(left_lines)):
        left = left_lines[i]
        right = right_lines[i] if i < len(right_lines) else ''
        print(f'{left}    {right}')

    print(main_sep)
    cap_line = (
        _left_line('市值', total_cap + '万亿') + '        ' +
        _left_line('流通', float_cap + '亿')
    )
    print(cap_line)
    print()
    if stealth:
        print(_color('[R refresh  ↑↓ switch  ← back]', _C_WHITE))
    else:
        print('[R 刷新  ↑↓ 切换  ← 返回]')


# ── Boss 模式 ───────────────────────────────────────────────
def show_boss_screen():
    """显示伪装 npm 构建日志。"""
    t = time.strftime('%H:%M:%S')
    print(_color('> npm run build', _C_GRAY))
    print()
    print(_color('> project@1.0.0 build D:\\project', _C_GRAY))
    print(_color('> tsc && vite build', _C_GRAY))
    print()
    print(_color('vite v5.0.0 building for production...', _C_GRAY))
    print(_color('✓ 128 modules transformed.', _C_GRAY))
    print(_color('dist/index.html                   0.45 kB', _C_GRAY))
    print(_color('dist/assets/index-a1b2c3d4.js   142.31 kB', _C_GRAY))
    print(_color('✓ built in 3.42s', _C_GRAY))
    print()
    print(_color(f'[{t}] Watching for changes...', _C_GRAY))


# ── 按键轮询 ────────────────────────────────────────────────
def wait_for_key_or_timeout(interval):
    """轮询等待按键，返回按键字符串或 None。"""
    elapsed = 0.0
    step = 0.05
    while elapsed < interval:
        key = get_key(timeout=step)
        if key is not None:
            return key
        time.sleep(step)
        elapsed += step
    return None


# ── 按钮栏（文本提示） ─────────────────────────────────────
def show_button_bar(stealth, depth_mode=False):
    """在屏幕底部显示可用按键提示。"""
    if depth_mode:
        buttons = [
            ('R', 'R refresh', 'R 刷新'),
            ('↑↓', '↑↓ switch', '↑↓ 切换'),
            ('←', '← back', '← 返回'),
        ]
    else:
        buttons = [
            ('R', 'R refresh', 'R 刷新'),
            ('C', 'C sort%', 'C 涨跌幅排序'),
            ('V', 'V sortVR', 'V 量比排序'),
            ('B', 'B hide', 'B 伪装'),
            ('S', 'S mode', 'S 切换'),
            ('Esc', 'Esc exit', 'Esc 退出'),
        ]
    parts = []
    for key, stealth_label, normal_label in buttons:
        label = stealth_label if stealth else normal_label
        parts.append(f'[{label}]')
    bar = ' '.join(parts)
    if stealth:
        print(_color(bar, _C_WHITE))
    else:
        print(bar)


# ── 主程序 ──────────────────────────────────────────────────
def parse_args(argv):
    """解析命令行参数，返回 (interval, show_index, stealth, fetch_hy, once)。"""
    interval = 15
    show_index = False
    stealth = True
    fetch_hy = False
    once = False
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ('--index', '-index'):
            i += 1
            if i < len(argv) and argv[i].lower() in ('on', 'true', '1'):
                show_index = True
            else:
                show_index = False
        elif arg in ('--stealth', '-stealth'):
            i += 1
            if i < len(argv) and argv[i].lower() in ('off', 'false', '0'):
                stealth = False
            else:
                stealth = True
        elif arg in ('--hy', '-hy'):
            i += 1
            if i < len(argv) and argv[i].lower() in ('on', 'true', '1'):
                fetch_hy = True
            else:
                fetch_hy = False
        elif arg == '--once':
            once = True
        elif arg in ('--help', '-h'):
            print_help()
            sys.exit(0)
        else:
            try:
                parsed = int(arg)
                if parsed > 0:
                    interval = parsed
            except ValueError:
                pass
        i += 1
    return interval, show_index, stealth, fetch_hy, once


def print_help(script_name='watch_quotes.py'):
    print(f'用法: python {script_name} [刷新秒数] [--index on|off] [--stealth on|off] [--hy on|off] [--once] [-h]')
    print()
    print('参数:')
    print('  刷新秒数          自动刷新间隔，默认 15 秒')
    print('  --index on|off    是否显示指数方块，默认 off（详情模式）')
    print('  --stealth on|off  简化模式（灰白英文、低调标题），默认 on')
    print('  --hy on|off       启动时获取并缓存半年涨跌，默认 off')
    print('  --once            只取一次数据后退出')
    print('  -h, --help        显示此帮助信息')
    print()
    print('列表页快捷键:')
    print('  Esc        退出程序')
    print('  R          立即刷新行情')
    print('  C          按涨跌幅排序（高→低→低→高→原样）')
    print('  V          按量比排序（高→低→低→高→原样）')
    print('  S          切换简化模式 / 详情模式')
    print('  B / F9     切换 npm 构建日志外观 / 正常行情')
    print('  ↑ / ↓      移动光标选择股票')
    print('  →          进入选中股票的盘口详情')
    print()
    print('盘口详情页快捷键:')
    print('  R          刷新盘口')
    print('  ↑ / ↓      切换到上一只 / 下一只自选股盘口')
    print('  ← / Esc    返回列表')
    print('  Ctrl+C     强制退出')


def main():
    global interval
    interval, show_index, stealth, fetch_hy, once = parse_args(sys.argv)

    if once:
        stock_rows, index_rows, err = get_quotes(fetch_hy=fetch_hy)
        if err:
            print(err)
            sys.exit(1)
        apply_half_year_pct(stock_rows)
        print_quotes(stock_rows, index_rows, show_index, stealth)
        return

    # 交互模式
    _set_title('System' if stealth else '行情监控')
    stock_rows = []
    index_rows = []
    sort_state = {'c': 0, 'v': 0}
    selected_idx = 0
    in_depth = False
    current_depth = None
    current_depth_row = None
    depth_stock_rows = None
    depth_stock_index = None
    boss_mode = False
    next_hy_update = time.time()

    def refresh_list():
        nonlocal stock_rows, index_rows
        s_rows, i_rows, err = get_quotes(fetch_hy=fetch_hy)
        if err:
            return False, err
        stock_rows = s_rows or []
        index_rows = i_rows or []
        apply_half_year_pct(stock_rows)
        return True, None

    def refresh_depth():
        nonlocal current_depth
        if current_depth_row is None:
            return False, '未选择股票'
        secid = _row_to_secid(current_depth_row)
        current_depth = fetch_depth_data(secid, retries=2)
        if current_depth is None:
            return False, '盘口数据获取失败'
        return True, None

    def schedule_hy_update():
        nonlocal next_hy_update
        if not fetch_hy:
            return
        complete_half_year_update()
        now = time.time()
        if now >= next_hy_update:
            secids = [f"{r.get(F_MARKET, '0')}.{r.get(F_CODE, '')}" for r in stock_rows]
            start_half_year_update(secids)
            next_hy_update = now + interval * 4

    clear_screen()
    try:
        hide_cursor()
        enter_raw_mode()
        ok, err = refresh_list()
        if not ok:
            print(err)
            return

        while True:
            if boss_mode:
                clear_screen()
                show_boss_screen()
            else:
                clear_screen()
                display_rows = apply_sort(stock_rows, sort_state)
                if in_depth:
                    print_depth(current_depth, current_depth_row, stealth=stealth)
                else:
                    if selected_idx >= len(display_rows):
                        selected_idx = max(0, len(display_rows) - 1)
                    print_quotes(display_rows, index_rows, show_index, stealth, highlight_idx=selected_idx)

                if not in_depth:
                    print()
                    show_button_bar(stealth, depth_mode=False)
                else:
                    # 盘口页底部提示已在 print_depth 中输出
                    pass

            schedule_hy_update()

            key = wait_for_key_or_timeout(interval)

            if key is None:
                # 超时自动刷新
                if boss_mode:
                    continue
                if in_depth:
                    refresh_depth()
                else:
                    ok, err = refresh_list()
                    if not ok:
                        clear_screen()
                        print(err)
                continue

            # ── 按键处理 ──
            if key == 'ESC':
                if in_depth:
                    in_depth = False
                    current_depth = None
                    current_depth_row = None
                    depth_stock_rows = None
                    depth_stock_index = None
                elif boss_mode:
                    boss_mode = False
                else:
                    break

            elif key == 'CTRL_C':
                break

            elif key in ('r', 'R'):
                if boss_mode:
                    continue
                if in_depth:
                    refresh_depth()
                else:
                    ok, err = refresh_list()
                    if not ok:
                        clear_screen()
                        print(err)
                        time.sleep(1)
                continue

            elif key in ('b', 'B', 'F9'):
                boss_mode = not boss_mode
                continue

            elif key in ('s', 'S'):
                if boss_mode or in_depth:
                    continue
                stealth = not stealth
                show_index = not show_index
                _set_title('System' if stealth else '行情监控')
                clear_screen()
                continue

            elif key in ('c', 'C'):
                if boss_mode or in_depth:
                    continue
                sort_state['c'] = (sort_state['c'] + 1) % 3
                sort_state['v'] = 0
                continue

            elif key in ('v', 'V'):
                if boss_mode or in_depth:
                    continue
                sort_state['v'] = (sort_state['v'] + 1) % 3
                sort_state['c'] = 0
                continue

            elif key == 'RIGHT':
                if boss_mode or in_depth:
                    continue
                display_rows = apply_sort(stock_rows, sort_state)
                if 0 <= selected_idx < len(display_rows):
                    current_depth_row = display_rows[selected_idx]
                    depth_stock_rows = display_rows
                    depth_stock_index = selected_idx
                    ok, err = refresh_depth()
                    if ok:
                        in_depth = True
                    else:
                        clear_screen()
                        print(err)
                        time.sleep(1)

            elif key == 'LEFT':
                if boss_mode:
                    continue
                if in_depth:
                    in_depth = False
                    current_depth = None
                    current_depth_row = None
                    depth_stock_rows = None
                    depth_stock_index = None

            elif key == 'UP':
                if boss_mode:
                    continue
                if in_depth:
                    if depth_stock_rows and depth_stock_index is not None:
                        depth_stock_index = (depth_stock_index - 1 + len(depth_stock_rows)) % len(depth_stock_rows)
                        current_depth_row = depth_stock_rows[depth_stock_index]
                        refresh_depth()
                else:
                    if stock_rows:
                        selected_idx = (selected_idx - 1 + len(apply_sort(stock_rows, sort_state))) % len(apply_sort(stock_rows, sort_state))

            elif key == 'DOWN':
                if boss_mode:
                    continue
                if in_depth:
                    if depth_stock_rows and depth_stock_index is not None:
                        depth_stock_index = (depth_stock_index + 1) % len(depth_stock_rows)
                        current_depth_row = depth_stock_rows[depth_stock_index]
                        refresh_depth()
                else:
                    if stock_rows:
                        selected_idx = (selected_idx + 1) % len(apply_sort(stock_rows, sort_state))

    except KeyboardInterrupt:
        pass
    finally:
        show_cursor()
        restore_terminal()
        _set_title('')
        clear_screen()
        print('已退出')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
