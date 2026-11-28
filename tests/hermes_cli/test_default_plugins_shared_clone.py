"""A default-plugin pass across many profile homes clones each catalog pin once.

An update with 80 profiles and two new default plugins cloned from GitHub 160 times. One pass now
clones each ``(repo, commit, subdir)`` once and gives every home its own copy of that checkout; each
home's install still runs whole: kill list, scan, catalog record, publish, enable, and a
``plugins.disabled`` entry still keeps the plugin off. Real catalog install path (real clones of
local repos, real config writes); only the https transport is redirected.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path

import pytest

import hermes_yaml as yaml
from tests.hermes_cli.plugin_worker_support import (
    isolated_python as isolated_python,  # noqa: PLC0414 -- the self-alias is load-bearing: it suppresses F811 for the pytest fixture parameter shadowing this import
    plugin_world as plugin_world,  # noqa: PLC0414 -- the self-alias is load-bearing: it suppresses F811 for the pytest fixture parameter shadowing this import
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _plugins(home: Path) -> dict:
    return (yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}).get("plugins") or {}


@pytest.fixture
def world(plugin_world, tmp_path, monkeypatch):
    """``(homes, entries, clones)``: five homes, catalog entries ``alpha``/``beta`` served from local repos
    and ``gamma`` whose remote is unreachable; *clones* lists every clone that reached a remote."""
    from hermes_cli import default_plugins, plugins_cmd, plugins_cmd_catalog
    from hermes_cli.plugin_catalog import PluginCatalogEntry
    monkeypatch.delenv("HERMES_DISABLE_LAZY_INSTALLS", raising=False)
    monkeypatch.setattr(default_plugins, "_live_catalog_unreachable", lambda: False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "systmp"))
    (tmp_path / "systmp").mkdir()
    repos, entries = {}, []
    for name in ("alpha", "beta", "gamma"):
        repo = tmp_path / "remotes" / name
        repo.mkdir(parents=True)
        _git(repo, "init", "-q", "-b", "main")
        (repo / "plugin.yaml").write_text(yaml.safe_dump({"name": name, "version": "1.0.0"}), encoding="utf-8")
        (repo / "__init__.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "v1")
        url = f"https://example.invalid/acme/{name}.git"
        repos[url] = repo
        entries.append(PluginCatalogEntry(name=name, repo=url, sha=_git(repo, "rev-parse", "HEAD"),
                                          description="d", maintainer="m", tier="official", default=True))
    by_name = {entry.name: entry for entry in entries}
    monkeypatch.setattr(plugins_cmd_catalog, "get_live_catalog_entry", by_name.get)
    clones: list[str] = []
    real = plugins_cmd._clone_plugin_repo

    def clone(dest, url, revision, subdir=None):
        clones.append(url.rsplit("/", 1)[-1].removesuffix(".git"))
        if url.endswith("/gamma.git"):
            raise plugins_cmd.PluginOperationError("fatal: unable to access remote", failure_class="clone_failed")
        return real(dest, repos[url].as_uri(), revision, subdir)
    monkeypatch.setattr(plugins_cmd, "_clone_plugin_repo", clone)
    homes = [plugin_world.home]
    for index in range(4):
        profile = plugin_world.home / "profiles" / f"p{index}"
        profile.mkdir(parents=True)
        (profile / "config.yaml").write_text("plugins:\n  enabled: []\n  disabled: []\n", encoding="utf-8")
        homes.append(profile)
    return homes, entries, clones


def test_one_pass_clones_each_pin_once_and_every_home_gets_the_same_install(world, tmp_path):
    from hermes_cli import default_plugins
    homes, entries, clones = world
    kept_off = homes[2]
    config = yaml.safe_load((kept_off / "config.yaml").read_text(encoding="utf-8"))
    config["plugins"]["disabled"] = ["beta"]
    (kept_off / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    summary = default_plugins._install_defaults_for_homes(homes, say=lambda _line: None, lock=nullcontext,
                                                          entries=entries)

    assert clones.count("alpha") == 1 and clones.count("beta") == 1, clones
    # A failed clone is not shared: every home tries the remote itself, and only that entry is owed.
    assert clones.count("gamma") == len(homes), clones
    assert sorted(summary["owed"]) == ["gamma"] * len(homes), summary
    assert summary["installed"].count("alpha") == len(homes)
    records = []
    assert summary["installed"].count("beta") == len(homes) - 1
    for home in homes:
        metadata = json.loads((home / "plugins" / ".install-metadata.json").read_text(encoding="utf-8"))
        # The home whose user disabled beta has it settled: it is recorded, never installed.
        names = ("alpha",) if home == kept_off else ("alpha", "beta")
        for name in names:
            assert (home / "plugins" / name / "plugin.yaml").is_file(), (home, name)
            records.append((name, json.dumps(metadata[name], sort_keys=True)))
        assert not (home / "plugins" / "gamma").exists()
        enabled = _plugins(home).get("enabled") or []
        assert "alpha" in enabled
        assert ("beta" in enabled) is (home != kept_off), (home, enabled)
    assert _plugins(kept_off)["disabled"] == ["beta"], "an unattended install never lifts plugins.disabled"
    assert not (kept_off / "plugins" / "beta").exists()
    by_name: dict[str, set[str]] = {}
    for name, record in records:
        by_name.setdefault(name, set()).add(record)
    assert all(len(variants) == 1 for variants in by_name.values()), by_name
    alpha = json.loads(next(iter(by_name["alpha"])))
    assert alpha["catalog"]["sha"] == alpha["catalog"]["pin"] == entries[0].sha
    from hermes_cli.plugins_cmd_install import _shared_clones
    assert _shared_clones.get() is None
    assert not list((tmp_path / "systmp").glob("hermes-plugin-clones-*")), "the shared clones outlived the pass"


def test_a_single_home_pass_clones_as_before(world, monkeypatch):
    from hermes_cli import default_plugins, plugins_cmd_install
    homes, entries, clones = world
    monkeypatch.setattr(plugins_cmd_install, "shared_clones", lambda: pytest.fail("one home needs no sharing"))

    summary = default_plugins._install_defaults_for_homes(homes[:1], say=lambda _line: None, lock=nullcontext,
                                                          entries=entries[:2])

    assert sorted(summary["installed"]) == ["alpha", "beta"] and not summary["owed"], summary
    assert sorted(clones) == ["alpha", "beta"]
