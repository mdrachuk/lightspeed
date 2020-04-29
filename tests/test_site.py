from pathlib import Path

import pytest

from lightweight import Site
from lightweight.errors import AbsolutePathIncluded, IncludedDuplicate


def test_rewrite_out(tmp_path: Path):
    assert_site_render('resources/test_nested/test2/test3/test.html', 'resources/test_nested', tmp_path)
    assert_site_render('resources/test.html', 'resources/test.html', tmp_path)


def assert_site_render(src_location, content, tmp_path):
    with Path(src_location).open() as f:
        src_content = f.read()
    test_out = tmp_path / 'out'
    site = Site(url='https://example.org/')
    site.include(content)
    site.generate(test_out)
    assert (test_out / src_location).exists()
    assert (test_out / src_location).read_text() == src_content


def test_absolute_includes_not_allowed():
    site = Site('https://example.org/')
    with pytest.raises(AbsolutePathIncluded):
        site.include('/etc')


def test_site_location(tmp_path: Path):
    site = Site(url='https://example.org/')
    assert site / 'test.html' == 'https://example.org/test.html'
    assert site / '/test.html' == 'https://example.org/test.html'
    assert site / '/foo/bar' == 'https://example.org/foo/bar'


def test_site_include_duplicate():
    site = Site(url='https://example.org/')
    site.include('page', 'resources/test.html')
    with pytest.raises(IncludedDuplicate):
        site.include('page', 'site/index.html')
