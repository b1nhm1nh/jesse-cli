import ast
import csv
import os
import traceback
from math import log10
from multiprocessing import cpu_count

import click
import hyperactive
import numpy as np
import pandas as pd

import jesse.helpers as jh
import jesse.services.logger as logger
import jesse.services.required_candles as required_candles
from jesse import exceptions
from jesse.config import config
from jesse.modes.backtest_mode import simulator
from jesse.routes import router
from jesse.services import metrics as stats
from jesse.services.validators import validate_routes
from jesse.store import store
from .overfitting import CSCV

os.environ['NUMEXPR_MAX_THREADS'] = str(cpu_count())


class Optimizer():
  def __init__(self, training_candles, optimal_total: int, cpu_cores: int, optimizer: str, iterations: int) -> None:
    if len(router.routes) != 1:
      raise NotImplementedError('optimize_mode mode only supports one route at the moment')

    self.strategy_name = router.routes[0].strategy_name
    self.optimal_total = optimal_total
    self.exchange = router.routes[0].exchange
    self.symbol = router.routes[0].symbol
    self.timeframe = router.routes[0].timeframe
    StrategyClass = jh.get_strategy_class(self.strategy_name)
    self.strategy_hp = StrategyClass.hyperparameters(None)
    self.hyperparameters_rules = StrategyClass.hyperparameters_rules(None)
    self.solution_len = len(self.strategy_hp)
    self.optimizer = optimizer
    self.iterations = iterations

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

    self.study_name = '{}-{}-{}-{}-{}'.format(
      self.strategy_name, self.exchange,
      self.symbol, self.timeframe, self.optimizer
    )

    self.path = 'storage/optimize/csv/{}.csv'.format(self.study_name)
    os.makedirs('./storage/optimize/csv', exist_ok=True)

  def objective_function(self, hp: str):
    score = np.nan
    try:
      if len(self.hyperparameters_rules) == 0 or jh.hp_rules_valid(hp, self.hyperparameters_rules):
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

        training_data = stats.trades(store.completed_trades.trades, store.app.daily_balance)
        total_effect_rate = log10(training_data['total']) / log10(self.optimal_total)
        total_effect_rate = min(total_effect_rate, 1)
        ratio_config = jh.get_config('env.optimization.ratio', 'sharpe')
        if ratio_config == 'sharpe':
          ratio = training_data['sharpe_ratio']
          ratio_normalized = jh.normalize(ratio, -.5, 5)
        elif ratio_config == 'calmar':
          ratio = training_data['calmar_ratio']
          ratio_normalized = jh.normalize(ratio, -.5, 30)
        elif ratio_config == 'sortino':
          ratio = training_data['sortino_ratio']
          ratio_normalized = jh.normalize(ratio, -.5, 15)
        elif ratio_config == 'omega':
          ratio = training_data['omega_ratio']
          ratio_normalized = jh.normalize(ratio, -.5, 5)
        else:
          raise ValueError(
            'The entered ratio configuration `{}` for the optimization is unknown. Choose between sharpe, calmar, sortino and omega.'.format(
              ratio_config))

        if ratio > 0:
          score = total_effect_rate * ratio_normalized

    except Exception as e:
      logger.error("".join(traceback.TracebackException.from_exception(e).format()))
    finally:

      # you can access the entire dictionary from "para"
      parameter_dict = hp.para_dict

      # save the score in the copy of the dictionary
      parameter_dict["score"] = score

      # if score:
      #   # save the daily_returns in the copy of the dictionary
      #   parameter_dict["daily_balance"] = str(store.app.daily_balance)
      # else:
      #   parameter_dict["daily_balance"] = np.nan

      # append parameter dictionary to csv
      with open(self.path, "a") as f:
        writer = csv.writer(f, delimiter=';')
        fields = parameter_dict.values()
        writer.writerow(fields)

      # reset store
      store.reset()

    return score

  def get_search_space(self):
    hp = {}
    for st_hp in self.strategy_hp:
      if st_hp['type'] is int:
        if 'step' not in st_hp:
          st_hp['step'] = 1
        hp[st_hp['name']] = list(range(st_hp['min'], st_hp['max'] + st_hp['step'], st_hp['step']))
      elif st_hp['type'] is float:
        if 'step' not in st_hp:
          st_hp['step'] = 0.1
        decs = str(st_hp['step'])[::-1].find('.')
        hp[st_hp['name']] = list(
          np.trunc(np.arange(st_hp['min'], st_hp['max'] + st_hp['step'], st_hp['step']) * 10 ** decs) / (10 ** decs))
      elif st_hp['type'] is bool:
        hp[st_hp['name']] = [True, False]
      else:
        raise TypeError('Only int, bool and float types are implemented')
    return hp

  def run(self):

    hyper = hyperactive.Hyperactive(distribution="multiprocessing",
                                    verbosity=["progress_bar", "print_results", "print_times"])

    self.search_space = self.get_search_space()

    # Later use actual search space combinations to determin n_iter
    # keys, values = zip(*self.search_space.items())
    # combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    # combinations_count = len(combinations)

    mem = None

    if jh.file_exists(self.path):
      with open(self.path, "r") as f:
        mem = pd.read_csv(f, sep=";", na_values='nan')
      if not mem.empty and not click.confirm(
          'Previous optimization results for {} exists. Continue?'.format(
              self.study_name),
          default=True,
      ):
        mem = None

    if self.optimizer == "RandomSearchOptimizer":
      optimizer = hyperactive.RandomSearchOptimizer()
    elif self.optimizer == "RandomRestartHillClimbingOptimizer":
      optimizer = hyperactive.RandomRestartHillClimbingOptimizer(
        epsilon=0.1,
        distribution="laplace",
        n_neighbours=4,
        rand_rest_p=0.1,
        n_iter_restart=20,
      )
    elif self.optimizer == "RandomAnnealingOptimizer":
      optimizer = hyperactive.RandomAnnealingOptimizer(
        epsilon=0.1,
        distribution="laplace",
        n_neighbours=4,
        rand_rest_p=0.1,
        annealing_rate=0.999,
        start_temp=0.8,
      )
    elif self.optimizer == "HillClimbingOptimizer":
      optimizer = hyperactive.HillClimbingOptimizer(
        epsilon=0.1, distribution="laplace", n_neighbours=4, rand_rest_p=0.1
      )
    elif self.optimizer == "RepulsingHillClimbingOptimizer":
      optimizer = hyperactive.RepulsingHillClimbingOptimizer(
        epsilon=0.1,
        distribution="laplace",
        n_neighbours=4,
        repulsion_factor=5,
        rand_rest_p=0.1,
      )
    elif self.optimizer == "SimulatedAnnealingOptimizer":
      optimizer = hyperactive.SimulatedAnnealingOptimizer(
        epsilon=0.1,
        distribution="laplace",
        n_neighbours=4,
        rand_rest_p=0.1,
        p_accept=0.15,
        norm_factor="adaptive",
        annealing_rate=0.999,
        start_temp=0.8,
      )
    elif self.optimizer == "ParallelTemperingOptimizer":
      optimizer = hyperactive.ParallelTemperingOptimizer(n_iter_swap=5, rand_rest_p=0.05)
    elif self.optimizer == "ParticleSwarmOptimizer":
      optimizer = hyperactive.ParticleSwarmOptimizer(
        inertia=0.4,
        cognitive_weight=0.7,
        social_weight=0.7,
        temp_weight=0.3,
        rand_rest_p=0.05,
      )
    elif self.optimizer == "EvolutionStrategyOptimizer":
      optimizer = hyperactive.EvolutionStrategyOptimizer(
        mutation_rate=0.5, crossover_rate=0.5, rand_rest_p=0.05
      )
    else:
      raise ValueError('Entered optimizer which is {} is not known.'.format(
        self.optimizer
      ))

    if mem is None or mem.empty:
      # init empty pandas dataframe
      #search_data = pd.DataFrame(columns=list(self.search_space.keys()) + ["score", "daily_balance"])
      search_data = pd.DataFrame(columns=list(self.search_space.keys()) + ["score"])
      with open(self.path, "w") as f:
        search_data.to_csv(f, sep=";", index=False, na_rep='nan')

      hyper.add_search(self.objective_function, self.search_space, optimizer=optimizer,
                       n_iter=self.iterations,
                       n_jobs=self.cpu_cores)
    else:
      #mem.drop('daily_balance', 1, inplace=True)
      hyper.add_search(self.objective_function, self.search_space, optimizer=optimizer, memory_warm_start=mem,
                       n_iter=self.iterations,
                       n_jobs=self.cpu_cores)
    hyper.run()

  # def validate_optimization(self, cscv_nbins: int = 10):
  #   with open(self.path, "r") as f:
  #     results = pd.read_csv(f, sep=";", converters={'daily_balance': from_np_array}, na_values='nan')
  #   results.dropna(inplace=True)
  #   results.drop("score", 1, inplace=True)
  #   multi_index = results.columns.tolist()
  #   multi_index.remove('daily_balance')
  #   results.set_index(multi_index, drop=True, inplace=True)
  #   new_columns = results.index.to_flat_index()
  #
  #   daily_balance = results.daily_balance.to_numpy()
  #   prepared = prepare_daily_percentage(daily_balance)
  #   vstack = np.vstack(prepared)
  #
  #   daily_percentage = pd.DataFrame(vstack).transpose()
  #   daily_percentage.columns = new_columns
  #
  #   cscv_objective = lambda r: r.mean()
  #   cscv = CSCV(n_bins=cscv_nbins, objective=cscv_objective)
  #   cscv.add_daily_returns(daily_percentage)
  #   cscv.estimate_overfitting(name=self.study_name)

# first make same length
# forward fill returns
# return percentage change
def prepare_daily_percentage(a):
  A = np.full((len(a), max(map(len, a))), np.nan)
  for i, aa in enumerate(a):
    A[i, :len(aa)] = aa
  ff = jh.np_ffill(A, 1)
  return np.diff(ff) / ff[:,:-1] * 100

def optimize_mode_hyperactive(start_date: str, finish_date: str, optimal_total: int, cpu_cores: int, optimizer: str,
                              iterations: int) -> None:
  # clear the screen
  click.clear()

  # validate routes
  validate_routes(router)

  # load historical candles and divide them into training
  # and testing candles (15% for test, 85% for training)
  training_candles = get_training_candles(start_date, finish_date)

  optimizer = Optimizer(training_candles, optimal_total, cpu_cores, optimizer, iterations)

  print('Starting optimization...')

  optimizer.run()

  print('Starting validation...')

  optimizer.validate_optimization()


def get_training_candles(start_date_str: str, finish_date_str: str):
  # Load candles (first try cache, then database)
  from jesse.modes.backtest_mode import load_candles
  return load_candles(start_date_str, finish_date_str)


def from_np_array(array_string):
  return np.array(ast.literal_eval(array_string))
