from sqlalchemy import Column, Integer, String, Float, DateTime, func
from models.base import Base


class CPU(Base):
    """
    SQLAlchemy model for Central Processing Units (CPUs).
    Stores technical specifications like cores, threads, and socket compatibility.
    """
    __tablename__ = "cpus"

    id = Column(Integer, primary_key=True)
    brand = Column(String)
    model = Column(String, unique=True, index=True)
    cores = Column(Integer)
    threads = Column(Integer)
    base_clock_ghz = Column(Float)
    boost_clock_ghz = Column(Float)
    tdp_w = Column(Integer)
    socket = Column(String)
    memory_type = Column(String)
    price_eur = Column(Float)
    product_url = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
