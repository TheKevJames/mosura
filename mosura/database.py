import databases
import sqlalchemy
from sqlalchemy.ext.declarative import declarative_base


DATABASE_URL = 'sqlite:///./mosura.db'

database = databases.Database(DATABASE_URL)
engine = sqlalchemy.create_engine(DATABASE_URL,
                                  connect_args={'check_same_thread': False})

Base = declarative_base()
