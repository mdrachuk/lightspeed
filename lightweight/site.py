from __future__ import annotations

__all__ = ['Site']

import asyncio
from asyncio import gather
from collections import defaultdict
from concurrent.futures.thread import ThreadPoolExecutor
from functools import partial
from os import getcwd
from os.path import abspath
from pathlib import Path
from shutil import rmtree
from typing import overload, Union, Optional, List, Dict
from urllib.parse import urlparse, urljoin

from .content.content_ import Content
from .content.copies_ import copy
from .errors import AbsolutePathIncluded, IncludedDuplicate
from .files import paths, directory
from .generation import GenContext, GenTask
from .included import Includes, IncludedContent


class Site:
    """A static site for generation, which is basically a collection of [Content].

    Site is one of the few mutable Lightweight components. It is available to content during [write][Content.write],
    as a property of the [provided ctx][GenContext].

    The only required parameter is the URL of the site. Other parameters may be useful for different content types.

    The following code output to the `out` directory the following content:
    - two rendered Jinja 2 HTML templates;
    - CSS rendered from SCSS;
    - copies of `img` and `js` directories.

    ```
    site = Site('https://example.org/')

    site.include('index.html', jinja('index.html'))
    site.include('about.html', jinja('about.html'))
    site.include('css/style.css', sass('styles/main.scss'))
    site.include('img')
    site.include('js')

    site.generate(out='out')
    ```
    """
    url: str
    content: Includes
    title: Optional[str]

    def __init__(
            self,
            url: str,
            *,
            title: Optional[str] = None,
            content: Optional[Includes] = None,
    ):
        self.url = _check_site_url(url)
        self.title = title
        self.content = Includes() if not content else content

    @overload
    def include(self, location: str):
        """Include a file, a directory, or multiple files with a glob pattern."""

    @overload
    def include(self, location: str, content: Content):
        """Include the content at the provided location."""

    @overload
    def include(self, location: str, content: str):
        """Copy files from content to location."""

    def include(self, location: str, content: Union[Content, str, None] = None):
        """Include the content at the location.

        Note the content write is executed only upon calling [`Site.generate()`][Site.generate].

        The location cannot be absolute. It cannot start with a forward slash.

        During the include the `cwd` (current working directory) is recorded.
        The [content’s write][Content.write] will be executed from this directory.

        Check overloads for alternative signatures."""
        cwd = getcwd()
        if location.startswith('/'):
            raise AbsolutePathIncluded()
        if content is None:
            contents = {str(path): copy(path) for path in paths(location)}
            if not len(contents):
                raise FileNotFoundError(f'There were no files at paths: {location}')
            [self._include_content(path, content_, cwd) for path, content_ in contents.items()]
        elif isinstance(content, Content):
            self._include_content(location, content, cwd)
        elif isinstance(content, str):
            source = Path(content)
            if not source.exists():
                raise FileNotFoundError(f'File does not exist: {content}')
            self._include_content(location, copy(source), cwd)
        else:
            raise ValueError('Content, str, or None types are accepted as include parameter')

    def _include_content(self, location: str, content: Content, cwd: str):
        self._include(
            IncludedContent(
                location=location,
                content=content,
                cwd=cwd
            )
        )

    def _include(self, c: IncludedContent):
        if c.location in self.content:
            raise IncludedDuplicate(at=c.location)
        self.content.add(c)

    def generate(self, out: Union[str, Path] = 'out'):
        """Generate the site in directory provided as out.

        If the out directory does not exist — it will be created along with its whole hierarchy.

        If the out directory already exists – it will be deleted with all of it contents.
        """
        out = Path(abspath(out))
        if out.exists():
            rmtree(out)
        out.mkdir(parents=True, exist_ok=True)
        self._generate(out)

    def _generate(self, out: Path):
        ctx = self.create_ctx(out)
        tasks = defaultdict(list)  # type: Dict[str, List[GenTask]]
        all_tasks = list()  # type: List[GenTask]
        for ic in self.content:
            _tasks = ic.make_tasks(ctx)
            for task in _tasks:
                tasks[task.cwd].append(task)
            all_tasks.extend(_tasks)
        ctx.tasks = tuple(all_tasks)  # injecting tasks, for other content to have access to site structure

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        executor = ThreadPoolExecutor()

        async def schedule(task):
            return await loop.run_in_executor(executor, partial(task.content.write, task.path, task.ctx))

        for cwd, _tasks in tasks.items():
            with directory(cwd):
                writes = map(schedule, _tasks)
                loop.run_until_complete(gather(*writes, loop=loop))
        loop.close()

    def create_ctx(self, out: Path) -> GenContext:
        """Override for custom context types."""
        return GenContext(out=out, site=self)

    def __repr__(self):
        return f'<{type(self).__name__} title={self.title} url={self.url} at 0x{id(self):02x}>'

    def __truediv__(self, location: str) -> str:
        """Create a URL for the location at site.

        ```python
        site = Site('https://example.org/')

        url = site / 'resource/images/photo-1.jpeg'
        print(url) # https://example.org/resource/images/photo-1.jpeg
        ```
        """

        return urljoin(self.url, location)


def _check_site_url(url: str) -> str:
    url_parts = urlparse(url)
    if url_parts.scheme is None:
        raise ValueError('Missing scheme in Site URL.')
    if not url.endswith('/'):
        raise ValueError(f'Site URL ({url}) must end with a forward slash (/).')
    return url
