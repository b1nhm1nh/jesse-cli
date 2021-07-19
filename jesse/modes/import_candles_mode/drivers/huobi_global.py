import ccxt
import time
import jesse.helpers as jh
from jesse.modes.import_candles_mode.drivers.interface import CandleExchange


class HuobiGlobal(CandleExchange):
    def __init__(self) -> None:

        super().__init__(
            name='Huobi Global',
            # cctx mentions in the docs 1000 is a good value that works across many exchanges.
            # See here https://ccxt.readthedocs.io/en/latest/manual.html#ohlcv-candlestick-charts
            count=1000,
            rate_limit_per_second=2,
            backup_exchange_class=None
        )

        exchange_id = 'huobipro'
        # cctx has a built-in rate limiter as alternative self.exchange_class.rateLimit returns the exchanges limit.
        # all properties of the exchange class: https://ccxt.readthedocs.io/en/latest/manual.html#exchange-structure
        self.exchange_class = getattr(ccxt, exchange_id)({'enableRateLimit': True})

        if not self.exchange_class.has['fetchOHLCV']:
            raise ValueError("fetchOHLCV not supported by exchange.")

        if not "1m" in self.exchange_class.timeframes.keys():
            raise ValueError("1m timeframe not supported by exchange.")


    def get_starting_time(self, symbol) -> int:

        # cctx uses / as default
        symbol = symbol.replace("-", "/")

        try:
            first_timestamp = None
            # here we loop through all timeframes starting with the biggest to find the first timestamp in a fast dynamic way.
            for timeframe in reversed(list(self.exchange_class.timeframes.keys())):
                if not first_timestamp:
                    first_timestamp = self.exchange_class.fetch_ohlcv(symbol, timeframe, since=1230768000000)[0][0]
                else:
                    first_timestamp = self.exchange_class.fetch_ohlcv(symbol, timeframe, since=first_timestamp, limit=2)[0][0]
                if timeframe == "1m":
                    break
                # make sure to not hit a rate-limit here.
                time.sleep(0.5)
        except ccxt.NetworkError as e:
            raise ValueError(self.exchange_class.id, 'get_starting_time failed due to a network error:', str(e))
        except ccxt.ExchangeError as e:
            raise ValueError(self.exchange_class.id, 'get_starting_time failed due to exchange error:', str(e))
        except Exception as e:
            raise ValueError(self.exchange_class.id, 'get_starting_time failed with:', str(e))

        # since the first timestamp doesn't include all the 1m
        # candles, let's start since the second day then
        second_timestamp = int(first_timestamp) + 60_000 * 1440

        return second_timestamp

    def fetch(self, symbol, start_timestamp):

        # cctx doesn't accept an end timestamp but only a count / limit of candles
        try:
            data = self.exchange_class.fetch_ohlcv(symbol.replace("-", "/"), '1m', since=start_timestamp, limit=self.count - 1)
        except ccxt.NetworkError as e:
            raise ValueError(self.exchange_class.id, 'fetch failed due to a network error:', str(e))
        except ccxt.ExchangeError as e:
            raise ValueError(self.exchange_class.id, 'fetch failed due to exchange error:', str(e))
        except Exception as e:
            raise ValueError(self.exchange_class.id, 'fetch failed with:', str(e))

        candles = []
        for d in data:
            candles.append({
                'id': jh.generate_unique_id(),
                'symbol': symbol,
                'exchange': self.name,
                'timestamp': int(d[0]),
                'open': float(d[1]),
                'close': float(d[4]),
                'high': float(d[2]),
                'low': float(d[3]),
                'volume': float(d[5])
            })

        return candles