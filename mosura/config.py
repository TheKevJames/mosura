import logging.config
import warnings
from typing import Any
from typing import Self

import jira
import pydantic
import pydantic_settings


class LogConfig(pydantic.BaseModel):
    LOG_LEVEL: str
    LOG_FORMAT: str = '%(levelprefix)s [%(name)s] %(message)s'

    version: int = 1
    disable_existing_loggers: bool = False
    formatters: dict[str, dict[str, str]] = {
        'default': {
            '()': 'uvicorn.logging.DefaultFormatter',
            'fmt': LOG_FORMAT,
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    }
    handlers: dict[str, dict[str, str]] = {
        'default': {
            'formatter': 'default',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stderr',
        },
    }

    @pydantic.computed_field
    def loggers(self) -> dict[str, Any]:
        liblevel = 'INFO' if self.LOG_LEVEL == 'DEBUG' else self.LOG_LEVEL
        return {
            'aiosqlite': {'handlers': ['default'], 'level': liblevel},
            'sqlachlemy': {'handlers': ['default'], 'level': liblevel},
            'root': {'handlers': ['default'], 'level': self.LOG_LEVEL},
            'urllib3': {'handlers': ['default'], 'level': liblevel},
        }


class Settings(pydantic_settings.BaseSettings):
    jira_auth_token: pydantic.SecretStr
    jira_auth_user: str
    jira_domain: str
    mosura_appdata: str = '.'
    mosura_log_level: str = 'DEBUG'
    mosura_poll_interval: int = 60
    mosura_user: str | None = None

    # support docker compose secrets by default
    model_config = pydantic_settings.SettingsConfigDict(
        secrets_dir='/run/secrets',
    )

    @pydantic.field_validator('mosura_user')
    @classmethod
    def normalize_optional_env_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        log_config = LogConfig(LOG_LEVEL=self.mosura_log_level).model_dump()
        logging.config.dictConfig(log_config)

    @property
    def jira_tracked_user(self) -> str:
        return self.mosura_user or self.jira_auth_user


class Jira(jira.JIRA):
    @classmethod
    def from_settings(cls, s: Settings) -> Self:
        auth = (s.jira_auth_user, s.jira_auth_token.get_secret_value())
        return cls(
            s.jira_domain, basic_auth=auth, max_retries=0,
            validate=True,
        )


def load_settings() -> Settings:
    with warnings.catch_warnings():
        # don't warn on secrets_dir being missing
        warnings.simplefilter('ignore', UserWarning)
        return Settings()
