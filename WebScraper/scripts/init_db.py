from database.engine import engine
from models.base import Base
from models.cpu import CPU

print("Creating database tables...")
Base.metadata.create_all(engine)
print("Done.")
