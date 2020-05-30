#!/usr/bin/env python
"""
Lightweight CLI.

Access CLI help via:
```bash
lw --help
```
or
```
python -m lightweight.lw --help
```

Initialize project using:
```bash
lw init example_project --url https://example.org
```
Additional help:
```bash
lw init --help
```

Start a server for the project:
```bash
lw serve website:dev
```
Additional help:
```bash
lw serve --help
```
"""
import asyncio
import inspect
import multiprocessing as mp
import os
import re
import sys
import traceback
from argparse import ArgumentParser
from asyncio import gather
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from logging import getLogger
from pathlib import Path
from random import randint, sample
from typing import Any, Optional, Callable

from slugify import slugify  # type: ignore

from lightweight import Site, jinja, directory, jinja_env, paths
from lightweight.errors import InvalidCommand
from lightweight.server import DevServer, LiveReloadServer

logger = getLogger('lightweight')


class Process(mp.Process):
    """https://stackoverflow.com/a/33599967/8677389"""

    def __init__(self, *args, **kwargs):
        mp.Process.__init__(self, *args, **kwargs)
        self._pconn, self._cconn = mp.Pipe()
        self._exception = None
        self._traceback = None

    def run(self):
        try:
            mp.Process.run(self)
            self._cconn.send(None)
        except Exception as e:
            tb = traceback.format_exc()
            self._cconn.send((e, tb))
            # raise e  # You can still rise this exception if you need to

    @property
    def exception(self):
        self._recv_exc()
        return self._exception

    def _recv_exc(self):
        if self._pconn.poll():
            recv = self._pconn.recv()
            if recv is not None:
                self._exception, self._traceback = recv

    @property
    def traceback(self):
        self._recv_exc()
        return self._traceback


class FailedGeneration(Exception):
    pass


class Generator:

    def __init__(self, func_file: Path, func_name: str, *, source: str, out: str, host: str, port: int):
        self.func_file = func_file
        self.func_name = func_name
        self.source = source
        self.out = out
        self.host = host
        self.port = port
        self._loaded = False

    @property
    def url(self) -> str:
        return f'http://{self.host}:{self.port}/'

    def generate(self):
        def worker():
            func = self.load_executable()

            site = func(self.url)
            if not hasattr(site, 'generate') or not positional_args_count(site.generate, equals=1):
                raise InvalidCommand(f'"{self.func_name}" did not return an instance of Site '
                                     f'with a "site.generate(out)" method.')
            site.generate(self.out)

        p = Process(target=worker)
        p.start()
        p.join()
        if p.exception:
            if isinstance(p.exception, InvalidCommand):
                raise p.exception
            else:
                logger.error(p.traceback)
                raise FailedGeneration() from p.exception

    def load_executable(self):
        module = load_module(self.func_file)
        try:
            func = getattr(module, self.func_name)
        except AttributeError as e:
            raise InvalidCommand(
                f'Module "{module.__name__}" ({module.__file__}) is missing function "{self.func_name}".') from e
        if not callable(func):
            raise InvalidCommand(f'"{module.__name__}:{self.func_name}" member is not callable.')
        if not positional_args_count(func, equals=1):
            raise InvalidCommand(f'"{module.__name__}:{self.func_name}" '
                                 f'cannot be called as `{self.func_name}("{self.url}")`.')
        return func


def positional_args_count(func: Callable, *, equals: int) -> bool:
    """
    if not positional_args_count(func, equals=2):
        ...
    """
    count = equals
    params = inspect.signature(func).parameters
    return len(params) >= count and all(p.default != p.empty for p in list(params.values())[count:])


def load_module(p: Path) -> Any:
    module_name = p.name.rsplit('.')[0]
    with sys_path_starting(with_=p.parent):
        loader = SourceFileLoader(module_name, str(p))
        spec = spec_from_loader(module_name, loader, is_package=False)
        module = module_from_spec(spec)
        loader.exec_module(module)
    return module


@contextmanager
def sys_path_starting(with_: Path):
    location = str(with_)
    sys.path.insert(0, location)
    yield
    sys.path.remove(location)


def start_server(func_file: Path, func_name: str,
                 *, source: str, out: str, host: str, port: int, enable_reload: bool, loop=None):
    source = os.path.abspath(source)
    out = absolute_out(out, source)

    generator = Generator(func_file, func_name, source=source, host=host, port=port, out=out)
    generator.generate()

    if not enable_reload:
        server = DevServer(out)
    else:
        server = LiveReloadServer(out, watch=source, regenerate=generator.generate, ignored=[out])

    logger.info(f'Runner: {func_name} in {func_file}')
    logger.info(f'Sources: {source}')
    logger.info(f'Out: {out}')
    logger.info(f'Starting server at: "http://{host}:{port}"')

    loop = loop or asyncio.new_event_loop()
    server.serve(host=host, port=port, loop=loop)
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        print()  # new line after ^C
        logger.info('Stopping the server.')
        server.shutdown(loop)
        pending = asyncio.all_tasks(loop=loop)
        loop.run_until_complete(gather(*pending, loop=loop))
        loop.stop()
        logger.info('Server stopped.')


def absolute_out(out: Optional[str], abs_source: str) -> str:
    if out is None:
        return str(Path(abs_source) / 'out')
    return os.path.abspath(out)


@dataclass(frozen=True)
class Color(object):
    """A color from red, green and blue."""
    r: int
    g: int
    b: int

    @classmethod
    def bright(cls):
        """Create a new bright color."""
        values = [randint(120, 255), randint(120, 255), randint(0, 50)]
        rgb = sample(values, 3)
        return cls(*rgb)

    def css(self, alpha=None) -> str:
        "A string representation of color which can be used in CSS."
        if alpha is not None:
            return f'rgba({self.r}, {self.g}, {self.b}, {alpha})'
        return f'rgb({self.r}, {self.g}, {self.b})'


def quickstart(location: str, title: Optional[str]):
    path = Path(location)
    path.mkdir(parents=True, exist_ok=True)

    abs_out = os.path.abspath(path)
    if not title:
        title = Path(abs_out).name
    title_slug = slugify_title(title)

    template_location = Path(__file__).parent / 'project-template'

    with directory(template_location), custom_jinja_tags():
        site = Site(title=title)

        [site.include(str(p), jinja(p)) for p in paths('_templates_/**/*.html')]
        [site.include(str(p), jinja(p)) for p in paths('*.html')]
        site.include('website.py', jinja('website.py.j2', title_slug=title_slug))
        site.include('requirements.txt', jinja('requirements.txt.j2', version=lw_version()))
        site.include('posts')
        [site.include(str(p), jinja(p)) for p in paths('styles/**/*css') if p.name != 'attributes.scss']
        site.include('styles/attributes.scss', jinja('styles/attributes.scss', accent=Color.bright()))
        site.include('js')
        site.include('img')

        site.generate(abs_out)

    logger.info(f'Lightweight project initialized in: {abs_out}')


@contextmanager
def custom_jinja_tags():
    original_tags = (jinja_env.block_start_string, jinja_env.block_end_string,
                     jinja_env.variable_start_string, jinja_env.variable_end_string,
                     jinja_env.comment_start_string, jinja_env.comment_end_string)
    jinja_env.block_start_string = '{?'
    jinja_env.block_end_string = '?}'
    jinja_env.variable_start_string = '{!'
    jinja_env.variable_end_string = '!}'
    jinja_env.comment_start_string = '{//'
    jinja_env.comment_end_string = '//}'

    yield

    (jinja_env.block_start_string, jinja_env.block_end_string,
     jinja_env.variable_start_string, jinja_env.variable_end_string,
     jinja_env.comment_start_string, jinja_env.comment_end_string) = original_tags


def slugify_title(title):
    title_slug = slugify(title, separator='_')
    title_slug = re.findall('[a-z][a-z0-9_]+$', title_slug)[0]  # in code nothing can start with digits
    title_slug.replace('\'', '’')
    return title_slug


def argument_parser():
    parser = ArgumentParser(description='Lightweight -- "code over configuration" static site generator. \n'
                                        'https://drach.uk/lightweight')

    subparsers = parser.add_subparsers()

    add_init_cli(subparsers)
    add_version_cli(subparsers)

    return parser


def add_init_cli(subparsers):
    qs_parser = subparsers.add_parser(name='init', description='Generate Lightweight skeleton application')
    qs_parser.add_argument('location', type=str, help='the directory to initialize site generator in')
    qs_parser.add_argument('--url', type=str, help='the url of the generated site', required=True)
    qs_parser.add_argument('--title', type=str, help='the title of of the generated site')
    qs_parser.set_defaults(func=lambda args: quickstart(args.location,
                                                        url=args.url,
                                                        title=args.title,
                                                        ))


def add_version_cli(subparsers):
    version_parser = subparsers.add_parser(name='version')
    version_parser.set_defaults(func=lambda args: print(lw_version()))


def parse_args():
    args = argument_parser().parse_args()
    return args

def lw_version():
    from lightweight import __version__
    return __version__


def main():
    args = parse_args()
    if hasattr(args, 'func'):
        try:
            args.func(args)
        except InvalidCommand as error:
            logger.error(f'{type(error).__name__}: {str(error)}')
            exit(-1)
    else:
        argument_parser().parse_args(['--help'])


if __name__ == '__main__':
    main()
