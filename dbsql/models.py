from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    osu_id = Column(Integer, unique=True, index=True)
    osu_avatar_url = Column(String)
    osu_username = Column(String, unique=True)
    osu_global_rank = Column(Integer, nullable=True)
    discord_id = Column(String, unique=True, index=True)

    team = relationship("Team", back_populates="owner")


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    avatar_url = Column(String, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="team")