股票行情监视器 - 办公隐蔽版（跨平台）
==============================

一份代码同时支持 Windows / macOS / Linux，仅依赖 Python 标准库。

环境要求
--------
- Python 3.8+
  （Windows：python 命令或 py 启动器；macOS / Linux：python3）
- 能访问东方财富 API 的网络环境

使用方法
--------
Windows:
  1. 双击 watch.cmd，默认 15 秒刷新，隐蔽模式
  2. 或命令行运行：watch.cmd [刷新秒数] [参数]

macOS / Linux:
  1. 终端运行 ./watch.sh，默认 15 秒刷新，隐蔽模式
  2. 或：python3 watch_quotes.py [刷新秒数] [参数]

常用命令
--------
示例以 macOS / Linux 的 ./watch.sh 为例；Windows 换成 watch.cmd，参数完全相同：

  ./watch.sh                   隐蔽模式，15秒刷新（办公推荐）
  ./watch.sh 30                隐蔽模式，30秒刷新
  ./watch.sh --once            取一次数据后退出
  ./watch.sh --stealth off --index on
                               恢复中文红绿 + 指数方块（在家用）

快捷键（两平台一致）
------------------
  Esc          退出
  B / F9       老板键：切换伪装 npm 构建日志 / 正常行情
               （macOS 上 F9 取决于终端是否映射功能键，不可用请用 B）
  S            切换办公模式（灰白隐蔽）/ 家庭模式（中文红绿 + 交替背景）
  Ctrl+C       退出（备用）

参数说明
--------
  --index on|off     是否显示指数方块，默认 off
                     （办公模式会固定显示上证指数、深证成指）
  --stealth on|off   隐蔽模式（灰白文字、伪装窗口标题），默认 on
  --hy on|off        启动时获取半年涨跌，默认 off
  --once             只取一次数据后退出

平台差异（有意保留）
------------------
- 伪装屏项目路径：Windows 显示 D:\project，macOS / Linux 显示 ~/project
- 退出后窗口标题：Windows 恢复为 Command Prompt，macOS / Linux 恢复为终端默认
- 其余显示、参数、快捷键行为两平台一致

文件说明
--------
  watch.cmd            Windows 启动器（自动选用 python / py 启动器）
  watch.sh             macOS / Linux 启动器
  watch_quotes.py      主程序（Python，跨平台）
  watchlist.json       自选股配置
  .secids_cache.json   股票代码缓存（删除后会重新搜索）

watchlist.json 配置
-------------------
stocks / indices 支持：中文名称（如 "鼎龙股份"）、6 位 A 股代码（如 "000001"）、
带市场前缀（如 "sh600000"、"sz000001"、"hk00700"）、secid 格式（如 "0.300054"）。

注意事项
--------
- 办公模式默认灰白英文显示，窗口标题为 System
- 按 B（或 F9）键立即伪装成 npm 构建日志，再按恢复
- 修改 watchlist.json 可增删股票和指数
- 证书校验失败会自动尝试系统 CA 证书；接口被拦截时回退到系统 curl 及延迟行情镜像
- 行情数据来自东方财富公开 API，仅供个人看盘参考，不构成投资建议
