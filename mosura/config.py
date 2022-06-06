import pydantic


class Settings(pydantic.BaseSettings):
    jira_domain: str
    jira_label_prefix: str
    jira_label_okr: str = 'okr'
    jira_project: str
    jira_token: str
    jira_username: str


settings = Settings()
