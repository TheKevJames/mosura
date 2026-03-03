import warnings

import pytest

from mosura import config


def test_settings_normalizes_blank_mosura_user_to_none() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        settings = config.Settings(
            jira_auth_token='test-token',
            jira_auth_user='auth@example.com',
            jira_domain='https://jira.example.com',
            mosura_user='   ',
        )

    assert settings.mosura_user is None
    assert settings.jira_tracked_user == 'auth@example.com'


def test_settings_normalizes_blank_custom_jql_to_none() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        settings = config.Settings(
            jira_auth_token='test-token',
            jira_auth_user='auth@example.com',
            jira_domain='https://jira.example.com',
            mosura_custom_jql='   ',
        )

    assert settings.mosura_custom_jql is None


def test_settings_prefers_mosura_user_when_set() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        settings = config.Settings(
            jira_auth_token='test-token',
            jira_auth_user='auth@example.com',
            jira_domain='https://jira.example.com',
            mosura_user='acct-999',
        )

    assert settings.jira_tracked_user == 'acct-999'


def test_settings_reads_mosura_custom_jql_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('JIRA_AUTH_TOKEN', 'test-token')
    monkeypatch.setenv('JIRA_AUTH_USER', 'auth@example.com')
    monkeypatch.setenv('JIRA_DOMAIN', 'https://jira.example.com')
    monkeypatch.setenv('MOSURA_CUSTOM_JQL', 'project = MOS')

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        settings = config.Settings()

    assert settings.mosura_custom_jql == 'project = MOS'
