from __future__ import annotations

from pathlib import Path
from shutil import rmtree
from typing import overload, Union, Optional, Dict
from urllib.parse import urlparse

from lightweight.content import Content, ContentCollection
from lightweight.content.copy import FileCopy, DirectoryCopy
from lightweight.files import paths
from lightweight.path import Rendering, RenderPath


class Site(ContentCollection, Content):
    content: Dict[str, Content]

    def __init__(self,
                 *,
                 url: Optional[str] = None,
                 title: Optional[str] = None):
        super().__init__({}, self)
        self.title = title
        if url is not None:
            url_parts = urlparse(url)
            assert url_parts.scheme, 'Missing scheme in Site URL.'
        self.url = url

    @overload
    def include(self, path: str):
        """Include a file, a directory, or multiple files with a glob pattern."""

    @overload
    def include(self, path: str, content: Content):
        """Create a file at path with content."""

    @overload
    def include(self, path: str, content: Site):
        """Include all of site contents in provided the directory."""

    def include(self, path: str, content: Union[Content, str] = None):
        if path.startswith('/'):
            path = path[1:]
        if content is None:
            contents = {path: file_or_dir(path) for path in paths(path)}
            if not len(contents):
                raise FileNotFoundError()
            self.content.update(contents)
        else:
            self.content[path] = content

    def render(self, out: Union[str, Path] = 'out'):
        out = Path(out)
        if out.exists():
            rmtree(out)
        out.mkdir(parents=True, exist_ok=True)

        rendering = Rendering(out=out, site=self)
        rendering.perform()

    def write(self, path: RenderPath):
        rendering = Rendering(out=(path.ctx.out / path.relative_path).absolute(), site=self)
        rendering.perform()


def file_or_dir(path: Path):
    return FileCopy(path) if path.is_file() else DirectoryCopy(path)
