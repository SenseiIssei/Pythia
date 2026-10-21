# Pythia

[English](../../README.md) · [Deutsch](README.de.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · 한국어 · [Español](README.es.md) · [Français](README.fr.md) · [Português](README.pt-BR.md)

Pythia는 모의 거래로 시작해서, 전략이 실력을 증명할 때까지 모의 거래에 머무는 트레이딩 콕핏입니다. Rust 엔진, 그 위에서 동작하는 데스크톱 앱과 웹 UI, 그리고 엔진이 무엇을 거래할 수 있는지 결정하는 Python 연구실로 이루어져 있습니다. 연구실은 지금까지 시도한 모든 아이디어를 세기 때문에, 운 좋게 나온 백테스트가 그대로 통과하지 못합니다.

여기 있는 전략 중 수익이 증명된 것은 없습니다. 실제 계좌를 연결하기 전에 [SAFETY.md](../../SAFETY.md)(영어)를 읽어 주세요.

<table>
  <tr>
    <td width="50%"><img src="../img/app-home.png" alt="홈 화면"></td>
    <td width="50%"><img src="../img/app-autopilot.png" alt="오토파일럿 화면"></td>
  </tr>
</table>

샘플 데이터를 사용한 개발 빌드의 스크린샷입니다.

## 하는 일

- 오토파일럿은 사용자가 멈추거나 손절 규칙이 발동할 때까지 하나의 전략을 스스로 거래하는 자금입니다. 여러 개를 나란히 돌릴 수 있고, 각각 BTC와 비교해 평가합니다.
- 암호화폐, 미국 주식, ETF는 Alpaca 모의 계좌에서 거래합니다. 롱/숏 북은 모의로 무기한 선물을 거래하며, 데모 키를 넣으면 Bybit 데모 계좌에서도 거래합니다.
- 모든 주문 앞에는 리스크 관리자가 있습니다. 킬 스위치, 일일 손실과 낙폭 한도, 익스포저 상한, 변동성 타기팅. 불확실하면 주문을 거부합니다.
- 연구실의 모든 연구는 첫 실행 전에 계획을 등록하고, 비용을 뺀 뒤 표본 외 데이터로 검증하며, 지금까지의 시도 횟수만큼 샤프 지수를 할인합니다(deflated Sharpe).
- 모델(변동성, 코인 순위, 수익률 분위수)은 연구실에서 학습하고 엔진에서 실행합니다. 거래에 영향을 주기 전에 먼저 섀도 모드로 돌아갑니다.
- 알림은 Telegram이나 원하는 웹훅으로 영어 또는 독일어로 전송됩니다.

## 구조

<img src="../img/architecture.svg" alt="Pythia: 맨 위는 UI, 그 아래 Rust 엔진, 그 아래 연구실과 레코더, 맨 아래는 시장" width="100%">

연구실의 북은 근거와 함께일 때만 오토파일럿에 전달됩니다. 자동 선택은 그 근거와 실전 기록으로 북의 순위를 매기고, 실험용 북은 오토파일럿이 이름으로 지정할 때만 실행됩니다.

## 지금까지의 결과

모든 수치는 연구실의 결과 파일이나 엔진 자체의 기록에서 나옵니다. 아래 그래프는 모두 [`scripts/readme_charts.py`](../../scripts/readme_charts.py)가 그리며 출처도 함께 표시합니다.

<img src="../img/scoreboard.png" alt="검증한 전략들의 표본 외 샤프 지수" width="100%">

가장 좋은 북은 유동성 상위 10개 코인에 대한 돈치안 돌파 전략입니다. 2024년 이후 샤프 지수는 1.17로, BTC 보유의 0.74보다 높습니다. 그래도 할인 검정은 통과하지 못합니다. 1,836번의 시도를 세면, 같은 수의 순수 노이즈 전략 중 가장 좋은 것도 약 2.69가 나오기 때문입니다.

무기한 선물 롱/숏 연구 두 개가 사전 등록한 검정을 통과했습니다(M4 잔차와 펀딩 캐리). 둘 다 할인 후에는 남지 않아 실험으로만 운영합니다. 모멘텀 북 대부분은 사실 BTC 200일 이동평균 필터를 다르게 표현한 것이었습니다. 필터가 꺼진 날에는 모두 손실을 냅니다.

<img src="../img/forward.png" alt="2026년 10월 15일 이후 모의 오토파일럿의 실전 기록" width="100%">

모의 오토파일럿은 2026년 10월 15일에 시작했습니다. 6일이 지난 지금 주 자동 선택은 +0.48 %, BTC는 +3.22 %입니다. 무언가를 판단하기에는 너무 짧지만, 기록을 첫날부터 공개하려고 그래프를 실었습니다.

<img src="../img/research_funnel.png" alt="시도 횟수의 증가와 각 연구의 판정" width="100%">

지금까지 연구는 69개입니다. 43개는 실패하거나 중단되었고, 7개는 표시된 실험으로 모의 운영 중이며, 2개는 사전 등록대로 통과했지만 아직 확인되지 않았고, 5개는 기준을 넘는 모델을 만들었습니다. 모든 판정은 [`research/lab/README.md`](../../research/lab/README.md)에 있습니다.

<img src="../img/by_year.png" alt="운영 중인 북의 연도별 샤프 지수" width="100%">

그래프 다시 그리기:

```bash
pip install matplotlib
PYTHIA_DATA=/path/to/lab/data python scripts/readme_charts.py
```

`PYTHIA_DATA`가 없으면 실전 기록 그래프는 건너뜁니다.

## 시작하기

Node.js(현재 LTS), Rust 1.85 이상, 연구실에는 Python 3가 필요합니다.

데스크톱 앱:

```bash
npm install
npm run tauri dev
npm run tauri build
```

서버와 웹 UI:

```bash
cp .env.example .env
npm run server
```

```bash
echo "VITE_PYTHIA_SERVER=http://localhost:8787" > .env.local
npm run dev
```

서버는 `127.0.0.1:8787`에서 대기합니다(`PYTHIA_BIND`로 변경). `.env`의 키는 선택 사항이며, 없으면 모든 것이 모의 거래로 남습니다. `VITE_PYTHIA_SERVER`가 없으면 웹 UI는 브라우저 안의 작은 모의 엔진으로 동작합니다.

연구실:

```bash
cd research/lab
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests
```

데이터는 `research/recorder`의 레코더와 그 과거 데이터 백필에서 옵니다. [`research/lab/README.md`](../../research/lab/README.md)에 모든 연구가, [`research/ops/README.md`](../../research/ops/README.md)에 예약 작업이 정리되어 있습니다.

검사:

```bash
npm run check
npm run preflight
npm run security:scan
```

Windows에서는 공백이 있는 경로가 Rust 네이티브 빌드를 깨뜨리기 때문에 npm 스크립트가 환경에서 `CC`와 `CXX`를 제거합니다.

## 디렉터리

| 경로 | 내용 |
|---|---|
| [`crates/pythia-core`](../../crates/pythia-core) | 엔진: 전략, 리스크, 오토파일럿, 주문 실행, 거래소, 예측, 알림 |
| [`crates/pythia-ml`](../../crates/pythia-ml) | 모델 추론(LightGBM, ONNX)과 연구실 대비 일치 테스트 |
| [`server`](../../server) | 엔진 위의 HTTP 및 WebSocket 서버 |
| [`src-tauri`](../../src-tauri) | 데스크톱 앱 |
| [`src`](../../src) | React UI |
| [`research/lab`](../../research/lab/README.md) | 연구, 모델, 모의 북, 전략 팩토리 |
| [`research/recorder`](../../research/recorder/README.md) | 시장 데이터 레코더와 과거 데이터 백필 |
| [`research/ops`](../../research/ops/README.md) | 작업 표, 상태 점검, 배포 스크립트 |
| [`docs`](..) | [데모 거래](../DEMO.md), [실거래](../LIVE-RUN.md), [알림](../ALERTS.md), [모델](../MODELS.md), [Claude API](../AI.md), [준비 규칙](../LIVE-READINESS.md) 안내서(영어) |

## 안전

- 새로 설치하면 실제 거래는 하지 않습니다. 오토파일럿은 모의 거래나 거래소의 데모 계좌에서 시작합니다.
- 실거래에는 본인의 키와 거래소마다 직접 입력하는 확인이 필요합니다. 스스로 켜지는 것은 없습니다.
- 키는 운영체제의 키체인이나 서버 환경 변수에 저장되며, 로그에 남거나 UI로 전송되지 않습니다.
- Pythia에는 출금, 입금, 송금 기능이 없습니다. API 키에는 거래 권한만 주세요.
- 암호화폐 현물은 롱만, 숏은 무기한 선물에서만, Polymarket은 읽기 전용입니다.

전체 목록은 [SAFETY.md](../../SAFETY.md)에 있습니다. 보안 문제는 [SECURITY.md](../../SECURITY.md)의 절차로 알려 주세요.

## 라이선스

[MIT](../../LICENSE). 시장 데이터는 Alpaca, Binance, Kraken, Bybit, OKX, Coinbase, Deribit, DefiLlama, Polymarket, SEC EDGAR에서 가져오며, 각 데이터에는 출처별 약관이 적용됩니다. Pythia가 도움이 되었다면 [Ko-fi에서 후원](https://ko-fi.com/senseiissei)할 수 있습니다.
