class Config:
    """Application configuration settings"""
    # Database configuration
    SQLALCHEMY_DATABASE_URI = "sqlite:///parking_v2.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Secret key for sessions – generated securely
    SECRET_KEY = __import__('os').urandom(24).hex()
    # Enable Flask debug mode for development
    DEBUG = True
