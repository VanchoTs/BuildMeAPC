from sqlalchemy.orm import sessionmaker
from database.engine import engine

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
