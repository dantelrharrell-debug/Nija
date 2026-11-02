"""Regression tests for the Capacitor web entrypoint generator."""
import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "build_mobile_web.py"
spec = importlib.util.spec_from_file_location("build_mobile_web", MODULE)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_repo_template_compiles_with_existing_assets():
    result = builder.compile_entrypoint(
        builder.TEMPLATE.read_text(encoding="utf-8"), builder.STATIC
    )
    assert '<html' in result.lower()
    assert 'src="static/js/app.js"' in result
    assert 'href="static/css/style.css"' in result
    assert '../static/' not in result


def test_rejects_missing_packaged_assets(tmp_path):
    try:
        builder.compile_entrypoint('<html><script src="../static/js/absent.js"></script></html>', tmp_path)
    except ValueError as error:
        assert "Missing bundled assets" in str(error)
    else:
        raise AssertionError("Missing assets must block the build")


def test_rejects_server_template_interpolation(tmp_path):
    try:
        builder.compile_entrypoint('<html>{{ user_secret }}</html>', tmp_path)
    except ValueError as error:
        assert "template syntax" in str(error)
    else:
        raise AssertionError("Server template markers must block the build")


def test_local_assets_pass(tmp_path):
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    result = builder.compile_entrypoint(
        '<html><script src="../static/js/app.js?v=1"></script></html>', tmp_path
    )
    assert 'src="static/js/app.js?v=1"' in result


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            if name in {"test_rejects_missing_packaged_assets", "test_rejects_server_template_interpolation", "test_local_assets_pass"}:
                from tempfile import TemporaryDirectory
                with TemporaryDirectory() as folder:
                    test(Path(folder))
            else:
                test()
    print("mobile web bundle regressions: PASS")
