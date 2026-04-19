from sqlalchemy import Column, DateTime, Float, Integer, String, func

from models.base import Base


class Cooler(Base):
    __tablename__ = "coolers"

    id = Column(Integer, primary_key=True)
    brand = Column(String)
    model = Column(String, index=True)
    cooler_type = Column(String)
    socket_compatibility = Column(String)
    cooler_height_mm = Column(Integer)
    tdp_w = Column(Integer)
    fan_size_mm = Column(Integer)
    fan_count = Column(Integer)
    noise_db = Column(Float)
    rpm_max = Column(Integer)
    price_eur = Column(Float)
    product_url = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
