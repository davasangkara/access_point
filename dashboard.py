import os
import secrets
import requests
from urllib.parse import urlencode
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    make_response
)
from dotenv import load_dotenv

# load .env kalau lagi jalan lokal
load_dotenv()

# =======================
# KONFIG GLOBAL
# =======================

# URL license server kamu
API_URL         = os.getenv("API_URL", "https://licensi.onrender.com")

# API key untuk akses endpoint admin di license server
ADMIN_KEY       = os.getenv("ADMIN_KEY", "super-secret-key")

# password panel admin (buat login di /login)
PANEL_PASSWORD  = os.getenv("PANEL_PASSWORD", "admin123")

# nomor WhatsApp admin (tanpa +) untuk auto-generate link wa.me
ADMIN_WHATSAPP  = os.getenv("ADMIN_WHATSAPP", "6289517705267")

app = Flask(__name__)
app.config["APP_NAME"] = "GENCO AUTO TOOL • BY Dava"

# session token admin disimpan di memori proses aja (sederhana)
CURRENT_SESSION_TOKEN = None
# catatan:
# - kalau service restart → auto logout semua admin
# - ini bukan full session production, tapi cukup aman buat panel internal


# =======================
# HELPER KE LICENSE SERVER
# =======================

def api_list():
    """
    Ambil semua device yang sudah di-whitelist dari license server.
    Return tuple: (ok:bool, err:str|None, data:list)
    """
    try:
        r = requests.get(
            f"{API_URL}/admin/list",
            headers={"X-API-KEY": ADMIN_KEY},
            timeout=10
        )
        if r.status_code != 200:
            return False, f"Error {r.status_code}: {r.text}", []
        return True, None, r.json()
    except Exception as e:
        return False, str(e), []


def api_add(machine_id, note=""):
    """
    Whitelist machine_id baru di license server.
    Return tuple: (status_code:int, text:str)
    """
    try:
        r = requests.post(
            f"{API_URL}/admin/add",
            headers={
                "X-API-KEY": ADMIN_KEY,
                "Content-Type": "application/json"
            },
            json={"machine_id": machine_id, "note": note},
            timeout=10
        )
        return r.status_code, r.text
    except Exception as e:
        return 500, f"Exception: {e}"


def api_remove(machine_id):
    """
    Cabut akses sebuah machine_id dari license server.
    Return tuple: (status_code:int, text:str)
    """
    try:
        r = requests.post(
            f"{API_URL}/admin/remove",
            headers={
                "X-API-KEY": ADMIN_KEY,
                "Content-Type": "application/json"
            },
            json={"machine_id": machine_id},
            timeout=10
        )
        return r.status_code, r.text
    except Exception as e:
        return 500, f"Exception: {e}"


# =======================
# AUTH / SESSION
# =======================

def get_auth_cookie(req):
    return req.cookies.get("auth")


def is_logged_in(req):
    """
    Cek apakah request ini punya session token admin yang valid.
    """
    global CURRENT_SESSION_TOKEN
    token = get_auth_cookie(req)
    return (CURRENT_SESSION_TOKEN is not None) and (token == CURRENT_SESSION_TOKEN)


def redirect_with_msg(endpoint, msg=None, level=None, **params):
    """
    Helper redirect + kirim notifikasi via querystring.
    Jadi URL tujuan bakal dapet ?msg=...&lvl=...
    Karena kita sengaja gak make flash() bawaan Flask session.
    """
    if msg:
        params["msg"] = msg
    if level:
        params["lvl"] = level
    base = url_for(endpoint)
    if params:
        return redirect(base + "?" + urlencode(params))
    return redirect(base)


# =======================
# PUBLIC PAGES (USER)
# =======================

@app.route("/public", methods=["GET"])
def public_page():
    """
    Halaman publik buat user biasa.
    Alur:
    - User jalanin script main.py
    - Kalau ditolak ("LISENSI DITOLAK"), script nampilin Machine ID
    - User paste Machine ID ke form ini
    - Kita generate tombol WhatsApp ke admin
    Admin nanti approve lewat panel admin.
    """
    toast_msg = request.args.get("msg")
    toast_lvl = request.args.get("lvl", "info")

    return render_template(
        "public_form.html",
        toast_msg=toast_msg,
        toast_lvl=toast_lvl,
        app_name=app.config["APP_NAME"]
    )


@app.route("/public/send", methods=["POST"])
def public_send():
    """
    Setelah user isi form Machine ID, kita bikin link WhatsApp yang sudah auto-format.
    Ini TIDAK otomatis whitelist, masih harus admin approve.
    """
    machine_id = request.form.get("machine_id", "").strip()
    note       = request.form.get("note", "").strip()

    if not machine_id:
        return redirect_with_msg(
            "public_page",
            msg="machine_id wajib diisi",
            level="danger"
        )

    # Format pesan WA.
    # %0A = newline encoded supaya aman di URL
    wa_lines = [
        "Halo admin, saya mau akses GENCO AUTO TOOL.",
        "Tolong whitelist device saya ya.",
        "",
        f"machine_id: {machine_id}",
    ]
    if note:
        wa_lines.append(f"info: {note}")
    wa_lines.append("")
    wa_lines.append("Terima kasih 🙏")

    wa_text_encoded = "%0A".join([line.replace(" ", "%20") for line in wa_lines])
    wa_url = f"https://wa.me/{ADMIN_WHATSAPP}?text={wa_text_encoded}"

    return render_template(
        "public_done.html",
        toast_msg="Silakan kirim Machine ID ke admin lewat tombol WhatsApp di bawah.",
        toast_lvl="success",
        machine_id=machine_id,
        note=note,
        wa_url=wa_url,
        app_name=app.config["APP_NAME"]
    )


# =======================
# LOGIN / LOGOUT ADMIN
# =======================

@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Login admin simpel pakai satu password.
    Kita buat session token random, simpan di memori server, dan taruh di cookie.
    """
    global CURRENT_SESSION_TOKEN

    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == PANEL_PASSWORD:
            # generate session token
            CURRENT_SESSION_TOKEN = secrets.token_hex(32)

            resp = make_response(redirect_with_msg(
                "machines_list",
                msg="Login sukses",
                level="success"
            ))
            # NOTE:
            # secure=True kalau sudah pakai HTTPS domain publik
            resp.set_cookie(
                "auth",
                CURRENT_SESSION_TOKEN,
                httponly=True,
                secure=False,
                samesite="Lax",
                max_age=60 * 60 * 6  # 6 jam
            )
            return resp

        # Password salah
        return redirect_with_msg(
            "login",
            msg="Password salah",
            level="danger"
        )

    # GET /login
    message = request.args.get("msg")
    level   = request.args.get("lvl", "info")
    return render_template(
        "login.html",
        toast_msg=message,
        toast_lvl=level,
        app_name=app.config["APP_NAME"]
    )


@app.route("/logout")
def logout():
    """
    Logout admin: hapus token dari memori + clear cookie.
    """
    global CURRENT_SESSION_TOKEN
    CURRENT_SESSION_TOKEN = None

    resp = make_response(redirect_with_msg(
        "login",
        msg="Logged out",
        level="info"
    ))
    resp.set_cookie("auth", "", max_age=0)
    return resp


# =======================
# DASHBOARD ADMIN
# =======================

@app.route("/")
def home():
    """
    Root:
    - kalau belum login → arahkan ke /public (biar user biasa bisa request akses)
    - kalau udah login → langsung ke /machines
    """
    if not is_logged_in(request):
        return redirect(url_for("public_page"))
    return redirect(url_for("machines_list"))


@app.route("/machines", methods=["GET"])
def machines_list():
    """
    Halaman admin lihat semua whitelist device.
    Ini pakai layout card grid (bukan tabel), dan ada tombol Remove langsung.
    """
    if not is_logged_in(request):
        return redirect(url_for("login"))

    ok, err, data = api_list()
    message = request.args.get("msg")
    level   = request.args.get("lvl", "info")

    if not ok:
        message = f"Gagal ambil data: {err}"
        level   = "danger"
        data    = []

    return render_template(
        "list.html",
        machines=data,
        toast_msg=message,
        toast_lvl=level,
        app_name=app.config["APP_NAME"]
    )


@app.route("/machines/add", methods=["GET", "POST"])
def machines_add():
    """
    Halaman + aksi whitelist device baru secara manual oleh admin.
    """
    if not is_logged_in(request):
        return redirect(url_for("login"))

    if request.method == "POST":
        machine_id = request.form.get("machine_id", "").strip()
        note       = request.form.get("note", "").strip()

        if not machine_id:
            return redirect_with_msg(
                "machines_add",
                msg="machine_id wajib diisi",
                level="danger"
            )

        status, text = api_add(machine_id, note)

        if status == 201:
            return redirect_with_msg(
                "machines_list",
                msg="Berhasil tambah device ✅",
                level="success"
            )
        else:
            return redirect_with_msg(
                "machines_add",
                msg=f"Gagal tambah ({status}): {text}",
                level="danger"
            )

    # GET
    message = request.args.get("msg")
    level   = request.args.get("lvl", "info")
    return render_template(
        "add.html",
        toast_msg=message,
        toast_lvl=level,
        app_name=app.config["APP_NAME"]
    )


@app.route("/machines/remove", methods=["GET", "POST"])
def machines_remove():
    """
    Halaman fallback: cabut akses dengan cara ketik manual machine_id.
    (Masih kita pertahankan sebagai opsi manual.)
    """
    if not is_logged_in(request):
        return redirect(url_for("login"))

    if request.method == "POST":
        machine_id = request.form.get("machine_id", "").strip()

        if not machine_id:
            return redirect_with_msg(
                "machines_remove",
                msg="machine_id wajib diisi",
                level="danger"
            )

        status, text = api_remove(machine_id)

        if status == 200:
            return redirect_with_msg(
                "machines_list",
                msg="Berhasil hapus device 🗑️",
                level="success"
            )
        else:
            return redirect_with_msg(
                "machines_remove",
                msg=f"Gagal hapus ({status}): {text}",
                level="danger"
            )

    # GET
    message = request.args.get("msg")
    level   = request.args.get("lvl", "info")
    return render_template(
        "remove.html",
        toast_msg=message,
        toast_lvl=level,
        app_name=app.config["APP_NAME"]
    )


@app.route("/machines/remove/<machine_id>", methods=["POST"])
def machines_remove_direct(machine_id):
    """
    Endpoint khusus tombol "✕ Remove" di card.
    Jadi admin tinggal klik tombol tanpa copy-paste machine_id.
    """
    if not is_logged_in(request):
        return redirect(url_for("login"))

    status, text = api_remove(machine_id)

    if status == 200:
        return redirect_with_msg(
            "machines_list",
            msg=f"Device {machine_id} berhasil dicabut 🗑️",
            level="success"
        )
    else:
        return redirect_with_msg(
            "machines_list",
            msg=f"Gagal hapus ({status}): {text}",
            level="danger"
        )


# =======================
# MAIN ENTRYPOINT
# =======================

if __name__ == "__main__":
    # LOCAL DEV RUN:
    #   python app.py
    #
    # PROD (Render) pakai gunicorn:
    #   gunicorn app:app --bind 0.0.0.0:$PORT --workers=2 --threads=4 --timeout=60
    #
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
