"""
app.py
SIGAP - Sistem Informasi Gawat Aduan Publik
Disesuaikan agar cocok dengan skema database `sipemas.sql` buatan sendiri
(tabel: users, categories, complaints, responses, notifications, activity_logs).

Perubahan penting dari versi awal:
 - Login memakai EMAIL (bukan username, karena tabel users tidak punya kolom itu)
 - Registrasi kini meminta NIK, no. HP, alamat (sesuai kolom di tabel users)
 - role: 'admin' / 'citizen' (bukan 'warga')
 - reference_code menggantikan ticket_code
 - status pengaduan: pending/verified/processing/completed/rejected
 - foto pengaduan disimpan sebagai FILE di static/uploads (path disimpan di kolom `photo`)
 - fitur baru: notifikasi (tabel notifications) & log aktivitas (tabel activity_logs)

Fitur utama (>= 8):
 1. Registrasi & login (email + password, role admin/citizen)
 2. Ajukan pengaduan baru (kategori, judul, deskripsi, lokasi, foto)
 3. Pelacakan status pengaduan pribadi via reference_code
 4. Dashboard admin: kelola & filter seluruh pengaduan
 5. Ubah status pengaduan + tanggapan resmi (oleh admin)
 6. Pencarian & filter pengaduan (kategori, status, kata kunci)
 7. Statistik pengaduan (grafik Chart.js)
 8. Daftar pengaduan publik (identitas pelapor disamarkan)
 9. Upload foto bukti pengaduan (disimpan sebagai file)
10. Notifikasi ke warga saat status/​tanggapan diperbarui
11. Log aktivitas pengguna (activity_logs)
"""
import os
import uuid
from datetime import datetime

# Package cloudinary memvalidasi format CLOUDINARY_URL SAAT di-import (bukan
# saat dipanggil), jadi kalau formatnya salah ia akan crash sebelum kode kita
# sempat menangkapnya dengan try/except. Makanya divalidasi & dibersihkan di
# sini DULU, sebelum baris "import cloudinary" di bawah dieksekusi.
_cloudinary_url = os.environ.get("CLOUDINARY_URL", "").strip()
if _cloudinary_url and not _cloudinary_url.startswith("cloudinary://"):
    print(
        "[SIGAP] CLOUDINARY_URL tidak diawali 'cloudinary://' — diabaikan. "
        "Upload foto akan memakai mode lokal (tidak permanen di Vercel)."
    )
    os.environ.pop("CLOUDINARY_URL", None)

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from flask import (
    Flask, render_template, redirect, url_for, request, flash, abort
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from sqlalchemy import func
from werkzeug.utils import secure_filename

from models import db, User, Category, Complaint, Response, Notification, ActivityLog

load_dotenv()

# Cloudinary otomatis membaca env var CLOUDINARY_URL jika tersedia
# (format: cloudinary://API_KEY:API_SECRET@CLOUD_NAME). Wajib diisi saat
# deploy ke Vercel karena filesystem-nya tidak permanen.
#
# Dibungkus try/except: kalau formatnya salah (tidak diawali "cloudinary://"),
# ini tidak boleh meng-crash SELURUH aplikasi saat import module.
try:
    cloudinary.config(secure=True)
except Exception as exc:  # noqa: BLE001
    print(f"[SIGAP] CLOUDINARY_URL tidak valid, upload foto akan pakai mode lokal: {exc}")
USE_CLOUDINARY = bool(os.environ.get("CLOUDINARY_URL"))

# ---------------------------------------------------------------------------
# Konfigurasi Aplikasi
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "sigap-dev-secret-key-ubah-ini")

# Database: default ke MySQL lokal (sesuai nama database di sipemas.sql).
# Ubah lewat file .env jika kredensial phpMyAdmin/XAMPP/Laragon kamu berbeda.
db_url = os.environ.get("DATABASE_URL", "mysql+pymysql://root:@localhost:3306/sipemas")
if db_url.startswith("mysql://"):
    db_url = db_url.replace("mysql://", "mysql+pymysql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024  # 3 MB maks upload foto
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
# Di Vercel, filesystem read-only (kecuali /tmp) — os.makedirs akan gagal dan
# meng-crash seluruh fungsi kalau tidak dibungkus try/except. Folder ini hanya
# benar-benar dibutuhkan saat CLOUDINARY_URL belum diisi (mode lokal).
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Silakan masuk terlebih dahulu untuk mengakses halaman ini."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Util
# ---------------------------------------------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def generate_reference_code():
    return "SGP-" + datetime.utcnow().strftime("%y%m") + "-" + uuid.uuid4().hex[:6].upper()


def save_photo(file_storage):
    """
    Simpan foto pengaduan dan kembalikan nilai yang disimpan ke kolom `photo`
    (varchar(255)).

    - Jika CLOUDINARY_URL tersedia (wajib untuk deploy Vercel): upload ke
      Cloudinary, kembalikan secure_url (URL penuh, muat di varchar(255)).
    - Jika tidak (mode pengembangan lokal): simpan sebagai file fisik di
      static/uploads/ dan kembalikan path relatifnya.
    """
    if USE_CLOUDINARY:
        result = cloudinary.uploader.upload(file_storage, folder="sigap")
        return result["secure_url"]

    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
    file_storage.save(os.path.join(UPLOAD_FOLDER, filename))
    return f"uploads/{filename}"


def photo_url(photo_value):
    """Ubah nilai kolom `photo` menjadi URL yang siap dipakai di <img src>."""
    if not photo_value:
        return None
    if photo_value.startswith("http://") or photo_value.startswith("https://"):
        return photo_value
    return url_for("static", filename=photo_value)


def log_activity(user_id, action, description=None):
    db.session.add(ActivityLog(
        user_id=user_id,
        action=action,
        description=description,
        ip_address=request.remote_addr,
    ))
    db.session.commit()


def notify(user_id, title, message, link=None):
    db.session.add(Notification(user_id=user_id, title=title, message=message, link=link))
    db.session.commit()


app.jinja_env.globals["photo_url"] = photo_url


def admin_required(func_):
    from functools import wraps

    @wraps(func_)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Halaman ini khusus untuk petugas.", "danger")
            return redirect(url_for("index"))
        return func_(*args, **kwargs)

    return wrapper


def seed_categories():
    defaults = [
        ("Infrastruktur", "Jalan rusak, lampu jalan, drainase, dsb."),
        ("Kebersihan", "Sampah, kebersihan lingkungan."),
        ("Keamanan", "Gangguan keamanan & ketertiban."),
        ("Pelayanan Publik", "Pelayanan instansi pemerintah."),
        ("Lainnya", "Kategori umum lainnya."),
    ]
    for name, desc in defaults:
        if not Category.query.filter_by(category_name=name).first():
            db.session.add(Category(category_name=name, description=desc))
    db.session.commit()


def seed_admin():
    if not User.query.filter_by(role="admin").first():
        admin = User(
            full_name="Admin SIGAP",
            nik="0000000000000000",
            email="admin@sigap.local",
            phone="0800000000",
            role="admin",
        )
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.commit()


# ---------------------------------------------------------------------------
# Beranda publik + pencarian/filter
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    query = Complaint.query

    keyword = request.args.get("q", "").strip()
    category_id = request.args.get("kategori", type=int)
    status = request.args.get("status", "").strip()

    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (Complaint.title.ilike(like)) | (Complaint.location.ilike(like))
        )
    if category_id:
        query = query.filter(Complaint.category_id == category_id)
    if status:
        query = query.filter(Complaint.status == status)

    complaints = query.order_by(Complaint.created_at.desc()).limit(30).all()
    categories = Category.query.order_by(Category.category_name).all()

    total = Complaint.query.count()
    selesai = Complaint.query.filter_by(status="completed").count()

    return render_template(
        "index.html",
        complaints=complaints,
        categories=categories,
        statuses=Complaint.STATUS_CHOICES,
        status_labels=Complaint.STATUS_LABELS,
        total=total,
        selesai=selesai,
        q=keyword,
        selected_category=category_id,
        selected_status=status,
    )


# ---------------------------------------------------------------------------
# Registrasi & Login (memakai EMAIL, sesuai skema users)
# ---------------------------------------------------------------------------
@app.route("/daftar", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        nik = request.form.get("nik", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        password = request.form.get("password", "")

        if not all([full_name, nik, email, password]):
            flash("Nama lengkap, NIK, email, dan kata sandi wajib diisi.", "danger")
        elif len(nik) < 10:
            flash("NIK tidak valid.", "danger")
        elif User.query.filter_by(nik=nik).first():
            flash("NIK sudah terdaftar.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Email sudah terdaftar.", "danger")
        else:
            user = User(
                full_name=full_name, nik=nik, email=email,
                phone=phone or None, address=address or None, role="citizen",
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            log_activity(user.id, "register", "Akun baru dibuat.")
            flash("Pendaftaran berhasil! Silakan masuk.", "success")
            return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/masuk", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            log_activity(user.id, "login", "Berhasil masuk.")
            flash(f"Selamat datang kembali, {user.full_name}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))
        flash("Email atau kata sandi salah.", "danger")

    return render_template("login.html")


@app.route("/keluar")
@login_required
def logout():
    logout_user()
    flash("Anda telah keluar.", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Dashboard warga (pelacakan status pengaduan pribadi)
# ---------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for("admin_dashboard"))

    my_complaints = (
        Complaint.query.filter_by(user_id=current_user.id)
        .order_by(Complaint.created_at.desc())
        .all()
    )
    counts = {s: 0 for s in Complaint.STATUS_CHOICES}
    for c in my_complaints:
        counts[c.status] = counts.get(c.status, 0) + 1

    return render_template(
        "dashboard.html",
        complaints=my_complaints,
        counts=counts,
        status_labels=Complaint.STATUS_LABELS,
    )


# ---------------------------------------------------------------------------
# Notifikasi warga
# ---------------------------------------------------------------------------
@app.route("/notifikasi")
@login_required
def notifications():
    items = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    unread_ids = [n.id for n in items if not n.is_read]
    if unread_ids:
        Notification.query.filter(Notification.id.in_(unread_ids)).update(
            {"is_read": True}, synchronize_session=False
        )
        db.session.commit()
    return render_template("notifications.html", items=items)


# ---------------------------------------------------------------------------
# Ajukan pengaduan baru + unggah foto bukti
# ---------------------------------------------------------------------------
@app.route("/pengaduan/baru", methods=["GET", "POST"])
@login_required
def new_complaint():
    categories = Category.query.order_by(Category.category_name).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        category_id = request.form.get("category_id", type=int)
        photo = request.files.get("photo")

        if not all([title, description, location, category_id]):
            flash("Judul, kategori, deskripsi, dan lokasi wajib diisi.", "danger")
            return render_template("submit_complaint.html", categories=categories)

        photo_path = None
        if photo and photo.filename:
            if not allowed_file(photo.filename):
                flash("Format foto harus JPG, PNG, atau WEBP.", "danger")
                return render_template("submit_complaint.html", categories=categories)
            photo_path = save_photo(photo)

        complaint = Complaint(
            reference_code=generate_reference_code(),
            user_id=current_user.id,
            category_id=category_id,
            title=title,
            description=description,
            location=location,
            photo=photo_path,
            status="pending",
        )
        db.session.add(complaint)
        db.session.commit()

        log_activity(current_user.id, "create_complaint", f"Membuat pengaduan {complaint.reference_code}")
        flash(f"Pengaduan berhasil dikirim! Nomor referensi Anda: {complaint.reference_code}", "success")
        return redirect(url_for("complaint_detail", complaint_id=complaint.id))

    return render_template("submit_complaint.html", categories=categories)


# ---------------------------------------------------------------------------
# Detail pengaduan (pemilik, admin, atau publik)
# ---------------------------------------------------------------------------
@app.route("/pengaduan/<int:complaint_id>")
def complaint_detail(complaint_id):
    complaint = db.session.get(Complaint, complaint_id) or abort(404)

    is_owner = current_user.is_authenticated and current_user.id == complaint.user_id
    is_admin = current_user.is_authenticated and current_user.is_admin

    return render_template(
        "complaint_detail.html", complaint=complaint, is_owner=is_owner, is_admin=is_admin
    )


# ---------------------------------------------------------------------------
# Dashboard admin, kelola status + tanggapan, statistik
# ---------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    query = Complaint.query

    keyword = request.args.get("q", "").strip()
    category_id = request.args.get("kategori", type=int)
    status = request.args.get("status", "").strip()

    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (Complaint.title.ilike(like)) | (Complaint.reference_code.ilike(like))
        )
    if category_id:
        query = query.filter(Complaint.category_id == category_id)
    if status:
        query = query.filter(Complaint.status == status)

    complaints = query.order_by(Complaint.created_at.desc()).all()
    categories = Category.query.order_by(Category.category_name).all()

    status_counts_raw = dict(
        db.session.query(Complaint.status, func.count(Complaint.id))
        .group_by(Complaint.status)
        .all()
    )
    status_counts = {
        Complaint.STATUS_LABELS[s]: status_counts_raw.get(s, 0) for s in Complaint.STATUS_CHOICES
    }
    category_counts = dict(
        db.session.query(Category.category_name, func.count(Complaint.id))
        .join(Complaint, Complaint.category_id == Category.id)
        .group_by(Category.category_name)
        .all()
    )

    return render_template(
        "admin_dashboard.html",
        complaints=complaints,
        categories=categories,
        statuses=Complaint.STATUS_CHOICES,
        status_labels=Complaint.STATUS_LABELS,
        status_counts=status_counts,
        category_counts=category_counts,
        q=keyword,
        selected_category=category_id,
        selected_status=status,
    )


@app.route("/admin/pengaduan/<int:complaint_id>", methods=["GET", "POST"])
@admin_required
def admin_complaint_detail(complaint_id):
    complaint = db.session.get(Complaint, complaint_id) or abort(404)

    if request.method == "POST":
        new_status = request.form.get("status")
        message = request.form.get("message", "").strip()

        if new_status in Complaint.STATUS_CHOICES:
            complaint.status = new_status

        if message:
            db.session.add(
                Response(complaint_id=complaint.id, admin_id=current_user.id, message=message)
            )

        db.session.commit()

        notify(
            complaint.user_id,
            title=f"Update pengaduan {complaint.reference_code}",
            message=message or f"Status pengaduan Anda diperbarui menjadi '{complaint.status_label()}'.",
            link=url_for("complaint_detail", complaint_id=complaint.id),
        )
        log_activity(
            current_user.id, "update_status",
            f"Mengubah status {complaint.reference_code} menjadi {complaint.status}"
        )
        flash("Status pengaduan diperbarui dan tanggapan terkirim.", "success")
        return redirect(url_for("admin_complaint_detail", complaint_id=complaint.id))

    return render_template(
        "admin_complaint_detail.html",
        complaint=complaint,
        statuses=Complaint.STATUS_CHOICES,
        status_labels=Complaint.STATUS_LABELS,
    )


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="Anda tidak memiliki akses ke halaman ini."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Halaman atau pengaduan tidak ditemukan."), 404


# ---------------------------------------------------------------------------
# Inisialisasi (tabel sudah dibuat lewat sipemas.sql; ini hanya jaga-jaga
# untuk data awal kategori & akun admin, tidak akan menimpa tabel yang ada)
#
# Dibungkus try/except: kalau DATABASE_URL salah/belum diisi saat deploy,
# ini tidak boleh meng-crash SELURUH fungsi serverless untuk SETIAP request.
# Error yang sebenarnya tetap akan muncul saat route yang butuh DB dipanggil,
# dan itu lebih mudah didiagnosis lewat Vercel > Logs.
# ---------------------------------------------------------------------------
try:
    with app.app_context():
        db.create_all()
        seed_categories()
        seed_admin()
except Exception as exc:  # noqa: BLE001
    app.logger.error("Gagal inisialisasi database saat startup: %s", exc)


if __name__ == "__main__":
    app.run(debug=True)
