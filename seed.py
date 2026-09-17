from app import app
from models import db, ParkingSpot, User
from werkzeug.security import generate_password_hash


def seed_db():
    with app.app_context():
        db.create_all()

        if ParkingSpot.query.first():
            print("[OK] Database already seeded. Skipping...")
            return

        # Default attendant account
        admin = User(
            username='admin',
            password_hash=generate_password_hash('password123')
        )
        db.session.add(admin)

        # ── Garage Layout: 3 Levels, 18 Spots ──────────────────────
        spots = [
            # Level 1 — Ground (EV charging + standard)
            ('L1-A01', 1, 'ev'),
            ('L1-A02', 1, 'ev'),
            ('L1-A03', 1, 'ev'),
            ('L1-B01', 1, 'standard'),
            ('L1-B02', 1, 'standard'),
            ('L1-B03', 1, 'standard'),

            # Level 2 — Standard + Compact mix
            ('L2-A01', 2, 'standard'),
            ('L2-A02', 2, 'standard'),
            ('L2-A03', 2, 'standard'),
            ('L2-B01', 2, 'compact'),
            ('L2-B02', 2, 'compact'),
            ('L2-B03', 2, 'compact'),

            # Level 3 — Rooftop (mostly compact)
            ('L3-A01', 3, 'standard'),
            ('L3-A02', 3, 'standard'),
            ('L3-B01', 3, 'compact'),
            ('L3-B02', 3, 'compact'),
            ('L3-B03', 3, 'compact'),
            ('L3-B04', 3, 'compact'),
        ]

        for num, level, s_type in spots:
            db.session.add(ParkingSpot(spot_number=num, level=level, type=s_type))

        db.session.commit()
        print(f"[OK] Seeded database: 1 admin user + {len(spots)} parking spots across 3 levels.")
        print("   EV: 3 | Standard: 8 | Compact: 7")
        print("   Login: admin / password123")


if __name__ == '__main__':
    seed_db()
