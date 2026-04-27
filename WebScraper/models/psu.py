from sqlalchemy import Column, DateTime, Float, Integer, String, func

from models.base import Base


class PSU(Base):
    """
    SQLAlchemy model for Power Supply Units (PSUs).
    Stores wattage, efficiency ratings, and modularity type.
    """
    __tablename__ = "psus"

    id = Column(Integer, primary_key=True)
    brand = Column(String)
    model = Column(String, index=True)
    physical_size = Column(String)
    power_w = Column(Integer)
    efficiency = Column(String)
    certificate = Column(String)
    modularity = Column(String)
    fan_size_mm = Column(Integer)
    price_eur = Column(Float)
    product_url = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
