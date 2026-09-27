import os

from doc2sheet.cli import expand_inputs, main
from doc2sheet.config import Settings, load_dotenv


def test_expand_inputs_handles_folders_globs_and_duplicates(samples):
    from_folder = expand_inputs([str(samples)])
    assert len(from_folder) == 4
    from_glob = expand_inputs([str(samples / "*.pdf"), str(samples / "invoice_pixel_pine_eur.pdf")])
    assert len(from_glob) == 3  # duplicate removed


def test_cli_explains_missing_token(samples, monkeypatch, capsys, tmp_path):
    for var in ("DOC2SHEET_API_KEY", "HF_TOKEN", "OPENAI_API_KEY", "DOC2SHEET_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    assert main([str(samples)]) == 2
    assert "HF_TOKEN" in capsys.readouterr().err


def test_cli_no_inputs(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main([str(tmp_path / "nothing-*.pdf")]) == 2


def test_dotenv_does_not_override_real_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        '# comment\nDOC2SHEET_MODEL="from-file"\nexport DOC2SHEET_MAX_PAGES=7   # inline comment\n'
        "DOC2SHEET_TIMEOUT=5\nDOC2SHEET_REASONING_EFFORT='none'  # off\n"
    )
    monkeypatch.delenv("DOC2SHEET_MODEL", raising=False)
    monkeypatch.delenv("DOC2SHEET_MAX_PAGES", raising=False)
    monkeypatch.setenv("DOC2SHEET_TIMEOUT", "99")
    monkeypatch.delenv("DOC2SHEET_REASONING_EFFORT", raising=False)
    load_dotenv(env)
    settings = Settings.from_env(env_file=None)
    assert settings.model == "from-file"
    assert settings.max_pages == 7
    assert settings.timeout == 99.0
    assert settings.max_image_side == 1600 and settings.reasoning_effort == "none"
    for var in ("DOC2SHEET_MODEL", "DOC2SHEET_MAX_PAGES", "DOC2SHEET_REASONING_EFFORT"):
        os.environ.pop(var, None)
