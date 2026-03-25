from database.engine import engine
from models.base import Base
from models.cpu import CPU
from models.gpu import GPU
from models.motherboard import Motherboard
from models.ram import RAM
from models.ssd import SSD

print("Creating database tables...")
Base.metadata.create_all(engine)
print("Done.")
