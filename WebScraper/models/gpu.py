from sqlalchemy import Column, Integer, String, Float, DateTime, func
from models.base import Base


class GPU(Base):
    __tablename__ = "gpus"

    id = Column(Integer, primary_key=True)
    brand = Column(String)
    model = Column(String, index=True)
    pcb_manufacturer = Column(String)
    pcb_series = Column(String)
    vram_gb = Column(Integer)
    memory_type = Column(String)
    memory_bus_bit = Column(Integer)
    base_clock_mhz = Column(Float)
    boost_clock_mhz = Column(Float)
    tdp_w = Column(Integer)
    interface = Column(String)
    price_eur = Column(Float)
    product_url = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
