"""
Cooler Repository Module.

This module manages database interactions for CPU cooler records.
It includes normalization logic for cooler types (Air, Liquid),
socket compatibility, physical dimensions (height), thermal performance (TDP),
and fan specifications. It handles deduplication during upsert operations.
"""

from database.session import SessionLocal
from models.cooler import Cooler
from ai.cooler_normalization import (
    _clean_str,
    normalize_cooler_brand,
    normalize_cooler_model,
    normalize_cooler_type,
    normalize_cooler_sockets,
    normalize_cooler_height_mm,
    normalize_cooler_tdp_w,
    normalize_cooler_fan_size_mm,
    normalize_cooler_fan_count,
    normalize_cooler_noise_db,
    normalize_cooler_rpm_max,
)


def _normalize_brand(value):
    """Wrapper for Cooler brand normalization."""
    return normalize_cooler_brand(value)


def _normalize_model(value):
    """Wrapper for Cooler model normalization."""
    return normalize_cooler_model(value)


def _normalize_cooler_type(value):
    """Wrapper for Cooler type (Air/Liquid) normalization."""
    return normalize_cooler_type(value)


def _normalize_sockets(value):
    """Wrapper for CPU socket compatibility normalization."""
    return normalize_cooler_sockets(value)


def _normalize_height_mm(value):
    """Wrapper for Cooler height normalization (mm)."""
    return normalize_cooler_height_mm(value)


def _normalize_tdp_w(value):
    """Wrapper for thermal design power (TDP) normalization (Watts)."""
    return normalize_cooler_tdp_w(value)


def _normalize_fan_size_mm(value):
    """Wrapper for fan size normalization (mm)."""
    return normalize_cooler_fan_size_mm(value)


def _normalize_fan_count(value):
    """Wrapper for fan count normalization."""
    return normalize_cooler_fan_count(value)


def _normalize_noise_db(value):
    """Wrapper for fan noise level normalization (dB)."""
    return normalize_cooler_noise_db(value)


def _normalize_rpm_max(value):
    """Wrapper for maximum fan rotation speed (RPM) normalization."""
    return normalize_cooler_rpm_max(value)


def upsert_cooler(cooler_data: dict) -> int:
    """
    Inserts or updates a CPU cooler record in the database.
    Deduplicates based on product URL or a unique combination of model,
    brand, cooler type, and TDP.
    """
    session = SessionLocal()
    try:
        product_url = _clean_str(cooler_data.get("url") or cooler_data.get("product_url"))
        brand = _normalize_brand(cooler_data.get("brand"))
        model = _normalize_model(cooler_data.get("model"))
        cooler_type = _normalize_cooler_type(cooler_data.get("cooler_type"))
        socket_compatibility = _normalize_sockets(cooler_data.get("socket_compatibility"))
        cooler_height_mm = _normalize_height_mm(cooler_data.get("cooler_height_mm"))
        tdp_w = _normalize_tdp_w(cooler_data.get("tdp_w"))
        fan_size_mm = _normalize_fan_size_mm(cooler_data.get("fan_size_mm"))
        fan_count = _normalize_fan_count(cooler_data.get("fan_count"))
        noise_db = _normalize_noise_db(cooler_data.get("noise_db"))
        rpm_max = _normalize_rpm_max(cooler_data.get("rpm_max"))
        price_raw = (
            cooler_data.get("price")
            if cooler_data.get("price") is not None
            else cooler_data.get("price_eur")
        )
        price_eur = float(price_raw) if price_raw is not None else None

        row = None
        if product_url:
            row = session.query(Cooler).filter(Cooler.product_url == product_url).first()

        dedupe_ready = all(
            value is not None
            for value in (brand, model, cooler_type, tdp_w)
        )
        if row is None and not product_url and dedupe_ready:
            row = (
                session.query(Cooler)
                .filter(
                    Cooler.brand == brand,
                    Cooler.model == model,
                    Cooler.cooler_type == cooler_type,
                    Cooler.tdp_w == tdp_w,
                )
                .first()
            )

        if row is None:
            row = Cooler()
            session.add(row)

        row.brand = brand
        row.model = model
        row.cooler_type = cooler_type
        row.socket_compatibility = socket_compatibility
        row.cooler_height_mm = cooler_height_mm
        row.tdp_w = tdp_w
        row.fan_size_mm = fan_size_mm
        row.fan_count = fan_count
        row.noise_db = noise_db
        row.rpm_max = rpm_max
        row.price_eur = price_eur
        row.product_url = product_url

        session.commit()
        return row.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
