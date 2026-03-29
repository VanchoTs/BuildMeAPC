from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, func

from models.base import Base


class SSD(Base):
    __tablename__ = "ssds"

    id = Column(Integer, primary_key=True)
    brand = Column(String)
    model = Column(String, index=True)
    type = Column(String)
    storage_size_gb = Column(Integer)
    physical_size = Column(String)
    read_speed_mbps = Column(Integer)
    write_speed_mbps = Column(Integer)
    interface = Column(String)
    tbw_tb = Column(Integer)
    nand_type = Column(String)
    has_heatsink = Column(Boolean)
    price_eur = Column(Float)
    product_url = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
