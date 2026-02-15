from sqlalchemy import Column, Integer, String, Float, DateTime, func
from models.base import Base


class RAM(Base):
    __tablename__ = "rams"

    id = Column(Integer, primary_key=True)
    brand = Column(String)
    model = Column(String, index=True)
    memory_type = Column(String)
    memory_amount = Column(String)
    memory_speed_mhz = Column(Integer)
    latency = Column(String)
    form_factor = Column(String)
    price_eur = Column(Float)
    product_url = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
