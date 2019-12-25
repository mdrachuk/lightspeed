from os import chdir, getcwd
from pathlib import Path

import pytest
from jinja2 import TemplateNotFound

from lightweight import Site, jinja, Content, directory


def test_render_jinja(tmp_path: Path):
    src_location = 'resources/jinja/title.html'
    out_location = 'title.html'

    test_out = tmp_path / 'out'
    site = Site(url='https://example.com')

    site.include(out_location, jinja(src_location, title='99 reasons lightweight rules'))
    site.render(test_out)

    assert (test_out / out_location).exists()
    with open('expected/jinja/params.html') as expected:
        assert (test_out / out_location).read_text() == expected.read()


def test_render_jinja_file(tmp_path: Path):
    src_location = 'resources/jinja/file.html'
    out_location = 'jinja/file.html'

    test_out = tmp_path / 'out'
    site = Site(url='https://example.com')

    site.include(out_location, jinja(src_location))
    site.render(test_out)

    assert (test_out / out_location).exists()
    with open('expected/jinja/file.html') as expected:
        assert (test_out / out_location).read_text() == expected.read()


class NoopContent(Content):
    def write(self, path: Path):
        """"""


class TestWorkingDirectory:

    def setup_method(self, method):
        self.original_cwd = getcwd()

    def teardown_method(self, method):
        chdir(self.original_cwd)

    def test_dynamic_cwd(self, tmp_path: Path):
        assert jinja('templates/test.html')
        chdir('templates')
        assert jinja('test.html')
        with pytest.raises(TemplateNotFound):
            jinja('templates/test.html')


def test_resolves_sub_site_template_by_cwd(tmp_path: Path):
    site = Site()
    with directory('site'):
        subsite = Site()
        subsite.include('page.html', jinja('page.html'))
    site.include('subsite', subsite)
    site.render(out=tmp_path)

    with open('expected/subsite/page.html') as expected:
        assert (tmp_path / 'subsite' / 'page.html').read_text() == expected.read()


def test_url_filter(tmp_path: Path):
    site = Site()
    site.include('page.html', jinja('resources/url/test.html'))
    site.render(out=tmp_path)

    with open('expected/url/test.html') as expected:
        assert (tmp_path / 'page.html').read_text() == expected.read()


def test_relative_url_filter(tmp_path: Path):
    site = Site()
    subsite = Site()
    subsite.include('page.html', jinja('resources/url/nested.html'))
    site.include('subsite', subsite)
    site.render(out=tmp_path)

    with open('expected/url/nested.html') as expected:
        assert (tmp_path / 'subsite' / 'page.html').read_text() == expected.read()
