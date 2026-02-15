from database.engine import engine
from models.base import Base
from models.cpu import CPU
from models.gpu import GPU
from models.ram import RAM

print("Creating database tables...")
Base.metadata.create_all(engine)
print("Done.")
