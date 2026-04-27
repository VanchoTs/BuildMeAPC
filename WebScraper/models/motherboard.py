from sqlalchemy import Column, Integer, String, Float, DateTime, func, JSON
from models.base import Base


class Motherboard(Base):
    """
    SQLAlchemy model for Motherboards.
    Uses a JSON column for flexible storage of I/O ports and expansion slots.
    """
    __tablename__ = "motherboards"

    id = Column(Integer, primary_key=True)
    brand = Column(String)
    model = Column(String, index=True)
    form_factor = Column(String)
    chipset = Column(String)
    socket = Column(String)
    memory_type = Column(String)
    ram_slots = Column(Integer)
    max_ram_speed_mhz = Column(Integer)
    max_ram_amount_gb = Column(Integer)
    onboard_wifi = Column(String)
    io_json = Column(JSON)
    price_eur = Column(Float)
    product_url = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
