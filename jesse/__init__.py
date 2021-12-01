from math import fabs
import os
import sys
# Hide the "FutureWarning: pandas.util.testing is deprecated." caused by empyrical
import warnings
from pydoc import locate

import click
import pkg_resources

import jesse.helpers as jh
from typing import Dict, Any, Tuple, Union
from numpy import ndarray
import arrow


warnings.simplefilter(action='ignore', category=FutureWarning)

from celery import Celery

# Python version validation.
if jh.python_version() < 3.7:
    print(
        jh.color(
            f'Jesse requires Python version above 3.7. Yours is {jh.python_version()}',
            'red'
        )
    )

# fix directory issue
sys.path.insert(0, os.getcwd())

ls = os.listdir('.')
is_jesse_project = 'strategies' in ls and 'config.py' in ls and 'storage' in ls and 'routes.py' in ls


def validate_cwd() -> None:
    """
    make sure we're in a Jesse project
    """
    if not is_jesse_project:
        print(
            jh.color(
                'Current directory is not a Jesse project. You must run commands from the root of a Jesse project.',
                'red'
            )
        )
        os._exit(1)


def inject_local_config() -> None:
    """
    injects config from local config file
    """
    local_config = locate('config.config')
    from jesse.config import set_config
    set_config(local_config)


def inject_local_routes() -> None:
    """
    injects routes from local routes folder
    """
    local_router = locate('routes')
    from jesse.routes import router

    router.set_routes(local_router.routes)
    router.set_extra_candles(local_router.extra_candles)
    router.set_ctf_candles(local_router.ctf_candles)


# inject local files
if is_jesse_project:
    inject_local_config()
    inject_local_routes()

broker_url = f"redis://{jh.get_config('env.cluster.host')}:{jh.get_config('env.cluster.port')}/{jh.get_config('env.cluster.broker_db')}"
backend_url = f"redis://{jh.get_config('env.cluster.host')}:{jh.get_config('env.cluster.port')}/{jh.get_config('env.cluster.backend_db')}"
print(f"{broker_url} {backend_url}")
app = Celery('jesse',  broker=broker_url, backend=backend_url, worker_prefetch_multiplier=1)


def register_custom_exception_handler() -> None:
    import sys
    import threading
    import traceback
    import logging
    from jesse.services import logger as jesse_logger
    import click
    from jesse import exceptions

    log_format = "%(message)s"
    os.makedirs('storage/logs', exist_ok=True)

    if jh.is_livetrading():
        logging.basicConfig(filename='storage/logs/live-trade.txt', level=logging.INFO,
                            filemode='w', format=log_format)
    elif jh.is_paper_trading():
        logging.basicConfig(filename='storage/logs/paper-trade.txt', level=logging.INFO,
                            filemode='w',
                            format=log_format)
    elif jh.is_collecting_data():
        logging.basicConfig(filename='storage/logs/collect.txt', level=logging.INFO, filemode='w',
                            format=log_format)
    elif jh.is_optimizing():
        logging.basicConfig(filename='storage/logs/optimize.txt', level=logging.INFO, filemode='w',
                            format=log_format)
    else:
        logging.basicConfig(level=logging.INFO)

    # main thread
    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.excepthook(exc_type, exc_value, exc_traceback)
            return

        # handle Breaking exceptions
        if exc_type in [
            exceptions.InvalidConfig, exceptions.RouteNotFound, exceptions.InvalidRoutes,
            exceptions.CandleNotFoundInDatabase
        ]:
            click.clear()
            print(f"{'=' * 30} EXCEPTION TRACEBACK:")
            traceback.print_tb(exc_traceback, file=sys.stdout)
            print("=" * 73)
            print(
                '\n',
                jh.color('Uncaught Exception:', 'red'),
                jh.color(f'{exc_type.__name__}: {exc_value}', 'yellow')
            )
            return

        # send notifications if it's a live session
        if jh.is_live():
            jesse_logger.error(
                f'{exc_type.__name__}: {exc_value}'
            )

        if jh.is_live() or jh.is_collecting_data():
            logging.error("Uncaught Exception:", exc_info=(exc_type, exc_value, exc_traceback))
        else:
            print(f"{'=' * 30} EXCEPTION TRACEBACK:")
            traceback.print_tb(exc_traceback, file=sys.stdout)
            print("=" * 73)
            print(
                '\n',
                jh.color('Uncaught Exception:', 'red'),
                jh.color(f'{exc_type.__name__}: {exc_value}', 'yellow')
            )

        if jh.is_paper_trading():
            print(
                jh.color(
                    'An uncaught exception was raised. Check the log file at:\nstorage/logs/paper-trade.txt',
                    'red'
                )
            )
        elif jh.is_livetrading():
            print(
                jh.color(
                    'An uncaught exception was raised. Check the log file at:\nstorage/logs/live-trade.txt',
                    'red'
                )
            )
        elif jh.is_collecting_data():
            print(
                jh.color(
                    'An uncaught exception was raised. Check the log file at:\nstorage/logs/collect.txt',
                    'red'
                )
            )

    sys.excepthook = handle_exception

    # other threads
    if jh.python_version() >= 3.8:
        def handle_thread_exception(args) -> None:
            if args.exc_type == SystemExit:
                return

            # handle Breaking exceptions
            if args.exc_type in [
                exceptions.InvalidConfig, exceptions.RouteNotFound, exceptions.InvalidRoutes,
                exceptions.CandleNotFoundInDatabase
            ]:
                click.clear()
                print(f"{'=' * 30} EXCEPTION TRACEBACK:")
                traceback.print_tb(args.exc_traceback, file=sys.stdout)
                print("=" * 73)
                print(
                    '\n',
                    jh.color('Uncaught Exception:', 'red'),
                    jh.color(f'{args.exc_type.__name__}: {args.exc_value}', 'yellow')
                )
                return

            # send notifications if it's a live session
            if jh.is_live():
                jesse_logger.error(
                    f'{args.exc_type.__name__}: { args.exc_value}'
                )

            if jh.is_live() or jh.is_collecting_data():
                logging.error("Uncaught Exception:",
                              exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            else:
                print(f"{'=' * 30} EXCEPTION TRACEBACK:")
                traceback.print_tb(args.exc_traceback, file=sys.stdout)
                print("=" * 73)
                print(
                    '\n',
                    jh.color('Uncaught Exception:', 'red'),
                    jh.color(f'{args.exc_type.__name__}: {args.exc_value}', 'yellow')
                )

            if jh.is_paper_trading():
                print(
                    jh.color(
                        'An uncaught exception was raised. Check the log file at:\nstorage/logs/paper-trade.txt',
                        'red'
                    )
                )
            elif jh.is_livetrading():
                print(
                    jh.color(
                        'An uncaught exception was raised. Check the log file at:\nstorage/logs/live-trade.txt',
                        'red'
                    )
                )
            elif jh.is_collecting_data():
                print(
                    jh.color(
                        'An uncaught exception was raised. Check the log file at:\nstorage/logs/collect.txt',
                        'red'
                    )
                )

        threading.excepthook = handle_thread_exception


# create a Click group
@click.group()
@click.version_option(pkg_resources.get_distribution("jesse").version)
def cli() -> None:
    pass


@cli.command()
@click.argument('exchange', required=True, type=str)
@click.argument('symbol', required=True, type=str)
@click.argument('start_date', required=True, type=str)
@click.option('--skip-confirmation', is_flag=True,
              help="Will prevent confirmation for skipping duplicates")
def import_candles(exchange: str, symbol: str, start_date: str, skip_confirmation: bool) -> None:
    """
    imports historical candles from exchange
    """
    validate_cwd()
    from jesse.config import config
    config['app']['trading_mode'] = 'import-candles'

    register_custom_exception_handler()

    from jesse.services import db

    from jesse.modes import import_candles_mode

    import_candles_mode.run(exchange, symbol, start_date, skip_confirmation)

    db.close_connection()


@cli.command()
@click.argument('start_date', required=True, type=str)
@click.argument('finish_date', required=True, type=str)
@click.option('--debug/--no-debug', default=False,
              help='Displays logging messages instead of the progressbar. Used for debugging your strategy.')
@click.option('--csv/--no-csv', default=False,
              help='Outputs a CSV file of all executed trades on completion.')
@click.option('--json/--no-json', default=False,
              help='Outputs a JSON file of all executed trades on completion.')
@click.option('--fee/--no-fee', default=True,
              help='You can use "--no-fee" as a quick way to set trading fee to zero.')
@click.option('--chart/--no-chart', default=False,
              help='Generates charts of daily portfolio balance and assets price change. Useful for a visual comparision of your portfolio against the market.')
@click.option('--tradingview/--no-tradingview', default=False,
              help="Generates an output that can be copy-and-pasted into tradingview.com's pine-editor too see the trades in their charts.")
@click.option('--full-reports/--no-full-reports', default=False,
              help="Generates QuantStats' HTML output with metrics reports like Sharpe ratio, Win rate, Volatility, etc., and batch plotting for visualizing performance, drawdowns, rolling statistics, monthly returns, etc.")
def backtest(start_date: str, finish_date: str, debug: bool, csv: bool, json: bool, fee: bool, chart: bool,
             tradingview: bool, full_reports: bool) -> None:
    """
    backtest mode. Enter in "YYYY-MM-DD" "YYYY-MM-DD"
    """
    validate_cwd()


    from jesse.config import config
    config['app']['trading_mode'] = 'backtest'

    register_custom_exception_handler()

    from jesse.services import db
    from jesse.modes import backtest_mode
    from jesse.services.selectors import get_exchange

    # debug flag
    config['app']['debug_mode'] = debug

    # fee flag
    if not fee:
        for e in config['app']['trading_exchanges']:
            config['env']['exchanges'][e]['fee'] = 0
            get_exchange(e).fee = 0

    # #Profiler Hack
    # import cProfile, pstats
    # profiler = cProfile.Profile()
    # profiler.enable()

    backtest_mode.run(start_date, finish_date, chart=chart, tradingview=tradingview, csv=csv,
                      json=json, full_reports=full_reports)

    # profiler.disable()
    # stats = pstats.Stats(profiler).sort_stats('cumtime')
    # stats.print_stats()

    db.close_connection()

@cli.command()
@click.argument('start_date', required=True, type=str)
@click.argument('finish_date', required=True, type=str)
@click.option('--debug/--no-debug', default=False,
              help='Displays logging messages instead of the progressbar. Used for debugging your strategy.')
@click.option('--csv/--no-csv', default=False,
              help='Outputs a CSV file of all executed trades on completion.')
@click.option('--json/--no-json', default=False,
              help='Outputs a JSON file of all executed trades on completion.')
@click.option('--fee/--no-fee', default=True,
              help='You can use "--no-fee" as a quick way to set trading fee to zero.')
@click.option('--chart/--no-chart', default=False,
              help='Generates charts of daily portfolio balance and assets price change. Useful for a visual comparision of your portfolio against the market.')
@click.option('--tradingview/--no-tradingview', default=False,
              help="Generates an output that can be copy-and-pasted into tradingview.com's pine-editor too see the trades in their charts.")
@click.option('--full-reports/--no-full-reports', default=False,
              help="Generates QuantStats' HTML output with metrics reports like Sharpe ratio, Win rate, Volatility, etc., and batch plotting for visualizing performance, drawdowns, rolling statistics, monthly returns, etc.")
def backtest2(start_date: str, finish_date: str, debug: bool, csv: bool, json: bool, fee: bool, chart: bool,
             tradingview: bool, full_reports: bool) -> None:
    """
    backtest2 mode. Enter in "YYYY-MM-DD" "YYYY-MM-DD"
    """
    validate_cwd()


    from jesse.config import config
    config['app']['trading_mode'] = 'backtest'

    register_custom_exception_handler()

    from jesse.services import db
    from jesse.modes import backtest2_mode
    from jesse.services.selectors import get_exchange

    # debug flag
    config['app']['debug_mode'] = debug

    # fee flag
    if not fee:
        for e in config['app']['trading_exchanges']:
            config['env']['exchanges'][e]['fee'] = 0
            get_exchange(e).fee = 0

    # #Profiler Hack
    # import cProfile, pstats
    # profiler = cProfile.Profile()
    # profiler.enable()

    backtest2_mode.run(start_date, finish_date, chart=chart, tradingview=tradingview, csv=csv,
                      json=json, full_reports=full_reports)

    # profiler.disable()
    # stats = pstats.Stats(profiler).sort_stats('cumtime')
    # stats.print_stats()

    db.close_connection()


@cli.command()
@click.argument('start_date', required=True, type=str)
@click.argument('finish_date', required=True, type=str)
@click.argument('optimal_total', required=True, type=int)
@click.option(
    '--cpu', default=0, show_default=True,
    help='The number of CPU cores that Jesse is allowed to use. If set to 0, it will use as many as is available on your machine.')
@click.option(
    '--debug/--no-debug', default=False,
    help='Displays detailed logs about the genetics algorithm. Use it if you are interested int he genetics algorithm.'
)
@click.option('--csv/--no-csv', default=False, help='Outputs a CSV file of all DNAs on completion.')
@click.option('--json/--no-json', default=False, help='Outputs a JSON file of all DNAs on completion.')
def optimize(start_date: str, finish_date: str, optimal_total: int, cpu: int, debug: bool, csv: bool,
             json: bool) -> None:
    """
    tunes the hyper-parameters of your strategy
    """
    validate_cwd()
    from jesse.config import config
    config['app']['trading_mode'] = 'optimize'

    register_custom_exception_handler()

    # debug flag
    config['app']['debug_mode'] = debug

    from jesse.modes.optimize_mode import optimize_mode

    optimize_mode(start_date, finish_date, optimal_total, cpu, csv, json)

@cli.command()
@click.argument('start_date', required=True, type=str)
@click.argument('finish_date', required=True, type=str)
@click.argument('optimal_total', required=True, type=int)
@click.option(
    '--cpu', default=0, show_default=True,
    help='The number of CPU cores that Jesse is allowed to use. If set to 0, it will use as many as is available on your machine.')
@click.option(
    '--debug/--no-debug', default=False,
    help='Displays detailed logs about the genetics algorithm. Use it if you are interested int he genetics algorithm.'
)
@click.option('--csv/--no-csv', default=False, help='Outputs a CSV file of all DNAs on completion.')
@click.option('--json/--no-json', default=False, help='Outputs a JSON file of all DNAs on completion.')
def optimize2(start_date: str, finish_date: str, optimal_total: int, cpu: int, debug: bool, csv: bool,
             json: bool) -> None:
    """
    tunes the hyper-parameters of your strategy
    """
    validate_cwd()
    from jesse.config import config
    config['app']['trading_mode'] = 'optimize'

    register_custom_exception_handler()

    # debug flag
    config['app']['debug_mode'] = debug

    from jesse.modes.optimize2_mode import optimize2_mode

    optimize2_mode(start_date, finish_date, optimal_total, cpu, csv, json)

@cli.command()
@click.argument('start_date', required=True, type=str)
@click.argument('finish_date', required=True, type=str)
@click.argument('optimal_total', required=True, type=int)
@click.option(
    '--cpu', default=0, show_default=True,
    help='The number of CPU cores that Jesse is allowed to use. If set to 0, it will use as many as is available on your machine.')
@click.option(
    '--debug/--no-debug', default=False,
    help='Displays detailed logs about the genetics algorithm. Use it if you are interested int he genetics algorithm.'
)
@click.option('--csv/--no-csv', default=False, help='Outputs a CSV file of all DNAs on completion.')
@click.option('--json/--no-json', default=False, help='Outputs a JSON file of all DNAs on completion.')
def optimize3(start_date: str, finish_date: str, optimal_total: int, cpu: int, debug: bool, csv: bool,
             json: bool) -> None:
    """
    tunes the hyper-parameters of your strategy
    """
    validate_cwd()
    from jesse.config import config
    config['app']['trading_mode'] = 'optimize'

    register_custom_exception_handler()

    # debug flag
    config['app']['debug_mode'] = debug

    from jesse.modes.optimize3_mode import optimize3_mode

    #optimize3_init_worker(start_date, finish_date, optimal_total)

    optimize3_mode(start_date, finish_date, optimal_total, cpu, csv, json)



########################################

@cli.command()
@click.argument('start_date', required=True, type=str)
@click.argument('finish_date', required=True, type=str)
@click.argument('optimal_total', required=True, type=int)
@click.option(
    '--cpu', default=0, show_default=True,
    help='The number of CPU cores that Jesse is allowed to use. If set to 0, it will use as many as is available on your machine.')
@click.option(
    '--debug/--no-debug', default=False,
    help='Displays detailed logs about the genetics algorithm. Use it if you are interested int he genetics algorithm.'
)
@click.option('--csv/--no-csv', default=False, help='Outputs a CSV file of all DNAs on completion.')
@click.option('--json/--no-json', default=False, help='Outputs a JSON file of all DNAs on completion.')
def walkforward(start_date: str, finish_date: str, optimal_total: int, cpu: int, debug: bool, csv: bool,
             json: bool) -> None:
    """
    tunes the hyper-parameters of your strategy
    """
    validate_cwd()
    from jesse.config import config
    config['app']['trading_mode'] = 'optimize'

    register_custom_exception_handler()

    # debug flag
    config['app']['debug_mode'] = debug

    train_month = 2
    test_month = 1
    inc_month = 1

    print (f" {start_date} - {finish_date}")

    a_start_date = arrow.get(start_date, 'YYYY-MM-DD')
    a_finish_date = arrow.get(finish_date, 'YYYY-MM-DD')
    i_start_date = a_start_date
    i_finish_date = i_start_date.shift(months = train_month + test_month)


    # from jesse.modes.optimize2_mode import optimize2_mode

    # optimize2_mode(start_date, finish_date, optimal_total, cpu, csv, json)

    from jesse.modes.optimizewf_mode import optimizewf_mode

    optimizewf_mode(start_date, finish_date, optimal_total, cpu, csv, json, train_month, test_month, inc_month)

@app.task
def init_worker(start_date: str, finish_date: str, optimal_total: int) -> None:
    """
    init worker
    """
    

    # return os.getcwd()
    #, cpu_cores: int, csv: bool, json: bool
    cpu_cores = 1
    csv = False
    json = False
    validate_cwd()
    from jesse.config import config
    from jesse.modes.optimize3_mode import optimize3_init_worker
    config['app']['trading_mode'] = 'optimize'

    register_custom_exception_handler()

    # debug flag
    config['app']['debug_mode'] = False

    from jesse.modes.optimize3_mode import optimize3_mode

    optimize3_init_worker(start_date, finish_date, optimal_total)
    #, 1, csv, json)
    return "Inited"

@app.task
def run_worker(dna:str) -> None:
    """
    run worker
    """
    global _test_value
    from jesse.modes.optimize3_mode import optimize3_run_worker
    return optimize3_run_worker(dna)

@cli.command()
@click.argument('name', required=True, type=str)
def make_strategy(name: str) -> None:
    """
    generates a new strategy folder from jesse/strategies/ExampleStrategy
    """
    validate_cwd()
    from jesse.config import config

    config['app']['trading_mode'] = 'make-strategy'

    register_custom_exception_handler()

    from jesse.services import strategy_maker

    strategy_maker.generate(name)


@cli.command()
@click.argument('name', required=True, type=str)
def make_project(name: str) -> None:
    """
    generates a new strategy folder from jesse/strategies/ExampleStrategy
    """
    from jesse.config import config

    config['app']['trading_mode'] = 'make-project'

    register_custom_exception_handler()

    from jesse.services import project_maker

    project_maker.generate(name)


@cli.command()
@click.option('--dna/--no-dna', default=False,
              help='Translates DNA into parameters. Used in optimize mode only')
def routes(dna: bool) -> None:
    """
    lists all routes
    """
    validate_cwd()
    from jesse.config import config

    config['app']['trading_mode'] = 'routes'

    register_custom_exception_handler()

    from jesse.modes import routes_mode

    routes_mode.run(dna)


live_package_exists = True
try:
    import jesse_live
except ModuleNotFoundError:
    live_package_exists = False
if live_package_exists:
    # @cli.command()
    # def collect() -> None:
    #     """
    #     fetches streamed market data such as tickers, trades, and orderbook from
    #     the WS connection and stores them into the database for later research.
    #     """
    #     validate_cwd()
    #
    #     # set trading mode
    #     from jesse.config import config
    #     config['app']['trading_mode'] = 'collect'
    #
    #     register_custom_exception_handler()
    #
    #     from jesse_live.live.collect_mode import run
    #
    #     run()


    @cli.command()
    @click.option('--testdrive/--no-testdrive', default=False)
    @click.option('--debug/--no-debug', default=False)
    @click.option('--dev/--no-dev', default=False)
    def live(testdrive: bool, debug: bool, dev: bool) -> None:
        """
        trades in real-time on exchange with REAL money
        """
        validate_cwd()

        # set trading mode
        from jesse.config import config
        config['app']['trading_mode'] = 'livetrade'
        config['app']['is_test_driving'] = testdrive

        register_custom_exception_handler()

        # debug flag
        config['app']['debug_mode'] = debug

        from jesse_live import init
        from jesse.services.selectors import get_exchange
        live_config = locate('live-config.config')

        # validate that the "live-config.py" file exists
        if live_config is None:
            jh.error('You\'re either missing the live-config.py file or haven\'t logged in. Run "jesse login" to fix it.', True)
            jh.terminate_app()

        # inject live config
        init(config, live_config)

        # execute live session
        from jesse_live.live_mode import run
        run(dev)


    @cli.command()
    @click.option('--debug/--no-debug', default=False)
    @click.option('--dev/--no-dev', default=False)
    def paper(debug: bool, dev: bool) -> None:
        """
        trades in real-time on exchange with PAPER money
        """
        validate_cwd()

        # set trading mode
        from jesse.config import config
        config['app']['trading_mode'] = 'papertrade'

        register_custom_exception_handler()

        # debug flag
        config['app']['debug_mode'] = debug

        from jesse_live import init
        from jesse.services.selectors import get_exchange
        live_config = locate('live-config.config')

        # validate that the "live-config.py" file exists
        if live_config is None:
            jh.error('You\'re either missing the live-config.py file or haven\'t logged in. Run "jesse login" to fix it.', True)
            jh.terminate_app()

        # inject live config
        init(config, live_config)

        # execute live session
        from jesse_live.live_mode import run
        run(dev)

    @cli.command()
    @click.option('--email', prompt='Email')
    @click.option('--password', prompt='Password', hide_input=True)
    def login(email: str, password: str) -> None:
        """
        (Initially) Logins to the website.
        """
        validate_cwd()

        # set trading mode
        from jesse.config import config
        config['app']['trading_mode'] = 'login'

        register_custom_exception_handler()

        from jesse_live.auth import login

        login(email, password)
