"""Metadata-only plugin members are keyed by content, so N profiles enabling one plugin build once.

An update that installed a default plugin (qqbot, weixin) into 80 profiles used to change the
member stamp 80 times and copy 80 plugin trees into each new generation; a member bound to its
tree (a build backend, uv package mode or ``tool.uv.sources``) still counts per installed path.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import pm.workspace as ws

QQBOT = (
    '[project]\nname = "hermes-qqbot"\nversion = "2.0.0"\nreadme = "README.md"\n'
    'description = "QQ Bot platform"\nrequires-python = ">=3.11"\n'
    'dependencies = ["httpx>=0.27", "aiohttp>=3.9"]\n'
    '[project.optional-dependencies]\nsilk = ["pilk>=0.2.4,<0.3"]\n'
)


def _profiles(tmp_path: Path, count: int = 10) -> list[tuple[Path, Path]]:
    """``(qqbot, weixin)`` per profile: a virtual pyproject with a readme and an extra, and a
    manifest-only plugin. Their code differs per profile; their dependency metadata does not."""
    pairs = []
    for index in range(count):
        plugins = tmp_path / f"profile-{index}" / "plugins"
        qqbot, weixin = plugins / "qqbot", plugins / "weixin"
        qqbot.mkdir(parents=True)
        weixin.mkdir()
        (qqbot / "plugin.yaml").write_text("name: qqbot\n", encoding="utf-8")
        (qqbot / "pyproject.toml").write_text(QQBOT, encoding="utf-8")
        (qqbot / "README.md").write_text(f"profile {index}\n", encoding="utf-8")
        (qqbot / "adapter.py").write_text(f"PROFILE = {index}\n", encoding="utf-8")
        (weixin / "plugin.yaml").write_text(
            f'name: weixin\ndescription: profile {index}\npip_dependencies: ["cryptography>=42"]\n',
            encoding="utf-8")
        (weixin / "adapter.py").write_text(f"PROFILE = {index}\n", encoding="utf-8")
        pairs.append((qqbot, weixin))
    return pairs


def test_profiles_sharing_metadata_only_plugins_share_one_stamp(tmp_path):
    pairs = _profiles(tmp_path)
    first = ws.members_stamp([*pairs[0]])
    assert first != ws.members_stamp([])
    for count in range(2, len(pairs) + 1):
        assert ws.members_stamp([plugin for pair in pairs[:count] for plugin in pair]) == first, count

    # Code, readme and description edits are not dependency inputs: no new generation.
    qqbot, weixin = pairs[3]
    (qqbot / "adapter.py").write_text("PROFILE = 'edited'\n", encoding="utf-8")
    (qqbot / "README.md").write_text("edited\n", encoding="utf-8")
    (weixin / "adapter.py").write_text("PROFILE = 'edited'\n", encoding="utf-8")
    everything = [plugin for pair in pairs for plugin in pair]
    assert ws.members_stamp(everything) == first


@pytest.mark.parametrize("edit", [
    ('"aiohttp>=3.9"', '"aiohttp>=3.10"'),
    ('pilk>=0.2.4,<0.3', 'pilk>=0.2.5,<0.3'),
    ('requires-python = ">=3.11"', 'requires-python = ">=3.12"'),
    ('version = "2.0.0"', 'version = "2.0.1"'),
])
def test_one_profile_changing_dependency_metadata_adds_its_own_member(tmp_path, edit):
    pairs = _profiles(tmp_path, 3)
    everything = [plugin for pair in pairs for plugin in pair]
    before = ws.members_stamp(everything)
    manifest = pairs[1][0] / "pyproject.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(*edit), encoding="utf-8")
    assert ws.members_stamp(everything) != before
    root = tmp_path / "generation"
    keys = {ws._workspace_member(plugin, root, identity=plugin).name for plugin in everything}
    assert len(keys) == 3  # the shared qqbot, the edited one, the shared weixin


def test_manifest_requirements_change_the_shared_stamp(tmp_path):
    pairs = _profiles(tmp_path, 2)
    everything = [plugin for pair in pairs for plugin in pair]
    before = ws.members_stamp(everything)
    manifest = pairs[0][1] / "plugin.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(">=42", ">=43"), encoding="utf-8")
    assert ws.members_stamp(everything) != before


def test_shared_virtual_member_snapshots_only_its_metadata(tmp_path):
    """One member for every profile, holding only the pyproject uv reads: no plugin code, and no
    readme/description pointing at files the snapshot does not carry."""
    pairs = _profiles(tmp_path)
    root = tmp_path / "generation"
    members = {ws._workspace_member(plugin, root, identity=plugin, extras=["silk"])
               for pair in pairs for plugin in pair}
    assert len(members) == 2
    qqbot = next(member for member in members if member.parent.name == "plugin-sources")
    assert sorted(path.name for path in qqbot.iterdir()) == ["pyproject.toml"]
    project = tomllib.loads((qqbot / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project == {"name": f"hermes-plugin-{qqbot.name}", "version": "2.0.0", "requires-python": ">=3.11",
                       "dependencies": ["httpx>=0.27", "aiohttp>=3.9"],
                       "optional-dependencies": {"silk": ["pilk>=0.2.4,<0.3"]}}
    assert [path.name for path in (root / "plugin-sources").iterdir()] == [qqbot.name]
    assert len(list((root / "plugin-deps").iterdir())) == 1


@pytest.mark.parametrize("bound", [
    '[build-system]\nrequires = []\nbuild-backend = "backend"\n',
    '[tool.uv]\npackage = true\n',
    '[tool.uv.sources]\nhttpx = { path = "vendor/httpx" }\n',
    '[tool.uv]\nindex-url = "https://example.invalid/simple"\n',
])
def test_members_bound_to_their_tree_stay_per_profile(tmp_path, bound):
    plugins = []
    for index in range(2):
        plugin = tmp_path / f"profile-{index}" / "plugins" / "bound"
        plugin.mkdir(parents=True)
        (plugin / "pyproject.toml").write_text(QQBOT + bound, encoding="utf-8")
        (plugin / "adapter.py").write_text("VALUE = 1\n", encoding="utf-8")
        plugins.append(plugin)
    one = ws.members_stamp(plugins[:1])
    both = ws.members_stamp(plugins)
    assert both != one
    (plugins[1] / "adapter.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert ws.members_stamp(plugins) != both, "a bound member's whole tree is a build input"
    root = tmp_path / "generation"
    members = [ws._workspace_member(plugin, root, identity=plugin) for plugin in plugins]
    assert members[0] != members[1]
    assert all((member / "adapter.py").is_file() for member in members)


def test_dynamic_metadata_stays_per_profile(tmp_path):
    plugins = []
    for index in range(2):
        plugin = tmp_path / f"profile-{index}" / "plugins" / "dyn"
        plugin.mkdir(parents=True)
        (plugin / "pyproject.toml").write_text(
            '[project]\nname = "dyn"\ndynamic = ["version"]\ndependencies = ["httpx"]\n', encoding="utf-8")
        plugins.append(plugin)
    assert ws.members_stamp(plugins) != ws.members_stamp(plugins[:1])
