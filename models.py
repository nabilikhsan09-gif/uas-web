"""
models.py
Model SQLAlchemy yang disesuaikan agar SAMA PERSIS dengan skema database
`sipemas.sql` (hasil export phpMyAdmin) yang sudah kamu buat & import sendiri.

Tabel: users, categories, complaints, responses, notifications, activity_logs
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    nik = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    password = db.Column(db.String(255), nullable=False)          # nama kolom: password (bukan password_hash)
    role = db.Column(db.Enum("admin", "citizen", name="role_enum"), default="citizen")
    photo = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    complaints = db.relationship(
        "Complaint", backref="pelapor", lazy=True, foreign_keys="Complaint.user_id"
    )

    def set_password(self, raw_password):
        self.password = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password, raw_password)

    @property
    def is_admin(self):
        return self.role == "admin"


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)

    complaints = db.relationship("Complaint", backref="category", lazy=True)


class Complaint(db.Model):
    __tablename__ = "complaints"

    # Nilai enum PERSIS seperti di sipemas.sql (bahasa Inggris, huruf kecil)
    STATUS_CHOICES = ["pending", "verified", "processing", "completed", "rejected"]
    STATUS_LABELS = {
        "pending": "Menunggu",
        "verified": "Terverifikasi",
        "processing": "Diproses",
        "completed": "Selesai",
        "rejected": "Ditolak",
    }

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    reference_code = db.Column(db.String(30), unique=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    photo = db.Column(db.String(255))          # path relatif ke file, contoh: uploads/abc123.jpg
    location = db.Column(db.String(255))
    latitude = db.Column(db.Numeric(10, 8))
    longitude = db.Column(db.Numeric(11, 8))
    status = db.Column(db.Enum(*STATUS_CHOICES, name="status_enum"), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    responses = db.relationship(
        "Response", backref="complaint", lazy=True,
        cascade="all, delete-orphan", order_by="Response.created_at"
    )

    def status_label(self):
        """Label berbahasa Indonesia untuk ditampilkan di UI."""
        return self.STATUS_LABELS.get(self.status, self.status)

    def status_badge_class(self):
        mapping = {
            "pending": "badge-waiting",
            "verified": "badge-progress",
            "processing": "badge-progress",
            "completed": "badge-done",
            "rejected": "badge-rejected",
        }
        return mapping.get(self.status, "badge-waiting")


class Response(db.Model):
    __tablename__ = "responses"

    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaints.id"), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    message = db.Column(db.Text, nullable=False)
    attachment = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    admin = db.relationship("User", foreign_keys=[admin_id])


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id])


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
