from click.testing import CliRunner
from pyadps.cli import init
from os import listdir


class TestRepoInit:
    def test_ok(self, tmp_path):
        result = CliRunner().invoke(init, [str(tmp_path)])  # type: ignore
        assert result.exit_code == 0
        assert set(listdir(tmp_path)) == {'adps_messages', 'adps_attachments'}

    def test_failed(self, tmp_path):
        result = CliRunner().invoke(init, [str(tmp_path)+'not_exists'])  # type: ignore
        assert result.exit_code == 2
        assert set(listdir(tmp_path)) == set()
