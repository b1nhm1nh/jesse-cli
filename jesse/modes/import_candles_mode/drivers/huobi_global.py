import ccxt
import jesse.helpers as jh
from jesse.modes.import_candles_mode.drivers.interface import CandleExchange


class HuobiGlobal(CandleExchange):
    def __init__(self) -> None:
        # import here instead of the top of the file to prevent possible the circular imports issue
        from jesse.modes.import_candles_mode.drivers.binance import Binance

        super().__init__(
            name='Huobi Global',
            count=1000,
            rate_limit_per_second=2,
            backup_exchange_class=Binance
        )

        exchange_id = 'huobipro'
        self.exchange_class = getattr(ccxt, exchange_id)({'enableRateLimit': True})
        if not self.exchange_class.has['fetchOHLCV']:
            raise ValueError("fetchOHLCV not supported by exchange.")
        # print(self.exchange_class.timeframes)

    def get_starting_time(self, symbol) -> int:

        # cctx uses / as default
        symbol = symbol.replace("-", "/")

        try:
            w_first_timestamp = self.exchange_class.fetch_ohlcv(symbol, '1week', 1230768000000)[0][0]
            d_first_timestamp = self.exchange_class.fetch_ohlcv(symbol, '1day', w_first_timestamp, limit=1)[0][0]
            m_first_timestamp = self.exchange_class.fetch_ohlcv(symbol, '1m', d_first_timestamp, limit=1)[0][0]
        except ccxt.NetworkError as e:
            raise ValueError(self.exchange_class.id, 'get_starting_time failed due to a network error:', str(e))
        except ccxt.ExchangeError as e:
            raise ValueError(self.exchange_class.id, 'get_starting_time failed due to exchange error:', str(e))
        except Exception as e:
            raise ValueError(self.exchange_class.id, 'get_starting_time failed with:', str(e))

        # since the first timestamp doesn't include all the 1m
        # candles, let's start since the second day then
        first_timestamp = int(m_first_timestamp)
        second_timestamp = first_timestamp + 60_000 * 1440

        return second_timestamp

    def fetch(self, symbol, start_timestamp):

        end_timestamp = start_timestamp + (self.count - 1) * 60000
        # cctx doesn't accept an end timestamp but only a count / limit of candles
        limit = (end_timestamp - start_timestamp) / 60000 + 1

        try:
            data = self.exchange_class.fetch_ohlcv(symbol.replace("-", "/"), '1m', start_timestamp, limit)
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