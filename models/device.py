from sqlalchemy import Column, Integer, String, TIMESTAMP
from sqlalchemy.sql import func

from database.config import Base


class Device(Base):
    __tablename__ = "device"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(50), unique=True, nullable=False, index=True)
    location = Column(String(255), nullable=True)
    status = Column(String(20), nullable=True, default="active")
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<Device(id={self.id}, device_id={self.device_id}, status={self.status})>"
