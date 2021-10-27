import requests

import jesse.helpers as jh
from jesse import exceptions
from jesse.modes.import_candles_mode.drivers.interface import CandleExchange
from datetime import datetime, timezone


class Bitstamp(CandleExchange):
    def __init__(self) -> None:
        from jesse.modes.import_candles_mode.drivers.coinbase import Coinbase

        super().__init__(
            name='Bitstamp',
            count=1000,
            rate_limit_per_second=1,
            backup_exchange_class=Coinbase
        )

    def get_starting_time(self, symbol: str) -> int:
        pass

    #
    # API: https://www.bitstamp.net/api/#ohlc_data
    #
    def fetch(self, symbol: str, start_timestamp: int) -> list:
        end_timestamp = start_timestamp + (self.count - 1) * 60000
        dashless_symbol = jh.dashless_symbol(symbol).lower()

        payload = {
            'step': 60,
            'start': int(start_timestamp / 1000),
            'end': int(end_timestamp / 1000),
            'limit': int(self.count)
        }

        response = requests.get(f'https://www.bitstamp.net/api/v2/ohlc/{dashless_symbol}', params=payload)

        self._handle_errors(response)

        data = response.json()

        return [{
            'id': jh.generate_unique_id(),
            'symbol': symbol,
            'exchange': self.name,
            'timestamp': int(d['timestamp'])*1000,
            'open': float(d['open']),
            'close': float(d['close']),
            'high': float(d['high']),
            'low': float(d['low']),
            'volume': float(d['volume'])
        } for d in data['data']['ohlc']] 


    @staticmethod
    def _handle_errors(response) -> None:
        if response.status_code == 502:
            raise exceptions.ExchangeInMaintenance('ERROR: 502 Bad Gateway. Please try again later')

        if response.status_code != 200:
            raise Exception(response.json())
