import os
import re
import secrets
import uuid
from datetime import datetime
from urllib.parse import quote
import io
import mimetypes
from dotenv import load_dotenv

import click
from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import (LoginManager, current_user, login_required,
                         login_user, logout_user)
from sqlalchemy import or_

from models import (CATEGORIES, SETTING_FIELDS, Message, Project,
                    ProjectImage, Setting, User, db)

try:
    from PIL import Image, ImageOps
except ImportError:  # Pillow opsional, tapi disarankan
    Image = None

load_dotenv()
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
PER_PAGE = 12

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "project-images")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)
PUBLIC_PREFIX = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/"
storage = None
if USE_SUPABASE:
    from supabase import create_client
    storage = create_client(SUPABASE_URL, SUPABASE_KEY).storage.from_(SUPABASE_BUCKET)

app = Flask(__name__)

db_url = os.environ.get("DATABASE_URL", "sqlite:///astudio.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-ganti-di-production"),
    SQLALCHEMY_DATABASE_URI=db_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=64 * 1024 * 1024,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "admin_login"
login_manager.login_message = "Silakan login dulu."

app.jinja_env.globals.update(CATEGORIES=CATEGORIES)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ----------------------------------------------------------------- helpers
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def verify_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Token tidak valid, coba refresh halaman.")


@app.context_processor
def inject_globals():
    s = Setting.all()
    wa = re.sub(r"\D", "", s.get("whatsapp", ""))
    if wa.startswith("0"):
        wa = "62" + wa[1:]
    text = quote("Halo A STUDIO, saya ingin konsultasi desain interior.")
    wa_link = f"https://wa.me/{wa}?text={text}" if wa else url_for("contact")
    unread = 0
    if current_user.is_authenticated:
        unread = Message.query.filter_by(is_read=False).count()
    return dict(S=s, wa_link=wa_link, csrf_token=csrf_token, unread_count=unread,
                now_year=datetime.now().year)


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def unique_slug(title, ignore_id=None):
    base = slugify(title) or "project"
    slug, i = base, 2
    while True:
        q = Project.query.filter_by(slug=slug)
        if ignore_id:
            q = q.filter(Project.id != ignore_id)
        if not q.first():
            return slug
        slug = f"{base}-{i}"
        i += 1


def save_image(file):
    """Resize, lalu simpan ke Supabase Storage (atau lokal kalau tidak dikonfigurasi)."""
    name = file.filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXT:
        return None
    try:
        if Image is not None:
            img = Image.open(file.stream)
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((1920, 1920))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85, optimize=True)
            data, fname = buf.getvalue(), uuid.uuid4().hex + ".jpg"
        else:
            data, fname = file.read(), f"{uuid.uuid4().hex}.{ext}"

        if USE_SUPABASE:
            ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
            storage.upload(fname, data, {"content-type": ctype})
            return PUBLIC_PREFIX + fname

        with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
            f.write(data)
        return fname
    except Exception:
        app.logger.exception("Upload gambar gagal")
        return None


def remove_file(filename):
    if filename.startswith("http"):
        if USE_SUPABASE and filename.startswith(PUBLIC_PREFIX):
            try:
                storage.remove([filename[len(PUBLIC_PREFIX):]])
            except Exception:
                app.logger.exception("Hapus gambar di storage gagal")
        return
    try:
        os.remove(os.path.join(UPLOAD_DIR, filename))
    except OSError:
        pass


def img_url(filename):
    if filename.startswith("http"):
        return filename
    return url_for("static", filename="uploads/" + filename)


app.jinja_env.globals["img_url"] = img_url


def save_uploads(project):
    files = [f for f in request.files.getlist("images") if f and f.filename]
    pos = max([i.position or 0 for i in project.images], default=-1) + 1
    for f in files:
        fname = save_image(f)
        if not fname:
            flash(f"File '{f.filename}' gagal diunggah (cek format JPG/PNG/WEBP atau koneksi storage).", "error")
            continue
        db.session.add(ProjectImage(project=project, filename=fname, position=pos))
        pos += 1
    db.session.flush()
    if project.images and not any(i.is_cover for i in project.images):
        project.images[0].is_cover = True


def fill_project(p):
    f = request.form
    title = f.get("title", "").strip()
    if not title:
        flash("Nama proyek wajib diisi.", "error")
        return False
    p.title = title
    cat = f.get("category", "house")
    p.category = cat if cat in CATEGORIES else "house"
    p.client = f.get("client", "").strip() or None
    p.location = f.get("location", "").strip() or None
    p.scope = f.get("scope", "").strip() or None
    p.area = f.get("area", "").strip() or None
    p.summary = f.get("summary", "").strip()[:300] or None
    p.description = f.get("description", "").strip() or None
    year = f.get("year", "").strip()
    p.year = int(year) if year.isdigit() else None
    p.is_featured = "is_featured" in f
    p.is_published = "is_published" in f
    return True


def published_projects():
    return Project.query.filter_by(is_published=True)


# ------------------------------------------------------------ public pages
@app.route("/")
def index():
    featured = (published_projects().filter_by(is_featured=True)
                .order_by(Project.year.desc().nulls_last(), Project.id.desc()).limit(6).all())
    if len(featured) < 6:
        ids = [p.id for p in featured]
        more = (published_projects().filter(~Project.id.in_(ids))
                .order_by(Project.year.desc().nulls_last(), Project.id.desc())
                .limit(6 - len(featured)).all())
        featured += more
    hero_project = next((p for p in featured if p.cover), None)
    total = published_projects().count()
    counts = {k: published_projects().filter_by(category=k).count() for k in CATEGORIES}
    return render_template("index.html", featured=featured, hero_project=hero_project,
                           total=total, counts=counts)


@app.route("/proyek")
def projects():
    cat = request.args.get("kategori", "")
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    query = published_projects()
    if cat in CATEGORIES:
        query = query.filter_by(category=cat)
    else:
        cat = ""
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Project.title.ilike(like), Project.client.ilike(like),
                                 Project.location.ilike(like)))
    pg = query.order_by(Project.year.desc().nulls_last(), Project.id.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False)
    return render_template("projects.html", pg=pg, cat=cat, q=q)


@app.route("/proyek/<slug>")
def project_detail(slug):
    p = Project.query.filter_by(slug=slug, is_published=True).first_or_404()
    related = (published_projects().filter(Project.category == p.category, Project.id != p.id)
               .order_by(Project.year.desc().nulls_last(), Project.id.desc()).limit(3).all())
    return render_template("project_detail.html", p=p, related=related)


@app.route("/tentang")
def about():
    return render_template("about.html")


@app.route("/kontak", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        if request.form.get("website_url"):  # honeypot anti-spam
            return redirect(url_for("contact"))
        name = request.form.get("name", "").strip()
        body = request.form.get("body", "").strip()
        if not name or not body:
            flash("Nama dan pesan wajib diisi.", "error")
        else:
            db.session.add(Message(
                name=name[:120], email=request.form.get("email", "").strip()[:160],
                phone=request.form.get("phone", "").strip()[:40], body=body[:4000]))
            db.session.commit()
            flash("Terima kasih! Pesan Anda sudah kami terima, tim kami akan segera menghubungi.", "success")
            return redirect(url_for("contact"))
    return render_template("contact.html")


# ------------------------------------------------------------------- admin
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username", "").strip()).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user)
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("admin_dashboard"))
        flash("Username atau password salah.", "error")
    return render_template("admin/login.html")


@app.route("/admin/logout", methods=["POST"])
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    stats = dict(
        total=Project.query.count(),
        published=Project.query.filter_by(is_published=True).count(),
        draft=Project.query.filter_by(is_published=False).count(),
        house=Project.query.filter_by(category="house").count(),
        office=Project.query.filter_by(category="office").count(),
        messages=Message.query.count(),
    )
    latest = Project.query.order_by(Project.updated_at.desc().nulls_last()).limit(5).all()
    msgs = Message.query.order_by(Message.created_at.desc()).limit(5).all()
    return render_template("admin/dashboard.html", stats=stats, latest=latest, msgs=msgs)


@app.route("/admin/proyek")
@login_required
def admin_projects():
    cat = request.args.get("kategori", "")
    q = request.args.get("q", "").strip()
    query = Project.query
    if cat in CATEGORIES:
        query = query.filter_by(category=cat)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Project.title.ilike(like), Project.client.ilike(like)))
    items = query.order_by(Project.year.desc().nulls_last(), Project.id.desc()).all()
    return render_template("admin/projects.html", items=items, cat=cat, q=q)


@app.route("/admin/proyek/baru", methods=["GET", "POST"])
@login_required
def admin_project_new():
    p = Project(is_published=True)
    if request.method == "POST":
        if fill_project(p):
            p.slug = unique_slug(p.title)
            db.session.add(p)
            db.session.flush()
            save_uploads(p)
            db.session.commit()
            flash("Proyek berhasil ditambahkan.", "success")
            return redirect(url_for("admin_project_edit", pid=p.id))
    return render_template("admin/project_form.html", p=p, is_new=True)


@app.route("/admin/proyek/<int:pid>", methods=["GET", "POST"])
@login_required
def admin_project_edit(pid):
    p = db.get_or_404(Project, pid)
    if request.method == "POST":
        if fill_project(p):
            save_uploads(p)
            db.session.commit()
            flash("Perubahan disimpan.", "success")
            return redirect(url_for("admin_project_edit", pid=p.id))
    return render_template("admin/project_form.html", p=p, is_new=False)


@app.route("/admin/proyek/<int:pid>/hapus", methods=["POST"])
@login_required
def admin_project_delete(pid):
    p = db.get_or_404(Project, pid)
    for img in p.images:
        remove_file(img.filename)
    db.session.delete(p)
    db.session.commit()
    flash("Proyek dihapus.", "success")
    return redirect(url_for("admin_projects"))


@app.route("/admin/proyek/<int:pid>/toggle/<field>", methods=["POST"])
@login_required
def admin_project_toggle(pid, field):
    p = db.get_or_404(Project, pid)
    if field == "published":
        p.is_published = not p.is_published
    elif field == "featured":
        p.is_featured = not p.is_featured
    else:
        abort(404)
    db.session.commit()
    return redirect(request.referrer or url_for("admin_projects"))


@app.route("/admin/gambar/<int:iid>/hapus", methods=["POST"])
@login_required
def admin_image_delete(iid):
    img = db.get_or_404(ProjectImage, iid)
    p = img.project
    was_cover = img.is_cover
    remove_file(img.filename)
    db.session.delete(img)
    db.session.flush()
    db.session.refresh(p)
    if was_cover and p.images:
        p.images[0].is_cover = True
    db.session.commit()
    flash("Gambar dihapus.", "success")
    return redirect(url_for("admin_project_edit", pid=p.id) + "#galeri")


@app.route("/admin/gambar/<int:iid>/cover", methods=["POST"])
@login_required
def admin_image_cover(iid):
    img = db.get_or_404(ProjectImage, iid)
    for other in img.project.images:
        other.is_cover = other.id == img.id
    db.session.commit()
    flash("Cover proyek diganti.", "success")
    return redirect(url_for("admin_project_edit", pid=img.project_id) + "#galeri")


@app.route("/admin/gambar/<int:iid>/geser/<direction>", methods=["POST"])
@login_required
def admin_image_move(iid, direction):
    img = db.get_or_404(ProjectImage, iid)
    imgs = list(img.project.images)
    i = imgs.index(img)
    j = i - 1 if direction == "kiri" else i + 1
    if 0 <= j < len(imgs):
        imgs[i], imgs[j] = imgs[j], imgs[i]
        for pos, item in enumerate(imgs):
            item.position = pos
        db.session.commit()
    return redirect(url_for("admin_project_edit", pid=img.project_id) + "#galeri")


@app.route("/admin/pengaturan", methods=["GET", "POST"])
@login_required
def admin_settings():
    if request.method == "POST":
        for key, _, _, _ in SETTING_FIELDS:
            Setting.set(key, request.form.get(key, "").strip())
        db.session.commit()
        flash("Pengaturan disimpan.", "success")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html", fields=SETTING_FIELDS)


@app.route("/admin/password", methods=["POST"])
@login_required
def admin_password():
    old = request.form.get("old", "")
    new = request.form.get("new", "")
    if not current_user.check_password(old):
        flash("Password lama salah.", "error")
    elif len(new) < 8:
        flash("Password baru minimal 8 karakter.", "error")
    else:
        current_user.set_password(new)
        db.session.commit()
        flash("Password berhasil diganti.", "success")
    return redirect(url_for("admin_settings"))


@app.route("/admin/pesan")
@login_required
def admin_messages():
    items = Message.query.order_by(Message.created_at.desc()).all()
    return render_template("admin/messages.html", items=items)


@app.route("/admin/pesan/<int:mid>")
@login_required
def admin_message_view(mid):
    m = db.get_or_404(Message, mid)
    if not m.is_read:
        m.is_read = True
        db.session.commit()
    return render_template("admin/message_view.html", m=m)


@app.route("/admin/pesan/<int:mid>/hapus", methods=["POST"])
@login_required
def admin_message_delete(mid):
    db.session.delete(db.get_or_404(Message, mid))
    db.session.commit()
    flash("Pesan dihapus.", "success")
    return redirect(url_for("admin_messages"))


# --------------------------------------------------------------- CLI / init
def ensure_default_admin():
    if User.query.first() is None:
        user = os.environ.get("ADMIN_USER", "admin")
        pwd = os.environ.get("ADMIN_PASS", "admin12345")
        u = User(username=user)
        u.set_password(pwd)
        db.session.add(u)
        db.session.commit()
        print(f"[!] Admin default dibuat: {user} / {pwd}  -> SEGERA ganti password!")


with app.app_context():
    db.create_all()
    ensure_default_admin()


@app.cli.command("create-admin")
@click.argument("username")
@click.password_option()
def create_admin(username, password):
    """Buat / reset akun admin:  flask --app app create-admin <username>"""
    u = User.query.filter_by(username=username).first() or User(username=username)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    click.echo(f"Admin '{username}' siap dipakai.")


@app.cli.command("seed-demo")
def seed_demo():
    """Isi data contoh proyek (tanpa foto) untuk preview tampilan."""
    from seed_data import DEMO_PROJECTS
    added = 0
    for d in DEMO_PROJECTS:
        if Project.query.filter_by(title=d["title"]).first():
            continue
        p = Project(**d)
        p.slug = unique_slug(p.title)
        db.session.add(p)
        added += 1
    db.session.commit()
    click.echo(f"{added} proyek contoh ditambahkan.")


if __name__ == "__main__":
    app.run(debug=True, port=5002)
