# Pythia

[English](../../README.md) · [Deutsch](README.de.md) · 简体中文 · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · [Português](README.pt-BR.md)

Pythia 是一个从模拟盘起步的交易驾驶舱，在策略证明自己之前一直停留在模拟盘。它由 Rust 引擎、基于引擎的桌面应用和网页界面，以及一个用 Python 编写的研究实验室组成，实验室决定引擎可以交易什么。实验室记录了它尝试过的每一个想法，因此一次幸运的回测不会蒙混过关。

这里没有任何策略被证明能够盈利。连接真实账户之前，请先阅读 [SAFETY.md](../../SAFETY.md)（英文）。

<table>
  <tr>
    <td width="50%"><img src="../img/app-home.png" alt="主页"></td>
    <td width="50%"><img src="../img/app-autopilot.png" alt="自动驾驶"></td>
  </tr>
</table>

截图来自使用示例数据的开发版本。

## 下载

[最新版本](https://github.com/SenseiIssei/Pythia/releases/latest)中包含：

| 平台 | 文件 |
|---|---|
| Windows | `Pythia_<version>_x64-setup.exe` |
| macOS（Apple 芯片和 Intel） | `Pythia_<version>_universal.dmg` |
| Linux | `.AppImage`、`.deb` 或 `.rpm` |
| 命令行 | `pythia-cli-<version>-<platform>`：`pythia` 和无界面引擎 `pythia-server`，见 [cli/README.md](../../cli/README.md)（英文） |

这些构建尚未签名。Windows 会提示一次（点击“更多信息”，再点“仍要运行”）；在 macOS 上首次打开时，请右键点击应用并选择“打开”。

## 功能

- 自动驾驶（autopilot）是一笔资金，它独立执行一个策略，直到你停止它或止损规则触发。多个自动驾驶可以并行运行，每个都以 BTC 为基准衡量。
- 加密货币、美股和 ETF 在 Alpaca 模拟账户上交易。多空组合在模拟盘上交易永续合约；如果你填入演示密钥，也可以在 Bybit 演示账户上交易。
- 每笔订单之前都有风险管理器：紧急停止、每日亏损和回撤上限、敞口上限、波动率目标。遇到不明确的情况，它会拒绝下单。
- 实验室中的每项研究在首次运行前就登记方案，在扣除成本后进行样本外检验，并按迄今为止的试验总数对夏普比率进行折减（deflated Sharpe）。
- 模型（波动率、币种排名、收益分位数）在实验室训练，由引擎执行。它们先在影子模式下运行，之后才能影响交易。
- 提醒通过 Telegram 或任意 webhook 发送，支持英文和德文。

## 架构

<img src="../img/architecture.svg" alt="Pythia：顶部是界面，其下是 Rust 引擎，再下是实验室和数据记录器，底部是市场" width="100%">

实验室的组合只有附带证据时才会交给自动驾驶。自动选择按证据和实盘前向记录对组合排序，实验性组合只在自动驾驶明确点名时才会运行。

## 目前的结果

所有数字都来自实验室的结果文件或引擎自身的记录。[`scripts/readme_charts.py`](../../scripts/readme_charts.py) 绘制了下面的每张图表，并注明数据来源。

<img src="../img/scoreboard.png" alt="已测试策略的样本外夏普比率" width="100%">

表现最好的组合是在流动性最高的十个币种上做唐奇安通道突破：自 2024 年以来夏普比率为 1.17，而持有 BTC 为 0.74。但它仍未通过折减检验。已计入 1,836 次试验，同样数量的纯噪声策略中最好的一个大约会显示 2.69。

两项永续合约多空研究通过了预先登记的检验（M4 残差和资金费率套利）。两者都没有通过折减检验，因此只作为实验运行。大多数动量组合其实是 BTC 200 日均线过滤器的变体：在过滤器关闭的日子里，它们全都亏损。

<img src="../img/forward.png" alt="自 2026 年 10 月 15 日起模拟自动驾驶的前向记录" width="100%">

模拟自动驾驶于 2026 年 10 月 15 日开始运行。六天后，主自动选择上涨 0.48 %，BTC 上涨 3.22 %。时间太短，说明不了任何问题；放出这张图是为了让记录从第一天起就公开。

<img src="../img/research_funnel.png" alt="试验总数的增长和每项研究的结论" width="100%">

目前共 69 项研究：43 项失败或中止，7 项作为标注的实验在模拟盘运行，2 项通过预先登记的检验但尚未确认，5 项产出了优于基准的模型。每项结论都列在 [`research/lab/README.md`](../../research/lab/README.md) 中。

<img src="../img/by_year.png" alt="仍在运行的组合每年的夏普比率" width="100%">

重新绘制图表：

```bash
pip install matplotlib
PYTHIA_DATA=/path/to/lab/data python scripts/readme_charts.py
```

没有 `PYTHIA_DATA` 时会跳过前向记录图。

## 快速开始

需要 Node.js（当前 LTS）、Rust 1.85 或更高版本，实验室还需要 Python 3。

桌面应用：

```bash
npm install
npm run tauri dev
npm run tauri build
```

服务器和网页界面：

```bash
cp .env.example .env
npm run server
```

```bash
echo "VITE_PYTHIA_SERVER=http://localhost:8787" > .env.local
npm run dev
```

服务器监听 `127.0.0.1:8787`（可用 `PYTHIA_BIND` 修改）。`.env` 中的密钥是可选的；没有密钥时一切都在模拟盘上运行。没有 `VITE_PYTHIA_SERVER` 时，网页界面会在浏览器里运行一个小型模拟引擎。

研究实验室：

```bash
cd research/lab
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests
```

数据来自 `research/recorder` 中的记录器及其历史回填。[`research/lab/README.md`](../../research/lab/README.md) 列出了每项研究，[`research/ops/README.md`](../../research/ops/README.md) 列出了定时任务。

检查：

```bash
npm run check
npm run preflight
npm run security:scan
```

在 Windows 上，npm 脚本会从环境中移除 `CC` 和 `CXX`，因为带空格的路径会破坏 Rust 原生构建。

## 目录

| 路径 | 内容 |
|---|---|
| [`crates/pythia-core`](../../crates/pythia-core) | 引擎：策略、风险、自动驾驶、执行、交易所、预测、提醒 |
| [`crates/pythia-ml`](../../crates/pythia-ml) | 模型推理（LightGBM、ONNX），带有与实验室对照的一致性测试 |
| [`server`](../../server) | 基于引擎的 HTTP 和 WebSocket 服务器 |
| [`cli`](../../cli/README.md) | `pythia` 命令行 |
| [`src-tauri`](../../src-tauri) | 桌面应用 |
| [`src`](../../src) | React 界面 |
| [`research/lab`](../../research/lab/README.md) | 研究、模型、模拟组合、策略工厂 |
| [`research/recorder`](../../research/recorder/README.md) | 行情数据记录器和历史回填 |
| [`research/ops`](../../research/ops/README.md) | 任务表、健康检查、部署脚本 |
| [`docs`](..) | [演示交易](../DEMO.md)、[实盘运行](../LIVE-RUN.md)、[提醒](../ALERTS.md)、[模型](../MODELS.md)、[Claude API](../AI.md) 和[就绪规则](../LIVE-READINESS.md)的操作手册（英文） |

## 安全

- 全新安装不会进行任何真实交易。自动驾驶从模拟盘或交易所的演示账户开始。
- 实盘交易需要你自己的密钥，并且每个交易所都要手动输入确认。没有任何东西会自行启用。
- 密钥保存在操作系统的钥匙串或服务器的环境变量中，从不写入日志，也不会发送到界面。
- Pythia 没有提现、充值或转账功能。请只给 API 密钥交易权限。
- 加密货币现货只做多，做空只在永续合约上进行，Polymarket 只读。

完整列表见 [SAFETY.md](../../SAFETY.md)。安全问题请按 [SECURITY.md](../../SECURITY.md) 报告。

## 许可证

[MIT](../../LICENSE)。行情数据来自 Alpaca、Binance、Kraken、Bybit、OKX、Coinbase、Deribit、DefiLlama、Polymarket 和 SEC EDGAR；数据适用各来源自己的条款。如果 Pythia 对你有用，可以在 [Ko-fi 上支持它](https://ko-fi.com/senseiissei)。
