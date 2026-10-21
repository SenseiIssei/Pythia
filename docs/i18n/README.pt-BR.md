# Pythia

[English](../../README.md) · [Deutsch](README.de.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · Português

Pythia é um cockpit de trading que começa no papel e fica lá até que uma estratégia mereça mais. Ele tem um motor em Rust, um aplicativo de desktop e uma interface web por cima, e um laboratório de pesquisa em Python que decide o que o motor pode negociar. O laboratório conta cada ideia que já testou, então um backtest de sorte não passa.

Nenhuma estratégia aqui é comprovadamente lucrativa. Leia o [SAFETY.md](../../SAFETY.md) (em inglês) antes de conectar uma conta real.

<table>
  <tr>
    <td width="50%"><img src="../img/app-home.png" alt="Tela inicial"></td>
    <td width="50%"><img src="../img/app-autopilot.png" alt="Tela do piloto automático"></td>
  </tr>
</table>

Capturas de uma versão de desenvolvimento com dados de exemplo.

## O que ele faz

- Um piloto automático é um valor que negocia uma estratégia sozinho até você pará-lo ou uma regra de parada disparar. Vários rodam lado a lado, cada um comparado ao BTC.
- Cripto, ações dos EUA e ETFs são negociados na conta de papel da Alpaca. As carteiras long/short negociam perpétuos no papel, ou numa conta demo da Bybit se você adicionar chaves de demo.
- O gestor de risco fica na frente de cada ordem: botão de emergência, limites de perda diária e de drawdown, tetos de exposição, meta de volatilidade. Se algo não estiver claro, ele recusa.
- Cada estudo do laboratório é registrado antes da primeira execução, testado fora da amostra depois dos custos, e seu Sharpe é corrigido pelo número total de tentativas feitas até agora (deflated Sharpe).
- Os modelos (volatilidade, ranking de moedas, quantis de retorno) são treinados no laboratório e executados pelo motor. Eles rodam primeiro em modo sombra antes de poder afetar uma operação.
- Os alertas chegam pelo Telegram ou qualquer webhook, em inglês ou alemão.

## Arquitetura

<img src="../img/architecture.svg" alt="Pythia: no topo a interface, depois o motor em Rust, depois o laboratório e o gravador, embaixo os mercados" width="100%">

Uma carteira do laboratório só chega a um piloto automático junto com suas evidências. A seleção automática ordena as carteiras por essas evidências e pelo histórico real, e uma carteira experimental só roda onde um piloto automático a pede pelo nome.

## Resultados até agora

Todos os números vêm dos arquivos de resultado do laboratório ou dos registros do próprio motor. [`scripts/readme_charts.py`](../../scripts/readme_charts.py) desenha cada gráfico abaixo e indica suas fontes.

<img src="../img/scoreboard.png" alt="Sharpe fora da amostra das estratégias testadas" width="100%">

A melhor carteira é um rompimento de Donchian nas dez moedas mais líquidas: Sharpe de 1,17 desde 2024, contra 0,74 para simplesmente manter BTC. Mesmo assim ela não passa na correção. Com 1.836 tentativas contadas, a melhor entre o mesmo número de estratégias de puro ruído mostraria cerca de 2,69.

Dois estudos long/short com perpétuos passaram nos testes registrados (o resíduo M4 e um carry de funding). Nenhum sobrevive à correção, então os dois rodam apenas como experimentos. A maioria das carteiras de momentum é, na verdade, o filtro de 200 dias do BTC disfarçado: nos dias em que o filtro está desligado, todas perdem dinheiro.

<img src="../img/forward.png" alt="Histórico real dos pilotos automáticos no papel desde 15 de outubro de 2026" width="100%">

Os pilotos automáticos no papel começaram em 15 de outubro de 2026. Depois de seis dias, a seleção automática principal está em +0,48 % e o BTC em +3,22 %. É curto demais para significar alguma coisa; o gráfico está aqui para que o histórico seja público desde o primeiro dia.

<img src="../img/research_funnel.png" alt="Crescimento do número de tentativas e o veredito de cada estudo" width="100%">

69 estudos até agora: 43 falharam ou foram interrompidos, 7 rodam no papel como experimentos identificados, 2 passaram no teste registrado sem confirmação, 5 geraram um modelo que supera sua referência. Todos os vereditos estão em [`research/lab/README.md`](../../research/lab/README.md).

<img src="../img/by_year.png" alt="Sharpe por ano das carteiras que ainda rodam" width="100%">

Para redesenhar os gráficos:

```bash
pip install matplotlib
PYTHIA_DATA=/path/to/lab/data python scripts/readme_charts.py
```

Sem `PYTHIA_DATA`, o gráfico do histórico real é pulado.

## Primeiros passos

Você precisa de Node.js (LTS atual), Rust 1.85 ou mais recente e, para o laboratório, Python 3.

Aplicativo de desktop:

```bash
npm install
npm run tauri dev
npm run tauri build
```

Servidor e interface web:

```bash
cp .env.example .env
npm run server
```

```bash
echo "VITE_PYTHIA_SERVER=http://localhost:8787" > .env.local
npm run dev
```

O servidor escuta em `127.0.0.1:8787` (`PYTHIA_BIND` muda isso). As chaves no `.env` são opcionais; sem elas tudo fica no papel. Sem `VITE_PYTHIA_SERVER`, a interface web roda um pequeno motor de papel no navegador.

Laboratório:

```bash
cd research/lab
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests
```

Os dados vêm do gravador em `research/recorder` e da sua carga histórica. [`research/lab/README.md`](../../research/lab/README.md) lista cada estudo e [`research/ops/README.md`](../../research/ops/README.md) as tarefas agendadas.

Verificações:

```bash
npm run check
npm run preflight
npm run security:scan
```

No Windows, os scripts do npm removem `CC` e `CXX` do ambiente, porque caminhos com espaços quebram as compilações nativas de Rust.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| [`crates/pythia-core`](../../crates/pythia-core) | Motor: estratégias, risco, pilotos automáticos, execução, corretoras, previsões, alertas |
| [`crates/pythia-ml`](../../crates/pythia-ml) | Inferência de modelos (LightGBM, ONNX) com testes de paridade contra o laboratório |
| [`server`](../../server) | Servidor HTTP e WebSocket sobre o motor |
| [`src-tauri`](../../src-tauri) | Aplicativo de desktop |
| [`src`](../../src) | Interface React |
| [`research/lab`](../../research/lab/README.md) | Estudos, modelos, carteiras no papel, fábrica de estratégias |
| [`research/recorder`](../../research/recorder/README.md) | Gravador de dados de mercado e carga histórica |
| [`research/ops`](../../research/ops/README.md) | Tabela de tarefas, verificações de saúde, scripts de deploy |
| [`docs`](..) | Guias de [trading demo](../DEMO.md), [operação real](../LIVE-RUN.md), [alertas](../ALERTS.md), [modelos](../MODELS.md), [API do Claude](../AI.md) e a [regra de prontidão](../LIVE-READINESS.md) (em inglês) |

## Segurança

- Uma instalação nova não negocia nada real. Os pilotos automáticos começam no papel ou na conta demo de uma corretora.
- Operar com dinheiro real exige suas próprias chaves e uma confirmação digitada para cada corretora. Nada se ativa sozinho.
- As chaves ficam no chaveiro do sistema ou no ambiente do servidor, nunca são registradas em log nem enviadas à interface.
- O Pythia não tem função de saque, depósito ou transferência. Dê às chaves de API apenas permissão de negociação.
- Cripto à vista é só comprado, vendas a descoberto existem só em perpétuos, e o Polymarket é somente leitura.

A lista completa está no [SAFETY.md](../../SAFETY.md). Problemas de segurança devem ser reportados conforme o [SECURITY.md](../../SECURITY.md).

## Licença

[MIT](../../LICENSE). Dados de mercado de Alpaca, Binance, Kraken, Bybit, OKX, Coinbase, Deribit, DefiLlama, Polymarket e SEC EDGAR; os termos de cada fonte se aplicam aos seus dados. Se o Pythia for útil para você, pode [apoiá-lo no Ko-fi](https://ko-fi.com/senseiissei).
