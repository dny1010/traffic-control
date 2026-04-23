from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from database.config import Base


class Detection(Base):
    __tablename__ = "detection"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(20), nullable=False, default="device")
    cctv_id = Column(Integer, ForeignKey("cctv.id"), nullable=True)
    device_id = Column(String(50), ForeignKey("device.device_id"), nullable=True)
    object_type = Column(String(50), nullable=False)
    detected_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    def __repr__(self):
        return (
            f"<Detection(id={self.id}, source_type={self.source_type}, "
            f"object_type={self.object_type})>"
        )