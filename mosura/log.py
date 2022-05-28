import pydantic


class LogConfig(pydantic.BaseModel):
    LOGGER_NAME = 'mosura'
    LOG_FORMAT = '%(levelprefix)s [%(name)s] %(message)s'
    LOG_LEVEL = 'DEBUG'

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
    loggers = {
        'mosura': {'handlers': ['default'], 'level': LOG_LEVEL},
    }
