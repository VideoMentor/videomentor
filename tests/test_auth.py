"""Pairing codes, the lockout, per-device sign-ins and keeping codes out of logs."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from videomentor import auth
from videomentor.api import COOKIE, create_app
from videomentor.config import Settings, load_settings, normalize_code


def app(code="1234-5678-9012"):
    return create_app(Settings(pair_code=code), run_worker=False)


def test_old_codes_are_upgraded_to_twelve_digits(vm_home):
    vm_home.mkdir(parents=True, exist_ok=True)
    (vm_home / "config.toml").write_text('pair_code = "F916D1E8"\n')
    code = load_settings().pair_code
    assert code != "F916D1E8" and len(normalize_code(code)) == 12 and normalize_code(code).isdigit()


def test_codes_match_with_or_without_dashes():
    assert auth.code_matches("1234 5678 9012", "1234-5678-9012")
    assert auth.code_matches("123456789012", "1234-5678-9012")
    assert not auth.code_matches("", "1234-5678-9012")
    assert not auth.code_matches("1234-5678-9013", "1234-5678-9012")


def test_each_device_gets_its_own_sign_in(conn):
    with TestClient(app()) as phone, TestClient(app()) as mac:
        assert phone.get("/pair?code=123456789012", follow_redirects=False).status_code == 303
        assert (
            mac.get(
                "/pair?code=1234-5678-9012",
                follow_redirects=False,
                headers={"user-agent": "Macintosh Chrome/1"},
            ).status_code
            == 303
        )
        assert phone.cookies[COOKIE] != mac.cookies[COOKIE]
        devices = phone.get("/api/devices").json()["devices"]
        assert len(devices) == 2 and sum(d["current"] for d in devices) == 1
        assert "Mac · Chrome" in [d["device"] for d in devices]
        # the stored value is a fingerprint, never the cookie itself
        stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
        assert phone.cookies[COOKIE] not in stored

        assert phone.post("/api/devices/sign-out-others").json() == {"signed_out": 1}
        assert mac.get("/api/status").status_code == 401
        assert phone.get("/api/status").status_code == 200
        me = phone.get("/api/devices").json()["devices"][0]["id"]
        assert phone.delete(f"/api/devices/{me}").status_code == 200
        assert phone.get("/api/status").status_code == 401
        assert phone.delete("/api/devices/not-an-id").status_code == 401  # signed out


def test_unused_sign_ins_expire(conn):
    with TestClient(app()) as c:
        c.get("/pair?code=123456789012", follow_redirects=False)
        old = (datetime.now(UTC) - timedelta(days=auth.SESSION_DAYS + 1)).isoformat()
        conn.execute("UPDATE sessions SET last_seen = ?", (old,))
        conn.commit()
        assert c.get("/api/status").status_code == 401
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_wrong_codes_lock_pairing_for_a_while(conn):
    with TestClient(app()) as c:
        for _ in range(auth.MAX_TRIES):
            assert c.get("/pair?code=0000-0000-0000").status_code == 401
        r = c.get("/pair?code=1234-5678-9012", follow_redirects=False)
        assert r.status_code == 429  # even the right code waits out the lockout
        assert "Too many wrong codes" in r.text


def test_lockout_window_slides():
    lock = auth.Lockout(tries=2, minutes=1)
    lock.fail(now=0)
    lock.fail(now=10)
    assert lock.wait_seconds(now=20) == 41
    assert lock.wait_seconds(now=61) == 0


def test_bearer_code_still_works_for_scripts(conn):
    with TestClient(app()) as c:
        assert (
            c.get("/api/status", headers={"Authorization": "Bearer 123456789012"}).status_code
            == 200
        )
        assert c.get("/api/status", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_pairing_codes_stay_out_of_the_access_log():
    f = auth.RedactPairCode()
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4", "GET", "/pair?code=1234-5678-9012", "1.1", 303), None)  # fmt: skip
    f.filter(rec)
    assert "1234" not in rec.getMessage() and "code=…" in rec.getMessage()


def test_bearer_guesses_count_toward_the_lockout(conn):
    with TestClient(app()) as c:
        for _ in range(auth.MAX_TRIES):
            assert c.get("/api/status", headers={"Authorization": "Bearer 0"}).status_code == 401
        assert (
            c.get("/api/status", headers={"Authorization": "Bearer 123456789012"}).status_code
            == 429
        )


def test_typed_codes_are_posted_and_odd_input_is_a_wrong_try(conn):
    with TestClient(app()) as c:
        assert c.get("/pair?code=%C3%A9").status_code == 401  # é: no crash, counted
        r = c.post("/pair", data={"code": "1234 5678 9012"}, follow_redirects=False)
        assert r.status_code == 303 and c.get("/api/status").status_code == 200
        assert r.headers["referrer-policy"] == "no-referrer"


def test_lockout_attempt_is_one_step():
    lock = auth.Lockout(tries=2, minutes=1)
    assert lock.attempt(False, now=0) == 0
    assert lock.attempt(True, now=1) == 0  # a right code never counts
    assert lock.attempt(False, now=2) == 0
    assert lock.attempt(True, now=3) > 0  # locked: even the right code waits


def test_a_new_code_works_without_a_restart_and_isnt_overwritten(conn, vm_home):
    import os
    import time as t

    from videomentor.config import load_settings, new_pair_code, save_settings

    s = load_settings()
    with TestClient(create_app(s, run_worker=False)) as c:
        fresh = load_settings()
        fresh.pair_code = new_pair_code()
        save_settings(fresh)
        later = t.time() + 5
        os.utime(vm_home / "config.toml", (later, later))
        assert c.get(f"/pair?code={fresh.pair_code}", follow_redirects=False).status_code == 303
        c.put(
            "/api/settings",
            json={"signal_areas": ["A"], "skill_map": ["B"], "signal_guidance": "C"},
        )
        assert load_settings().pair_code == fresh.pair_code


def test_scripts_cannot_sign_out_every_device(conn):
    with TestClient(app()) as c:
        r = c.post("/api/devices/sign-out-others", headers={"Authorization": "Bearer 123456789012"})
        assert r.status_code == 400
