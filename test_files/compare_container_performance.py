import os
import subprocess
import shlex
from collections import defaultdict

from tabulate import tabulate

from ab_wrapper.runner import Runner
from ab_wrapper.config import Config
from ab_wrapper.parser import Parser
from ab_wrapper.collector import Collector
from typing import Dict, List


class ABConfig(Config):

    def __init__(self, config: Dict):
        # we don't want to load from file so don't call super
        self.config = {}
        data = config
        if self.DEFAULTS_KEY in data:
            self.defaults = {**self.defaults, **data[self.DEFAULTS_KEY]}

        for key, one_location in data.items():
            if key == self.DEFAULTS_KEY:
                continue
            self.config[key] = {**self.defaults, **one_location}
        self.config.update(config)
        self.check_config()


class ABRunner(Runner):

    def __init__(self, config: Config, parser: Parser, collector: Collector):
        super().__init__(config, parser, collector)
        open(self.CSV_DATA_FILE, 'w').close()
        self.ab_results = {}

    def compose_command(self, config_name: str) -> list:
        """
        ab -q -n 1000 -c 100 -T 'application/json' -prequestbody http://127.0.0.1:"$PORT""$URL" >/dev/null
        :param config_name:
        :return:
        """
        cmd = ['ab']
        options = self.config[config_name]
        cmd.append('-q ')
        cmd.append('-c ' + str(options['clients']))
        cmd.append('-n ' + str(options['count']))
        cmd.append('-T ' + str(options['content_type']))
        cmd.append('-p ' + str(options['request_body']))
        cmd.append(' ' + options['url'])

        return cmd

    @staticmethod
    def execute_command_whole_output(cmd: list) -> (str, str, int):
        process = subprocess.run(shlex.split(" ".join(cmd)), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 encoding='ascii',
                                 shell=False,
                                 timeout=100,
                                 env=os.environ.copy(),
                                 check=False,
                                 universal_newlines=True,
                                 bufsize=0)
        return process.stdout, process.stderr, int(process.returncode)

    def run(self):
        try:
            for key, config in self.config.items():
                command = self.compose_command(key)
                print('Running command ' + ' '.join(command))
                stdout, stderr, error_code = self.execute_command_whole_output(command)
                if error_code != 0:
                    print('An ap process failed with error code ' + str(error_code) + '!!!')
                    print(stderr)
                else:
                    self.ab_results = self.parser.parse_ab_result(stdout)

        except subprocess.TimeoutExpired:
            print("Timeout reached")


class TestContainer:
    DEFAULT_URI = "/items/"

    def __init__(self, port: int = 8000, uri: str = DEFAULT_URI):
        self.ab_parser = Parser()
        self.ab_collector = Collector()
        self.port = port
        self.uri = self._identify_uri(uri=uri)
        self.ab_raw_results = {}

    def _identify_uri(self, uri):
        if uri:
            uri = uri if uri.startswith('/') else f"/{uri}"
        else:
            uri = self.DEFAULT_URI
        return uri

    def _get_config(self):
        """
        Defaults: 'time', 'count', 'clients', 'keep-alive', 'url'
        :return:
        """
        return {
            "_defaults": {
                "time": 5,
                "clients": 100,
                "count": 100,  # 10000
                "content_type": "'application/json'",
                "request_body": os.path.abspath(
                    os.path.join(os.path.dirname(os.path.realpath(__file__)), 'requestbody')),
                "keep-alive": False,
                "url": f"http://127.0.0.1:{self.port}{self.uri}"}
        }

    def pre_warm(self):
        config = self._get_config()
        config["count"] = config.get("clients", 100)
        _ab_runner = ABRunner(ABConfig(config=config), Parser(), Collector())
        _ab_runner.run()

    def run(self):
        _ab_runner = ABRunner(ABConfig(config=self._get_config()), self.ab_parser, self.ab_collector)
        _ab_runner.run()
        self.ab_raw_results = _ab_runner.ab_results

    def get_results(self):
        _return = {}
        for key in ['failed_requests', 'rps', 'time_mean']:
            _return[key] = self.ab_raw_results.get(key)
        return _return


class CompareContainers:
    TEST_RUN_PER_CONTAINER = 1

    def __init__(self, test_config: Dict):
        self.test_config = test_config
        self.test_results = []

    def run_test(self):
        for container in self.test_config:
            port = container.get('port')
            name = container.get('name')
            uri = container.get('uri')
            baseline = container.get('name', False)
            container['results'] = self.test_container(port=port, uri=uri)
            self.test_results.append(container)

        print(self.test_results)

    def sum_test_results(self, results: list) -> dict:
        """
        IN:
        [{'failed_requests': 0, 'rps': 1280.72, 'time_mean': 78.081}]
        Out (in dict)
        | **Test attribute**    | **Test run 1** | **Test run 2** | **Test run 3** | **Average** | Difference to baseline [%] |
        |-----------------------|----------------|----------------|----------------|-------------|----------------------------|
        | Requests per second   | 686,21         | 689,44         | 674,9          | **683,52**  | -51,59                     |
        | Time per request [ms] | 145,728        | 145,044        | 148,17         | **146,31**  | 34,03                      |
        """
        pass

    @staticmethod
    def tabulate_data(headers: List[str], data: dict):
        """
        tabulate_data(
            headers=["Node name", "Last activity"],
            data=self.node_info.get_failing_nodes(),
        )
        :param headers:
        :param data:
        :return:
        """
        table_data = []
        for k, v in data.items():
            table_data.append([k, v])
        print(tabulate(table_data, headers=headers, tablefmt="grid"))

    def sum_container_results(self):
        """
        [{'name': 'base', 'port': 8000, 'baseline': True,
        'results': [{'failed_requests': 0, 'rps': 1280.72, 'time_mean': 78.081}]},
        {'name': 'app_one_base_middleware', 'port': 8001, 'baseline': False, 'results': [{'failed_requests': 0, 'rps': 917.87, 'time_mean': 108.948}]}, {'name': 'app_two_base_middlewares', 'port': 8002, 'baseline': False, 'results': [{'failed_requests': 0, 'rps': 612.07, 'time_mean': 163.379}]}]
        :return:
        """
        baseline = {}
        results = {}
        for container in self.test_results:
            if container.get('baseline'):
                baseline = self.sum_container_results(container.get('results'))
            else:
                results = self.sum_container_results(container.get('results'))

    def test_container(self, port, uri):
        _results = []
        for i in range(self.TEST_RUN_PER_CONTAINER):
            print(f"{i}. of {port} / {uri}")
            t = TestContainer(port=port, uri=uri)
            t.run()
            _results.append(t.get_results())
        return _results


test_config = [
    {
        "name": "base",
        "port": 8000,
        "baseline": True
    },
    {
        "name": "app_one_base_middleware",
        "port": 8001,
        "baseline": False
    },
    {
        "name": "app_two_base_middlewares",
        "port": 8002,
        "baseline": False
    }
]
p = CompareContainers(test_config)
p.run_test()
# exit()
# p = TestContainer()
# p.run()
# print(p.get_results())
