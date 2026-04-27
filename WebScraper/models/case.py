from sqlalchemy import Column, DateTime, Float, Integer, String, func, JSON

from models.base import Base


class Case(Base):
    """
    SQLAlchemy model for Computer Cases.
    Tracks physical clearance for GPUs, coolers, and radiator support.
    """
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True)
    brand = Column(String)
    model = Column(String, index=True)
    case_size = Column(String)
    motherboard_form_factors = Column(String)
    included_fans = Column(Integer)
    max_cpu_cooler_mm = Column(Integer)
    max_gpu_length_mm = Column(Integer)
    max_psu_length_mm = Column(Integer)
    max_radiator_mm = Column(Integer)
    io_json = Column(JSON)
    price_eur = Column(Float)
    product_url = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
