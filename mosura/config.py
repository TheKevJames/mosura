import logging

import pydantic


logger = logging.getLogger(__name__)


class Settings(pydantic.BaseSettings):
    jira_domain: str
    # TODO: https://docs.pydantic.dev/latest/usage/settings/#secret-support
    jira_auth_token: pydantic.SecretStr
    jira_auth_user: str
    jira_project: str
    jira_label_okr: str = 'okr'
    mosura_port: int = 8080
    mosura_appdata: str = '.'


# TODO: rather than all this import-time crap, can I use app context of some
# sort? Maybe Dependencies?
settings = Settings()
