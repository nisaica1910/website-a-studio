# A STUDIO — Company Profile (Flask)

## Jalankan lokal
```
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
flask --app app seed-demo      # (opsional) isi 9 proyek contoh
python app.py                  # buka http://127.0.0.1:5000
```
Admin: http://127.0.0.1:5002/admin  (default `admin` / `admin12345` — langsung ganti di Pengaturan)

## Akses developer (backend)
- Buat/reset admin : `flask --app app create-admin <username>`
- Database SQLite  : `instance/astudio.db` (buka pakai DB Browser for SQLite)
- Kategori baru    : tambah di `CATEGORIES` (models.py)
- Field pengaturan : tambah di `SETTING_FIELDS` (models.py), otomatis muncul di admin
- Foto upload      : `static/uploads/` (otomatis di-resize max 1920px)

## Production
Set env: `SECRET_KEY`, `DATABASE_URL` (opsional), `ADMIN_USER`, `ADMIN_PASS`
Jalankan: `gunicorn app:app`
Backup rutin: `instance/astudio.db` + folder `static/uploads/`
