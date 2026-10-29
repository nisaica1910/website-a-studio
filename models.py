from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

# Tambah kategori baru cukup di sini (key: label)
CATEGORIES = {
    "house": "Interior Rumah",
    "office": "Interior Kantor",
}

# (key, label, tipe input, nilai default) -> dipakai di halaman Pengaturan admin
SETTING_FIELDS = [
    ("company_name", "Nama perusahaan", "text", "A STUDIO"),
    ("tagline", "Tagline", "text", "Interior Design & Build"),
    ("hero_title", "Judul utama (beranda)", "text",
     "Ruang yang dirancang presisi, dibangun dengan standar terbaik."),
    ("hero_subtitle", "Sub-judul (beranda)", "textarea",
     "Kontraktor interior & sipil dengan layanan custom furniture, dari konsep desain "
     "hingga serah terima untuk hunian dan kantor Anda."),
    ("about_text", "Tentang perusahaan", "textarea",
     "A STUDIO adalah studio desain dan kontraktor interior yang berfokus pada arsitektur, "
     "interior, dan sipil. Kami menangani proyek hunian maupun perkantoran dengan pendekatan "
     "desain yang rapi, material yang tepat, dan pengerjaan yang terukur.\n\n"
     "Dengan satu tim yang menangani desain sekaligus pembangunan, klien mendapat proses yang "
     "lebih efisien, anggaran yang transparan, dan hasil akhir yang sesuai dengan rencana."),
    ("whatsapp", "Nomor WhatsApp (format 628xxxxxxxxxx)", "text", ""),
    ("phone", "Nomor telepon (tampilan)", "text", ""),
    ("email", "Email", "text", ""),
    ("address", "Alamat", "textarea",
     "Jl. Parung Karet No.3, RT.001/RW.003, Parung Jaya, Kec. Karang Tengah, "
     "Kota Tangerang, Banten 15159"),
    ("instagram", "Username Instagram", "text", "a_studio.id"),
    ("website", "Website", "text", "astudio.id"),
    ("maps_embed", "Google Maps embed URL (opsional, isi src dari iframe)", "text", ""),
]
DEFAULT_SETTINGS = {k: d for k, _, _, d in SETTING_FIELDS}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False, index=True)
    category = db.Column(db.String(30), nullable=False, default="house", index=True)
    client = db.Column(db.String(160))
    location = db.Column(db.String(160))
    year = db.Column(db.Integer)
    area = db.Column(db.String(60))      # contoh: "250 m²"
    scope = db.Column(db.String(160))    # contoh: "Desain & Build"
    summary = db.Column(db.String(300))
    description = db.Column(db.Text)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    images = db.relationship(
        "ProjectImage", backref="project", cascade="all, delete-orphan",
        order_by="ProjectImage.position",
    )

    @property
    def cover(self):
        for img in self.images:
            if img.is_cover:
                return img
        return self.images[0] if self.images else None

    @property
    def category_label(self):
        return CATEGORIES.get(self.category, self.category)


class ProjectImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    position = db.Column(db.Integer, default=0)
    is_cover = db.Column(db.Boolean, default=False, nullable=False)


class Setting(db.Model):
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text, default="")

    @classmethod
    def all(cls):
        data = dict(DEFAULT_SETTINGS)
        for row in cls.query.all():
            data[row.key] = row.value or ""
        return data

    @classmethod
    def set(cls, key, value):
        row = db.session.get(cls, key)
        if row is None:
            row = cls(key=key)
            db.session.add(row)
        row.value = value


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160))
    phone = db.Column(db.String(40))
    body = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
