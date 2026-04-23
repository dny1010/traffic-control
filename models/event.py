from sqlalchemy import Column, Float, Integer, String, Text, TIMESTAMP, JSON, ForeignKey
from sqlalchemy.sql import func
from database.config import Base


class Event(Base):
    __tablename__ = "event"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(20), nullable=False, default="device")
    cctv_id = Column(Integer, ForeignKey("cctv.id"), nullable=True)
    device_id = Column(String(50), ForeignKey("device.device_id"), nullable=True)
    event_type = Column(String(50), nullable=False)
    event_time = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    description = Column(Text)
    image_url = Column(Text)
    event_metadata = Column("metadata", JSON)

    def __repr__(self):
        return (
            f"<Event(id={self.id}, source_type={self.source_type}, "
            f"event_type={self.event_type})>"
        )