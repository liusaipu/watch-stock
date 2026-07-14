# watch-stock

一个基于东方财富免费 API 的终端自选股行情看盘工具，支持 macOS 与 Windows，零第三方依赖。

## 功能特点

- **纯 Python 实现**：跨平台运行，无需 PowerShell/Batch。
- **实时刷新**：定时清屏刷新行情，按 `Ctrl+C` 退出。
- **自选股配置**：通过 `watchlist.json` 用中文名或股票代码配置股票与指数。
- **行情数据**：最新价、最高价、最低价、涨跌额、涨跌幅、换手率、量比、成交量、成交额、半年涨跌。
- **指数方块**：以方块形式展示主要指数，根据终端宽度自动排列。
- **颜色提示**：涨红跌绿白平，符合 A 股习惯（Windows 10+ / Windows Terminal / macOS 终端均支持）。
- **本地缓存**：首次搜索后自动保存名称与 secid 的映射到 `.watchlist_cache.json`，避免每次启动都调用搜索接口。
- **错误降级**：网络异常时保留上一次数据并提示，不会直接退出。

## 环境要求

- Python 3.8+
- 能访问东方财富 API 的网络环境

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/liusaipu/watch-stock.git
cd watch-stock

# 单次查询
python get_watchlist_quotes.py

# 实时刷新（默认 3 秒）
python watch_quotes.py

# 自定义刷新间隔 5 秒，不显示指数方块
python watch_quotes.py 5 --index off
```

在 macOS / Linux 上，由于脚本已添加 shebang 并标记为可执行，也可以直接运行：

```bash
./get_watchlist_quotes.py
./watch_quotes.py 3 --index on
```

## 配置自选股

编辑 `watchlist.json`：

```json
{
  "description": "用户自选股列表",
  "stocks": [
    "鼎龙股份",
    "苏试试验",
    "麦捷科技",
    "000001",
    "sz000001",
    "sh600000",
    "hk00700"
  ],
  "indices": [
    "上证指数",
    "深证成指",
    "创业板指",
    "科创50"
  ]
}
```

`stocks` 和 `indices` 支持以下写法：

| 写法 | 示例 | 说明 |
|------|------|------|
| 中文名称 | `"鼎龙股份"` | 通过东方财富 suggest API 搜索 |
| 6 位 A 股代码 | `"000001"` | 自动判断深 A / 沪 A |
| 带市场前缀 | `"sz000001"`、`"sh600000"`、`"hk00700"` | 明确指定市场 |
| secid 格式 | `"0.300054"`、`"1.600000"` | 东方财富内部格式 |

## 命令行参数

### `get_watchlist_quotes.py`

```text
用法: python get_watchlist_quotes.py [--index on|off]

参数:
  --index on|off    是否显示指数方块，默认 on
  -h, --help        显示此帮助信息
```

### `watch_quotes.py`

```text
用法: python watch_quotes.py [刷新秒数] [--index on|off]

参数:
  刷新秒数          自动刷新间隔，默认 3 秒
  --index on|off    是否显示指数方块，默认 on
  -h, --help        显示此帮助信息
```

## 项目结构

```text
watch-stock/
├── quotes_core.py           # 公共模块（网络、格式化、打印、缓存）
├── get_watchlist_quotes.py  # 单次查询入口
├── watch_quotes.py          # 定时刷新入口
├── watchlist.json           # 自选股与指数配置
├── .gitignore               # Git 忽略规则
└── README.md                # 本文件
```

## 注意事项

1. **数据来源**：行情数据来自东方财富公开 API，仅供个人看盘参考，不构成投资建议。
2. **网络要求**：部分网络环境（如海外 IP）可能无法稳定访问东方财富接口。
3. **证书问题**：在 macOS 上若遇到 SSL 证书错误，脚本会自动降级为不验证证书重试一次。
4. **缓存文件**：`.watchlist_cache.json` 为运行时生成，不会被提交到 Git。

## 开源协议

MIT
