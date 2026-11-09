"""What a user installs is what runs. These pin the two things a source checkout hides:
the built distribution must carry every subpackage, and the gate's own CI job must be
able to tell a block from a crash."""
import fnmatch
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_distribution_ships_every_subpackage_the_cli_imports():
    """An explicit packages list shipped app/ without app/engine, so `pip install .`
    produced a program that crashed on import outside a source checkout."""
    setuptools_cfg = PYPROJECT["tool"]["setuptools"]
    assert "find" in setuptools_cfg["packages"], "packages must be found, not listed"
    include = setuptools_cfg["packages"]["find"]["include"]
    on_disk = {".".join(p.parent.relative_to(ROOT).parts)
               for top in ("app", "seismograph") for p in (ROOT / top).rglob("__init__.py")}
    assert {"app", "app.engine", "seismograph"} <= on_disk
    # setuptools matches each dotted package name against the include patterns
    unshipped = sorted(pkg for pkg in on_disk if not any(fnmatch.fnmatchcase(pkg, pat) for pat in include))
    assert unshipped == [], f"packages on disk that would not ship: {unshipped}"


def test_every_package_directory_has_an_init_so_it_can_be_found():
    missing = [str(d.relative_to(ROOT)) for d in (ROOT / "app").rglob("*")
               if d.is_dir() and d.name != "__pycache__" and any(d.glob("*.py"))
               and not (d / "__init__.py").is_file()]
    assert missing == []


def test_the_planted_defect_job_requires_a_block_verdict_not_just_exit_1():
    workflow = (ROOT / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
    assert 'grep -q "Seismograph gate: BLOCK"' in workflow
    assert 'cd "$RUNNER_TEMP/elsewhere"' in workflow, "must run the installed program, outside the checkout"
    assert "PYTHONPATH" not in workflow


def test_the_action_passes_inputs_through_the_environment():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    run_blocks = action.split("run:")[1:]
    assert all("${{" not in block.split("\n    - ")[0] for block in run_blocks), \
        "an input pasted into a run script is a shell injection vector"
    assert "PYTHONPATH" not in action


def test_a_callers_system_loads_from_the_working_directory_without_shadowing_app(tmp_path, monkeypatch):
    from app.gate_cli import resolve_sut

    (tmp_path / "their_eval.py").write_text(
        "class Sut:\n    def run(self, probe_input, t, rng):\n        return '{}'\n", encoding="utf-8")
    (tmp_path / "app").mkdir()                       # the caller has their own `app` package
    (tmp_path / "app" / "__init__.py").write_text("MINE = True\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(tmp_path)])
    sut = resolve_sut("their_eval:Sut")
    assert sut.run("x", 0, None) == "{}"
    assert sys.path[-1] == os.getcwd(), "appended, never prepended"
    import app

    assert not hasattr(app, "MINE"), "the installed app package must not be shadowed"
    sys.modules.pop("their_eval", None)
