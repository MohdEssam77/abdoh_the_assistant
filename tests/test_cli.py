from abdoh.cli import main


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "usage: abdoh" in capsys.readouterr().out
