import time
import logging
import requests
from datetime import datetime

# Настраиваем логгер в ТВОЙ формат: YYMMDD HHMMSS PID LEVEL component: message
logging.basicConfig(
    filename="data/moex_live.log",
    format="%(asctime)s %(process)d %(levelname)s %(name)s: %(message)s",
    datefmt="%y%m%d %H%M%S",
    level=logging.INFO,
)
logger = logging.getLogger("moex.collector")

TICKERS = ["SBER", "GAZP", "YNDX", "LKOH", "ROSN"]  # какие акции следим
PREV_PRICES = {}  # запоминаем предыдущую цену

def fetch_price(ticker: str) -> dict:
    url = (
        f"https://iss.moex.com/iss/engines/stock/markets/shares/"
        f"boards/TQBR/securities/{ticker}.json"
        f"?iss.meta=off&iss.only=marketdata&marketdata.columns=SECID,LAST,SYSTIME"
    )
    start = time.time()
    response = requests.get(url, timeout=5)
    elapsed_ms = (time.time() - start) * 1000
    return {"response": response, "elapsed_ms": elapsed_ms}


def check_and_log(ticker: str):
    try:
        result = fetch_price(ticker)
        elapsed = result["elapsed_ms"]
        data = result["response"].json()

        rows = data.get("marketdata", {}).get("data", [])
        if not rows or rows[0][1] is None:
            # Пустой ответ — данных нет
            logger.warning(f"empty_price_response: ticker={ticker} elapsed_ms={elapsed:.0f}")
            return

        price = float(rows[0][1])
        systime = rows[0][2]

        # Проверяем таймаут запроса
        if elapsed > 3000:
            logger.warning(f"slow_response: ticker={ticker} elapsed_ms={elapsed:.0f}")

        # Проверяем аномальный скачок цены
        if ticker in PREV_PRICES:
            prev = PREV_PRICES[ticker]
            change_pct = abs(price - prev) / prev * 100
            if change_pct > 5:
                logger.error(
                    f"price_spike: ticker={ticker} prev={prev} current={price} "
                    f"change_pct={change_pct:.2f}"
                )
            elif change_pct > 2:
                logger.warning(
                    f"price_jump: ticker={ticker} change_pct={change_pct:.2f}"
                )
            else:
                logger.info(
                    f"price_ok: ticker={ticker} price={price} elapsed_ms={elapsed:.0f}"
                )
        else:
            logger.info(f"price_first: ticker={ticker} price={price}")

        PREV_PRICES[ticker] = price

    except requests.Timeout:
        logger.error(f"timeout: ticker={ticker} threshold_ms=5000")

    except requests.ConnectionError:
        logger.error(f"connection_failed: ticker={ticker} reason=network_error")

    except Exception as e:
        logger.warning(f"unexpected_error: ticker={ticker} error={e}")


def run_collector(interval_sec: float = 10.0):
    """Запускай этот цикл в отдельном потоке или процессе"""
    print(f"Коллектор MOEX запущен. Интервал: {interval_sec}с. Тикеры: {TICKERS}")
    while True:
        for ticker in TICKERS:
            check_and_log(ticker)
        time.sleep(interval_sec)


if __name__ == "__main__":
    run_collector(interval_sec=10)