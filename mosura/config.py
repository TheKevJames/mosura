import logging.config
import warnings
from typing import Annotated
from typing import Any
from typing import Self

import fastapi
import pydantic

with warnings.catch_warnings():
    # TODO: fixable?
    warnings.simplefilter('ignore', DeprecationWarning)
    import jira


logger = logging.getLogger(__name__)


class LogConfig(pydantic.BaseModel):
    LOG_LEVEL: str
    LOG_FORMAT = '%(levelprefix)s [%(name)s] %(message)s'

    version = 1
    disable_existing_loggers = False
    formatters = {
        'default': {
            '()': 'uvicorn.logging.DefaultFormatter',
            'fmt': LOG_FORMAT,
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    }
    handlers = {
        'default': {
            'formatter': 'default',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stderr',
        },
    }

    @property
    def loggers(self) -> dict[str, Any]:
        liblevel = 'INFO' if self.LOG_LEVEL == 'DEBUG' else self.LOG_LEVEL
        return {
            'aiosqlite': {'handlers': ['default'], 'level': liblevel},
            'databases': {'handlers': ['default'], 'level': liblevel},
            'root': {'handlers': ['default'], 'level': self.LOG_LEVEL},
            'urllib3': {'handlers': ['default'], 'level': liblevel},
        }

    def dictz(self) -> dict[str, str]:
        # TODO: in pydantic v2, use @pydantic.computed_field on loggers
        x = self.dict()
        x['loggers'] = self.loggers
        return x


class Settings(pydantic.BaseSettings):
    jira_auth_token: pydantic.SecretStr
    jira_auth_user: str
    jira_domain: str
    jira_label_okr: str = 'okr'
    jira_project: str
    mosura_appdata: str = '.'
    mosura_header_user_email: str | None
    mosura_log_level: str = 'DEBUG'
    mosura_port: int = 8080
    mosura_user: str | None

    class Config:
        # support docker compose secrets by default
        secrets_dir = '/run/secrets'

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        log_config = LogConfig(LOG_LEVEL=self.mosura_log_level).dictz()
        logging.config.dictConfig(log_config)

        if not self.mosura_header_user_email:
            logger.warning('MOSURA_HEADER_USER_EMAIL is not set, running in '
                           'insecure mode as user %s', self.mosura_user)


class Jira(jira.JIRA):
    @classmethod
    def from_settings(cls, s: Settings) -> Self:
        auth = (s.jira_auth_user, s.jira_auth_token.get_secret_value())
        return cls(s.jira_domain, basic_auth=auth, max_retries=0,
                   validate=True)


# TODO: rather than all this import-time crap, can I use app context of some
# sort? Maybe Dependencies?
settings = Settings()
jira_client = Jira.from_settings(settings)


class CommonParameters:
    email: str | None
    user: str | None

    def __init__(self, request: fastapi.Request) -> None:
        if settings.mosura_header_user_email:
            self.email = request.headers.get(settings.mosura_header_user_email)
        else:
            self.email = settings.mosura_user

        users = jira_client.search_users(query=self.email)
        if users:
            self.user = str(users.pop())


CommonsDep = Annotated[CommonParameters, fastapi.Depends()]
