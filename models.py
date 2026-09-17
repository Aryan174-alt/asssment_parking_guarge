from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from sqlalchemy import text

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ParkingSpot(db.Model):
    __tablename__ = 'parking_spots'
    id = db.Column(db.Integer, primary_key=True)
    spot_number = db.Column(db.String(20), unique=True, nullable=False)
    level = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20), nullable=False)  # compact | standard | ev
    is_occupied = db.Column(db.Boolean, default=False)


class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    id = db.Column(db.Integer, primary_key=True)
    plate_number = db.Column(db.String(50), unique=True, nullable=False)
    vehicle_type = db.Column(db.String(20), nullable=False)  # regular | ev


class Ticket(db.Model):
    __tablename__ = 'tickets'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    spot_id = db.Column(db.Integer, db.ForeignKey('parking_spots.id'), nullable=False)
    check_in_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    check_out_time = db.Column(db.DateTime, nullable=True)
    fee = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), default='active', nullable=False)  # active | completed

    vehicle = db.relationship('Vehicle', backref='tickets')
    spot = db.relationship('ParkingSpot', backref='tickets')

    __table_args__ = (
        # Partial unique indexes — DB-level guard against double-parking race conditions
        db.Index('uix_active_spot', 'spot_id', unique=True,
                 sqlite_where=text("status = 'active'")),
        db.Index('uix_active_vehicle', 'vehicle_id', unique=True,
                 sqlite_where=text("status = 'active'")),
    )
