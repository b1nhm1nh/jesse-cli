import requests

import jesse.helpers as jh
from jesse import exceptions
from jesse.modes.import_candles_mode.drivers.interface import CandleExchange


class Bitmex(CandleExchange):
    def __init__(self) -> None:
        # import here instead of the top of the file to prevent possible the circular imports issue
        from jesse.modes.import_candles_mode.drivers.coinbase import Coinbase

        super().__init__(
            name='Bitmex',
            count=10000,
            rate_limit_per_second=10,
            backup_exchange_class=Coinbase
        )

        self.endpoint = 'https://www.bitmex.com/api/udf/history'

    def get_starting_time(self, symbol: str) -> int:
        dashless_symbol = jh.dashless_symbol(symbol)

        # hard-code few common symbols
        if symbol == 'XBT-USD':
            return jh.date_to_timestamp('2015-09-26')
        elif symbol == 'ETH-USD':
            return jh.date_to_timestamp('2016-01-01')

        # payload = {
        #     'resolution': 1,
        #     'from': 5000,
        # }

        # response = requests.get(f"{self.endpoint}/trade:1D:t{dashless_symbol}/hist", params=payload)

        # if response.status_code != 200:
        #     raise Exception(response.content)

        # data = response.json()

        # # wrong symbol entered
        # if not len(data):
        #     raise exceptions.SymbolNotFound(
        #         f"No candle exists for {symbol} in Bitmex. You're probably misspelling the symbol name."
        #     )

        # # since the first timestamp doesn't include all the 1m
        # # candles, let's start since the second day then
        # first_timestamp = int(data[0][0])
        return 0

    def fetch(self, symbol: str, start_timestamp: int) -> list:
        # since Bitmex API skips candles with "volume=0", we have to send end_timestamp
        # instead of limit. Therefore, we use limit number to calculate the end_timestamp
        start_timestamp = start_timestamp / 1000
        end_timestamp = start_timestamp + (self.count - 1) * 60

        dashless_symbol = jh.dashless_symbol(symbol)

        payload = {
            'symbol': dashless_symbol,
            'from': start_timestamp,
            'to': end_timestamp,
            'resolution': 1
        }


        response = requests.get(
            f"{self.endpoint}/",
            params=payload
        )
        self._handle_errors(response)

        data = response.json()

        if not 's' in data or data['s'] != 'ok':
            raise exceptions.SymbolNotFound(
                f"No candle exists for {symbol} in Bitmex. You're probably misspelling the symbol name."
            )
        # jh.dd(data)

        # for d in range(0, len(data['t'])):
        #     print(d)
        #     print(f"T {data['t'][d]} {data['o'][d]} {data['c'][d]} {data['v'][d]}")  
        # jh.dd("Here") 
        # 
        print(f"S: {start_timestamp}")

        length = len(data['t'])  
        return [{
                'id': jh.generate_unique_id(),
                'symbol': symbol,
                'exchange': self.name,
                'timestamp': data['t'][d],
                'open': data['o'][d],
                'close': data['c'][d],
                'high': data['h'][d],
                'low': data['l'][d],
                'volume': data['v'][d]
            } for d in range(0, length)]

    def _handle_errors(self, response) -> None:
        # Exchange In Maintenance
        if response.status_code == 502:
            raise exceptions.ExchangeInMaintenance('ERROR: 502 Bad Gateway. Please try again later')

        if response.status_code != 200:
            raise Exception(response.json()['error'])