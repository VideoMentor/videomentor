import json
import plistlib
from pathlib import Path

from videomentor import cli
from videomentor.config import Settings


def make_dist(tmp_path):
    dist = tmp_path / "repo" / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>")
    (dist / "build.json").write_text(json.dumps({"build": "ABC.001", "version": "0.1.0"}))
    return dist


def test_launch_info_has_what_the_mac_app_needs(tmp_path, monkeypatch):
    monkeypatch.setenv("VM_HOME", str(tmp_path / "Lib"))
    (tmp_path / "Lib" / "web").mkdir(parents=True)
    (tmp_path / "Lib" / "web" / "build.json").write_text(json.dumps({"build": "9BA12CC7.001"}))
    info = cli.launch_info(Settings(pair_code="123456789012"))
    assert info["program"] == str(Path.home() / ".local/bin/vm")
    assert info["args"] == ["serve"]
    assert info["env"]["VM_HOME"] == str(tmp_path / "Lib")
    assert info["env"]["VM_WEB_DIST"] == str(tmp_path / "Lib" / "web")
    assert info["env"]["PYTHONUNBUFFERED"] == "1"
    assert "/opt/homebrew/bin" in info["env"]["PATH"].split(":")
    assert str(Path.home() / ".local/bin") in info["env"]["PATH"].split(":")
    assert info["log"] == str(tmp_path / "Lib" / "logs" / "serve.log")
    assert (info["host"], info["port"], info["pair_code"]) == ("127.0.0.1", 8791, "123456789012")
    assert info["build"] == "9BA12CC7.001" and info["version"]


def test_launch_info_build_is_empty_without_an_installed_web_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("VM_HOME", str(tmp_path / "Lib"))
    assert cli.launch_info(Settings())["build"] == ""


def test_install_service_uses_the_same_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("VM_HOME", str(tmp_path / "Lib"))
    dist = make_dist(tmp_path)
    plist_path = tmp_path / "LaunchAgents" / "x.plist"
    monkeypatch.setattr(cli, "LAUNCH_PLIST", plist_path)
    monkeypatch.setattr(cli, "web_dist", lambda: dist)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/fake/uv")
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    cli.cmd_install_service(None, Settings())
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["EnvironmentVariables"] == cli.launch_info(Settings())["env"]
    assert plist["ProgramArguments"] == [cli.launch_info(Settings())["program"], "serve"]
    assert ["/fake/uv", "tool", "install", "--force", "--reinstall"] == calls[0][:5]
    assert (tmp_path / "Lib" / "web" / "index.html").exists()


def test_install_command_installs_without_a_login_service(tmp_path, monkeypatch):
    monkeypatch.setenv("VM_HOME", str(tmp_path / "Lib"))
    dist = make_dist(tmp_path)
    monkeypatch.setattr(cli, "LAUNCH_PLIST", tmp_path / "LaunchAgents" / "x.plist")
    monkeypatch.setattr(cli, "web_dist", lambda: dist)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/fake/uv")
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    cli.main(["install"])
    assert [c[0] for c in calls] == ["/fake/uv"]  # no launchctl
    assert not (tmp_path / "LaunchAgents").exists()
    assert (tmp_path / "Lib" / "web" / "build.json").exists()


def test_launch_info_cli_prints_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VM_HOME", str(tmp_path / "Lib"))
    cli.main(["launch-info", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["args"] == ["serve"] and data["env"]["VM_HOME"] == str(tmp_path / "Lib")
    assert set(data) == {
        "program",
        "args",
        "env",
        "log",
        "port",
        "host",
        "pair_code",
        "version",
        "build",
    }
