"""
股票行情监视器（Python 版）
用法:
  python watch_quotes.py [刷新秒数] [--index on|off] [--once] [-h]

快捷键:
  ↑/↓    移动光标选择股票
  Enter  查看选中股票的盘口详情
  R      立即刷新
  C      按涨跌幅排序（第一次高到低，第二次低到高，第三次恢复）
  V      按量比排序（第一次高到低，第二次低到高，第三次恢复）
  Esc    退出或返回
  Ctrl+C 强制退出
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
    fmt_num, fmt_open_price, display_width, pad_center, pad_left, pad_right,
    print_indices, get_market_total_amounts, print_market_total, fetch_depth_data,
)


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def get_quotes():
    wl_path = os.path.join(BASE_DIR, 'watchlist.json')
    with open(wl_path, 'r', encoding='utf-8') as f:
        wl = json.load(f)
    stocks = wl.get('stocks', [])
    indices = wl.get('indices', [])

    stock_secids = search_secids(stocks)
    index_secids = search_secids(indices)

    if not stock_secids and not index_secids:
        return None, None, None, '没有可查询的股票或指数'

    stock_rows = fetch_quote_rows(stock_secids)
    index_rows = fetch_quote_rows(index_secids)
    return stock_rows, index_rows, None, None


def _fmt_row(r):
    """格式化单个股票行为字符串。"""
    code = r.get(F_CODE, '')
    name = truncate_name(r.get(F_NAME, ''))
    market = '深A' if str(r.get(F_MARKET, '')) == '0' else '沪A'
    price_digits = 3 if is_etf(r) else 2
    price = fmt_num(r.get(F_PRICE), digits=price_digits)
    prev_close = fmt_num(r.get(F_PREV_CLOSE), digits=price_digits)
    open_price, open_arrow = fmt_open_price(
        r.get(F_OPEN), r.get(F_PREV_CLOSE), digits=price_digits
    )
    high = fmt_num(r.get(F_HIGH), digits=price_digits)
    low = fmt_num(r.get(F_LOW), digits=price_digits)
    change = fmt_num(r.get(F_CHG), digits=price_digits)
    pct = fmt_num(r.get(F_PCT_CHG))
    turnover = fmt_num(r.get(F_TURNOVER))
    vr = fmt_num(r.get(F_VOL_RATIO))
    vol = fmt_num(r.get(F_VOL), digits=0)
    amt = fmt_num(r.get(F_AMT), divisor=100000000)
    return (
        f"{name:<10} {code:<8} {market:<5} {price:>8} {prev_close:>8} "
        f"{open_price:>8}{open_arrow} {high:>8} {low:>8} {change:>9} "
        f"{pct:>8}% {turnover:>8} {vr:>8} {vol:>12} {amt:>9}"
    )


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


def sort_hint(sort_state):
    """返回当前排序状态提示文本。"""
    parts = []
    if sort_state['c'] == 1:
        parts.append('C=涨跌幅↓')
    elif sort_state['c'] == 2:
        parts.append('C=涨跌幅↑')
    if sort_state['v'] == 1:
        parts.append('V=量比↓')
    elif sort_state['v'] == 2:
        parts.append('V=量比↑')
    return ' '.join(parts)


def print_stocks(rows, highlight_idx=-1):
    """打印自选股列表，支持光标高亮。"""
    header = (
        f"{'名称':<10} {'代码':<8} {'市场':<5} {'最新':>8} {'昨收':>8} {'今开':>9} "
        f"{'最高':>8} {'最低':>8} {'涨跌额':>9} {'涨跌幅':>8} {'换手%':>8} {'量比':>8} "
        f"{'成交量(手)':>12} {'成交亿':>9}"
    )
    print(header)
    print('-' * 132)
    for i, r in enumerate(rows):
        prefix = '> ' if i == highlight_idx else '  '
        print(prefix + _fmt_row(r))


def print_quotes(stock_rows, index_rows, show_index=True, highlight_idx=-1):
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"自选股行情 ({len(stock_rows)} 只)    刷新时间: {now}")
    if stock_rows:
        print_stocks(stock_rows, highlight_idx=highlight_idx)
    if show_index and index_rows:
        print_indices(index_rows)
        market_info = get_market_total_amounts(index_rows)
        print_market_total(market_info)


def _fmt_yi(v):
    """把金额格式化为 亿，返回纯数值（单位在标签中）。"""
    try:
        return f"{float(v)/1e8:.2f}"
    except (TypeError, ValueError):
        return '-'


def _fmt_wanyi(v):
    """把市值格式化为 万亿，返回纯数值（单位在标签中）。"""
    try:
        return f"{float(v)/1e12:.2f}"
    except (TypeError, ValueError):
        return '-'


def _fmt_depth_price(v, digits=2):
    return fmt_num(v, digits=digits)


def _fmt_depth_vol(v):
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return '-'


def _fmt_latest_vol(v):
    try:
        return f"{abs(int(float(v))):,}"
    except (TypeError, ValueError):
        return '-'


def _row_to_secid(row):
    """把行情行转换为东方财富 secid。"""
    market = str(row.get(F_MARKET, '0'))
    code = row.get(F_CODE, '')
    return f"{market}.{code}"


def _left_line(label, value, width=20):
    """左侧信息行：标签左对齐、数值右对齐，总显示宽度固定。"""
    label = str(label)
    value = str(value)
    label_w = display_width(label)
    value_w = display_width(value)
    # 标签占 6 显示宽度（3 个汉字），数值占 14 显示宽度
    label_pad = label + ' ' * max(0, 6 - label_w)
    value_pad = ' ' * max(0, 14 - value_w) + value
    return label_pad + ' ' + value_pad


def _right_line(label, price, vol):
    """右侧盘口行：档位左对齐，价格和数量右对齐。"""
    label = str(label)
    price = str(price)
    vol = str(vol)
    label_pad = label + ' ' * max(0, 4 - display_width(label))
    price_pad = ' ' * max(0, 10 - display_width(price)) + price
    vol_pad = ' ' * max(0, 12 - display_width(vol)) + vol
    return f"{label_pad} {price_pad} {vol_pad}"


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
        arrow = '▲' if c > 0 else '▼' if c < 0 else '─'
    except (TypeError, ValueError):
        arrow = '─'
    name_pad = pad_right(name, 8)
    code_pad = pad_right(code, 6)
    price_part = price + ' ' + arrow
    price_part_padded = price_part + ' ' * (12 - display_width(price_part))
    change_pad = change + ' ' * (9 - display_width(change))
    pct_part = pct + '%'
    return f"{name_pad}    {code_pad}        {price_part_padded}{change_pad}{pct_part}"


def print_depth(depth, row):
    """打印单只股票盘口详情窗口。"""
    if not depth:
        print("盘口数据获取失败")
        return

    print(_fmt_depth_title(depth, row))

    price_digits = 3 if is_etf(row) else 2
    price = fmt_num(depth.get('price'), digits=price_digits)
    prev_close = fmt_num(depth.get('prev_close'), digits=price_digits)
    open_price = fmt_num(depth.get('open'), digits=price_digits)
    high = fmt_num(depth.get('high'), digits=price_digits)
    low = fmt_num(depth.get('low'), digits=price_digits)
    limit_up = fmt_num(depth.get('limit_up'), digits=price_digits)
    limit_down = fmt_num(depth.get('limit_down'), digits=price_digits)

    turnover = fmt_num(row.get(F_TURNOVER))
    vol_ratio = fmt_num(row.get(F_VOL_RATIO))
    amount = _fmt_yi(row.get(F_AMT))
    total_cap = _fmt_wanyi(row.get(F_TOTAL_CAP))
    float_cap = _fmt_yi(row.get(F_FLOAT_CAP))
    latest_vol = _fmt_latest_vol(row.get(F_LATEST_VOL))

    main_sep = '-' * 53
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
        price, vol = asks[5 - i] if len(asks) >= i else (None, None)
        right_lines.append(
            _right_line(f"卖{i}", _fmt_depth_price(price), _fmt_depth_vol(vol))
        )
    right_lines.append('-' * 28)
    for i in range(1, 6):
        price, vol = bids[i - 1] if len(bids) >= i else (None, None)
        right_lines.append(
            _right_line(f"买{i}", _fmt_depth_price(price), _fmt_depth_vol(vol))
        )

    for i in range(len(left_lines)):
        left = left_lines[i]
        right = right_lines[i] if i < len(right_lines) else ''
        print(f"{left}    {right}")

    print(main_sep)
    print(_left_line('市值', total_cap + '万亿') + '        ' + _left_line('流通', float_cap + '亿'))
    print()
    print("[Enter/Esc 返回  R 刷新]")


def wait_for_key_or_timeout(interval):
    """轮询等待 interval 秒或直到有按键，返回按键字符串或 None。

    以 0.1 秒为粒度轮询，既保证响应速度又不过分消耗 CPU。
    """
    elapsed = 0.0
    step = 0.1
    while elapsed < interval:
        key = get_key()
        if key is not None:
            return key
        time.sleep(step)
        elapsed += step
    return None


def main():
    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()
        return

    interval = 3
    show_index = True
    once = False
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ('--index', '-index'):
            i += 1
            if i < len(sys.argv) and sys.argv[i].lower() in ('on', 'true', '1'):
                show_index = True
            else:
                show_index = False
        elif arg == '--once':
            once = True
        else:
            try:
                parsed = int(arg)
                if parsed > 0:
                    interval = parsed
            except ValueError:
                pass
        i += 1

    if once:
        stock_rows, index_rows, err, _ = get_quotes()
        if err:
            print(err)
            sys.exit(1)
        print_quotes(stock_rows, index_rows, show_index)
        return

    # ── 交互模式 ──
    stock_rows = []
    index_rows = []
    sort_state = {'c': 0, 'v': 0}  # 0=原样, 1=从高到低, 2=从低到高
    selected_idx = 0
    in_depth = False
    current_depth = None
    current_depth_row = None

    def refresh_list():
        nonlocal stock_rows, index_rows
        s_rows, i_rows, err, _ = get_quotes()
        if err:
            return False, err
        stock_rows = s_rows or []
        index_rows = i_rows or []
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

    clear_screen()
    try:
        # 首次加载
        ok, err = refresh_list()
        if not ok:
            print(err)
            return

        while True:
            clear_screen()
            display_rows = apply_sort(stock_rows, sort_state)

            if in_depth:
                print_depth(current_depth, current_depth_row)
            else:
                if selected_idx >= len(display_rows):
                    selected_idx = max(0, len(display_rows) - 1)
                print_quotes(display_rows, index_rows, show_index, highlight_idx=selected_idx)
                hint = sort_hint(sort_state)
                print(f"\n[↑↓ 选择  Enter 盘口  R 刷新  C 涨跌幅  V 量比  Esc 退出] {hint}")

            # 等待按键或超时
            key = wait_for_key_or_timeout(interval)

            if key is None:
                # 超时：自动刷新
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
                else:
                    break

            elif key in ('r', 'R'):
                if in_depth:
                    refresh_depth()
                else:
                    ok, err = refresh_list()
                continue

            elif key == 'ENTER':
                if not in_depth and 0 <= selected_idx < len(display_rows):
                    current_depth_row = display_rows[selected_idx]
                    ok, err = refresh_depth()
                    if ok:
                        in_depth = True
                    else:
                        clear_screen()
                        print(err)
                        time.sleep(1)
                continue

            elif key == 'UP':
                if not in_depth and selected_idx > 0:
                    selected_idx -= 1

            elif key == 'DOWN':
                if not in_depth and selected_idx < len(display_rows) - 1:
                    selected_idx += 1

            elif key in ('c', 'C'):
                if not in_depth:
                    sort_state['c'] = (sort_state['c'] + 1) % 3
                    sort_state['v'] = 0

            elif key in ('v', 'V'):
                if not in_depth:
                    sort_state['v'] = (sort_state['v'] + 1) % 3
                    sort_state['c'] = 0

    except KeyboardInterrupt:
        pass
    finally:
        clear_screen()
        print("已退出")


def print_help(script_name='watch_quotes.py'):
    print(f"用法: python {script_name} [刷新秒数] [--index on|off] [--once] [-h]")
    print()
    print("参数:")
    print("  刷新秒数          自动刷新间隔，默认 3 秒")
    print("  --index on|off    是否显示指数方块，默认 on")
    print("  --once            只取一次数据后退出")
    print("  -h, --help        显示此帮助信息")
    print()
    print("快捷键:")
    print("  ↑/↓    移动光标选择股票")
    print("  Enter  查看选中股票的盘口详情")
    print("  R      立即刷新数据")
    print("  C      按涨跌幅排序（第一次高到低，第二次低到高，第三次恢复）")
    print("  V      按量比排序（第一次高到低，第二次低到高，第三次恢复）")
    print("  Esc    退出程序或返回上一层")
    print("  Ctrl+C 强制退出")


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
