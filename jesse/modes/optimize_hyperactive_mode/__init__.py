import os
from math import log10
from multiprocessing import cpu_count
from typing import Dict, Any, Tuple, Union

import arrow
import click
import numpy as np
import pandas as pd
from hyperactive import Hyperactive, RandomSearchOptimizer

import jesse.helpers as jh
import jesse.services.required_candles as required_candles
from jesse import exceptions
from jesse.config import config
from jesse.modes.backtest_mode import simulator
from jesse.routes import router
from jesse.services import metrics as stats
from jesse.services.validators import validate_routes
from jesse.store import store

os.environ['NUMEXPR_MAX_THREADS'] = str(cpu_count())


class Optimizer():
    def __init__(self, training_candles, optimal_total: int, cpu_cores: int) -> None:
        if len(router.routes) != 1:
            raise NotImplementedError('optimize_mode mode only supports one route at the moment')

        self.strategy_name = router.routes[0].strategy_name
        self.optimal_total = optimal_total
        self.exchange = router.routes[0].exchange
        self.symbol = router.routes[0].symbol
        self.timeframe = router.routes[0].timeframe
        StrategyClass = jh.get_strategy_class(self.strategy_name)
        self.strategy_hp = StrategyClass.hyperparameters(None)
        self.solution_len = len(self.strategy_hp)

        if self.solution_len == 0:
            raise exceptions.InvalidStrategy('Targeted strategy does not implement a valid hyperparameters() method.')

        if cpu_cores > cpu_count():
            raise ValueError('Entered cpu cores number is more than available on this machine which is {}'.format(
                cpu_count()
            ))
        elif cpu_cores == 0:
            self.cpu_cores = cpu_count()
        else:
            self.cpu_cores = cpu_cores

        self.training_candles = training_candles

        key = jh.key(self.exchange, self.symbol)
        training_candles_start_date = jh.timestamp_to_time(self.training_candles[key]['candles'][0][0]).split('T')[0]
        training_candles_finish_date = jh.timestamp_to_time(self.training_candles[key]['candles'][-1][0]).split('T')[0]

        self.training_initial_candles = []

        for c in config['app']['considering_candles']:
            self.training_initial_candles.append(
                required_candles.load_required_candles(c[0], c[1], training_candles_start_date,
                                                       training_candles_finish_date))


        self.study_name = '{}-{}-{}-{}'.format(
          self.strategy_name, self.exchange,
          self.symbol, self.timeframe
        )

        self.path = 'storage/optimize/csv/{}.csv'.format(self.study_name)
        os.makedirs('./storage/optimize/csv', exist_ok=True)


    def objective_function(self, hp: str):

        # init candle store
        store.candles.init_storage(5000)
        # inject required TRAINING candles to the candle store

        for num, c in enumerate(config['app']['considering_candles']):
            required_candles.inject_required_candles_to_store(
                self.training_initial_candles[num],
                c[0],
                c[1]
            )

        # run backtest simulation
        simulator(self.training_candles, hp)


        if store.completed_trades.count > 5:
            training_data = stats.trades(store.completed_trades.trades, store.app.daily_balance)
            total_effect_rate = log10(training_data['total']) / log10(self.optimal_total)
            if total_effect_rate > 1:
                total_effect_rate = 1

            ratio_config = jh.get_config('env.optimization.ratio', 'sharpe')
            if ratio_config == 'sharpe':
                ratio = training_data['sharpe_ratio']
                ratio_normalized = jh.normalize(ratio, -.5, 5)
            elif ratio_config == 'calmar':
                ratio = training_data['calmar_ratio']
                ratio_normalized = jh.normalize(ratio, -.5, 30)
            elif ratio_config == 'sortiono':
                ratio = training_data['sortino_ratio']
                ratio_normalized = jh.normalize(ratio, -.5, 15)
            elif ratio_config == 'omega':
                ratio = training_data['omega_ratio']
                ratio_normalized = jh.normalize(ratio, -.5, 5)
            else:
                raise ValueError(
                    'The entered ratio configuration `{}` for the optimization is unknown. Choose between sharpe, calmar, sortino and omega.'.format(
                        ratio_config))

            if ratio < 0:
                score = 0.0001
                # reset store
                store.reset()
                return score

            score = total_effect_rate * ratio_normalized

        else:
            score = 0.0001

        # reset store
        store.reset()

        # you can access the entire dictionary from "para"
        parameter_dict = hp.para_dict

        # save the score in the copy of the dictionary
        parameter_dict["score"] = score

        # append parameter dictionary to pandas dataframe
        search_data = pd.read_csv(self.path)
        search_data_new = pd.DataFrame(parameter_dict, columns=list(self.search_space.keys()) + ["score"], index=[0])
        search_data = search_data.append(search_data_new)
        search_data.to_csv(self.path, index=False)

        return score

    def get_search_space(self):
        hp = {}
        for st_hp in self.strategy_hp:
            if st_hp['type'] is int:
                if not 'step' in st_hp:
                    st_hp['step'] = 1
                hp[st_hp['name']] = list(range(st_hp['min'], st_hp['max'], st_hp['step']))
            elif st_hp['type'] is float:
                if not 'step' in st_hp:
                    st_hp['step'] = 0.1
                hp[st_hp['name']] = list(np.arange(st_hp['min'], st_hp['max'], st_hp['step']))
            elif st_hp['type'] is bool:
                hp[st_hp['name']] = [True, False]
            else:
                raise TypeError('Only int, bool and float types are implemented')

        return hp

    def run(self):

        hyper = Hyperactive(distribution="multiprocessing")
        optimizer = RandomSearchOptimizer()
        self.search_space = self.get_search_space()

        if jh.file_exists(self.path):
          if click.confirm('Optimization for {} exists? Continue?'.format(self.study_name), abort=True, default=True):
            mem = pd.read_csv(self.path)
            hyper.add_search(self.objective_function, self.search_space, optimizer=optimizer, n_iter=self.solution_len * 100 - len(mem), memory_warm_start=mem,
                           n_jobs=self.cpu_cores)
            hyper.run()
            return

        # init empty pandas dataframe
        search_data = pd.DataFrame(columns=list(self.search_space.keys()) + ["score"])
        search_data.to_csv(self.path, index=False)
        hyper.add_search(self.objective_function, self.search_space, optimizer=optimizer,
                         n_iter=self.solution_len * 100,
                         n_jobs=self.cpu_cores)
        hyper.run()




        hyper.run()



def optimize_mode(start_date: str, finish_date: str, optimal_total: int, cpu_cores: int) -> None:
    # clear the screen
    click.clear()
    print('loading candles...')

    # validate routes
    validate_routes(router)

    # load historical candles and divide them into training
    # and testing candles (15% for test, 85% for training)
    training_candles = get_training_candles(start_date, finish_date)

    # clear the screen
    click.clear()

    optimizer = Optimizer(training_candles, optimal_total, cpu_cores)

    optimizer.run()


def get_training_candles(start_date_str: str, finish_date_str: str):

    # Load candles (first try cache, then database)
    from jesse.modes.backtest_mode import load_candles
    training_candles = load_candles(start_date_str, finish_date_str)

    return training_candles
