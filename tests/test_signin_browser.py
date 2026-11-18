"""`vm youtube-login` must never open the Chrome profile VideoMentor reads its YouTube login from.

Opening that profile lets Google refresh (rotate) its login, which cancels the copy the
background engine saved. Sign-in pages open in `signin_profile`, or the default browser.
"""

import webbrowser

import pytest

from videomentor import cli, youtube_api
from videomentor.config import Settings


@pytest.fixture
def opened(monkeypatch):
    """Record how the sign-in page was opened, and stop after opening it."""
    calls = {"chrome": [], "browser": []}

    def fake_run(cmd, **kwargs):
        calls["chrome"].append(cmd)

    def fake_login(open_url):
        open_url("https://accounts.google.com/o/oauth2/auth?x=1")
        raise youtube_api.SignInNeeded("stopped in test")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(webbrowser, "open", lambda url: calls["browser"].append(url))
    monkeypatch.setattr(youtube_api, "login", fake_login)
    return calls


def run_login(settings):
    with pytest.raises(SystemExit):
        cli.cmd_youtube_login(None, settings)


def test_sign_in_opens_the_signin_profile_not_the_watch_later_one(opened):
    run_login(Settings(watch_later_profile="Profile 14", signin_profile="Profile 1"))
    (cmd,) = opened["chrome"]
    assert "--profile-directory=Profile 1" in cmd
    assert not any("Profile 14" in part for part in cmd)
    assert opened["browser"] == []


def test_without_a_signin_profile_it_uses_the_default_browser(opened):
    run_login(Settings(watch_later_profile="Profile 14"))
    assert opened["chrome"] == []
    assert opened["browser"] == ["https://accounts.google.com/o/oauth2/auth?x=1"]


def test_signin_profile_defaults_to_empty():
    assert Settings().signin_profile == ""
