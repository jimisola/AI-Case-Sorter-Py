"""Developer environment overrides: .env loading, API base, TLS trust.

The insecure-TLS switch is the interesting part — it must apply for a loopback
backend and must NOT apply to anything else, however it is spelled.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from sorter import appenv


@pytest.fixture(autouse=True)
def _reset_warnings():
    """Warnings are one-shot per process; clear them between tests."""
    appenv._warned.clear()


# ----- .env parsing ----------------------------------------------------------


def test_parse_env_text_handles_comments_quotes_and_export() -> None:
    parsed = appenv.parse_env_text(
        "\n"
        "# a comment\n"
        "CASESORTER_API_BASE=https://localhost:7043/api\n"
        "  export QUOTED = 'value with spaces' \n"
        'DOUBLE="dq"\n'
        "novalue\n"
        "EMPTY=\n"
    )
    assert parsed == {
        "CASESORTER_API_BASE": "https://localhost:7043/api",
        "QUOTED": "value with spaces",
        "DOUBLE": "dq",
        "EMPTY": "",
    }


def test_load_dotenv_applies_file_without_clobbering_real_env(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "dev.env"
    env_file.write_text("CASESORTER_API_BASE=https://localhost:7043/api\nOTHER=x\n")
    monkeypatch.setenv("CASESORTER_ENV_FILE", str(env_file))
    monkeypatch.setenv("OTHER", "already-set")

    applied = appenv.load_dotenv()

    assert env_file in applied
    assert appenv.api_base() == "https://localhost:7043/api"
    # A real environment variable outranks the file.
    assert os.environ["OTHER"] == "already-set"


def test_load_dotenv_is_a_noop_without_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CASESORTER_ENV_FILE", str(tmp_path / "nope.env"))
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path / "data"))
    assert appenv.load_dotenv() == []
    assert appenv.api_base() == appenv.DEFAULT_API_BASE


def test_load_dotenv_survives_an_unreadable_file(tmp_path, monkeypatch) -> None:
    """A developer convenience must never stop the app from starting."""
    bad = tmp_path / "dir.env"
    bad.mkdir()                      # is_file() is False → skipped, not raised
    monkeypatch.setenv("CASESORTER_ENV_FILE", str(bad))
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path / "data"))
    assert appenv.load_dotenv() == []


# ----- api base --------------------------------------------------------------


def test_api_base_default_and_override(monkeypatch) -> None:
    assert appenv.api_base() == "https://www.reloadingrecipes.com/api"
    monkeypatch.setenv("CASESORTER_API_BASE", "https://localhost:7043/api/")
    assert appenv.api_base() == "https://localhost:7043/api"   # trailing / trimmed
    monkeypatch.setenv("CASESORTER_API_BASE", "   ")
    assert appenv.api_base() == appenv.DEFAULT_API_BASE        # blank → default


# ----- tls trust -------------------------------------------------------------


def test_tls_verify_defaults_to_system_trust() -> None:
    assert appenv.tls_verify() is True


def test_ca_bundle_is_used_when_it_exists(tmp_path, monkeypatch) -> None:
    pem = tmp_path / "devcert.pem"
    pem.write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setenv("CASESORTER_API_CA_BUNDLE", str(pem))
    assert appenv.tls_verify() == str(pem)


def test_missing_ca_bundle_falls_back_to_system_trust(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CASESORTER_API_CA_BUNDLE", str(tmp_path / "gone.pem"))
    assert appenv.tls_verify() is True


def test_ca_bundle_wins_over_insecure(tmp_path, monkeypatch) -> None:
    pem = tmp_path / "devcert.pem"
    pem.write_text("x")
    monkeypatch.setenv("CASESORTER_API_CA_BUNDLE", str(pem))
    monkeypatch.setenv("CASESORTER_API_INSECURE", "1")
    monkeypatch.setenv("CASESORTER_API_BASE", "https://localhost:7043/api")
    assert appenv.tls_verify() == str(pem)


def test_insecure_honoured_for_loopback(monkeypatch) -> None:
    monkeypatch.setenv("CASESORTER_API_INSECURE", "1")
    for base in (
        "https://localhost:7043/api",
        "https://127.0.0.1:7043/api",
        "https://127.0.1.5/api",
        "https://app.localhost/api",
        "https://[::1]:7043/api",
    ):
        monkeypatch.setenv("CASESORTER_API_BASE", base)
        appenv._warned.clear()
        assert appenv.tls_verify() is False, base


def test_insecure_ignored_for_remote_hosts(monkeypatch) -> None:
    """A stray CASESORTER_API_INSECURE can never weaken production traffic."""
    monkeypatch.setenv("CASESORTER_API_INSECURE", "1")
    for base in (
        appenv.DEFAULT_API_BASE,
        "https://evil.example.com/api",
        "https://localhost.evil.example.com/api",   # not a loopback host
    ):
        monkeypatch.setenv("CASESORTER_API_BASE", base)
        appenv._warned.clear()
        assert appenv.tls_verify() is True, base


def test_insecure_ignored_with_the_default_base(monkeypatch) -> None:
    monkeypatch.setenv("CASESORTER_API_INSECURE", "1")   # no base override at all
    assert appenv.tls_verify() is True


def test_insecure_flag_spellings(monkeypatch) -> None:
    monkeypatch.setenv("CASESORTER_API_BASE", "https://localhost/api")
    for value, expected in (
        ("1", False), ("true", False), ("TRUE", False), ("yes", False), ("on", False),
        ("0", True), ("false", True), ("", True), ("maybe", True),
    ):
        monkeypatch.setenv("CASESORTER_API_INSECURE", value)
        appenv._warned.clear()
        assert appenv.tls_verify() is expected, value


def test_describe_reports_the_effective_settings(tmp_path, monkeypatch) -> None:
    assert "system trust" in appenv.describe()
    monkeypatch.setenv("CASESORTER_API_BASE", "https://localhost:7043/api")
    monkeypatch.setenv("CASESORTER_API_INSECURE", "1")
    text = appenv.describe()
    assert "localhost:7043" in text and "DISABLED" in text


def test_warnings_are_emitted_once(capsys, monkeypatch) -> None:
    monkeypatch.setenv("CASESORTER_API_BASE", "https://localhost/api")
    monkeypatch.setenv("CASESORTER_API_INSECURE", "1")
    for _ in range(3):
        appenv.tls_verify()
    assert capsys.readouterr().err.count("TLS verification is DISABLED") == 1


# ----- wiring into the API client --------------------------------------------


def test_community_api_picks_up_the_override(monkeypatch) -> None:
    from sorter.community_api import API_BASE, CommunityApi

    class _Auth:
        def acquire_token_silent(self, scopes=None): return None

    class _Session:
        verify = True

    assert CommunityApi(auth=_Auth(), session=_Session()).base_url == API_BASE
    monkeypatch.setenv("CASESORTER_API_BASE", "https://localhost:7043/api/")
    assert CommunityApi(auth=_Auth(), session=_Session()).base_url == "https://localhost:7043/api"


def test_community_api_resolves_tls_trust(tmp_path, monkeypatch) -> None:
    from sorter.community_api import CommunityApi

    class _Auth:
        def acquire_token_silent(self, scopes=None): return None

    class _Session:
        verify = True

    pem = tmp_path / "devcert.pem"
    pem.write_text("x")
    monkeypatch.setenv("CASESORTER_API_CA_BUNDLE", str(pem))
    assert CommunityApi(auth=_Auth(), session=_Session()).verify == str(pem)


def test_explicit_verify_argument_wins(monkeypatch) -> None:
    from sorter.community_api import CommunityApi

    class _Auth:
        def acquire_token_silent(self, scopes=None): return None

    class _Session:
        verify = True

    monkeypatch.setenv("CASESORTER_API_INSECURE", "1")
    monkeypatch.setenv("CASESORTER_API_BASE", "https://localhost/api")
    assert CommunityApi(auth=_Auth(), session=_Session(), verify=True).verify is True


def test_env_file_candidate_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CASESORTER_ENV_FILE", str(tmp_path / "explicit.env"))
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path / "data"))
    candidates = appenv.env_file_candidates()
    assert candidates[0] == tmp_path / "explicit.env"
    assert candidates[1] == tmp_path / "data" / "config" / ".env"
    assert candidates[2] == Path(appenv.__file__).resolve().parent.parent / ".env"


def test_verify_is_passed_per_request_not_on_the_session(tmp_path, monkeypatch) -> None:
    """Regression guard: session.verify is not enough.

    requests lets REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE in the environment
    outrank ``session.verify``, so a session-level setting is silently ignored
    on any machine that sets one (corporate proxies do). Only a per-request
    ``verify=`` wins.
    """
    from tests.test_community_api import _FakeResp, _FakeSession, _api

    pem = tmp_path / "devcert.pem"
    pem.write_text("x")
    monkeypatch.setenv("CASESORTER_API_CA_BUNDLE", str(pem))

    s = _FakeSession()
    api = _api(s)
    url = f"{api.base_url}/Models/FetchWishList?communityModelId=uid-1"
    s.next_responses[url] = _FakeResp(json_data=["FC"])
    api.fetch_wish_list("uid-1")
    assert s.verify_args == [str(pem)]


def test_default_verify_stays_true_so_env_ca_bundles_still_work(tmp_path) -> None:
    """Passing True (not None) keeps requests' own env-bundle handling intact."""
    from tests.test_community_api import _FakeResp, _FakeSession, _api

    s = _FakeSession()
    api = _api(s)
    url = f"{api.base_url}/Models/FetchWishList?communityModelId=uid-1"
    s.next_responses[url] = _FakeResp(json_data=[])
    api.fetch_wish_list("uid-1")
    assert s.verify_args == [True]
