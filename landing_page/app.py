import os
import sys
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from instagram.instagram_api import publish_reel, get_all_accounts
from instagram.tasks import run_scheduled_reels

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Configurações de upload
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ================= MYSQL =================
def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )

# ================= FLASK-LOGIN =================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "index"  # Página de login

# User class para Flask-Login
class User(UserMixin):
    def __init__(self, id, username, email):
        self.id = id
        self.username = username
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM usuarios WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    db.close()
    if user:
        return User(id=user["id"], username=user["username"], email=user["email"])
    return None

# ================= LOGIN =================
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")
        if not email or not senha:
            flash("Preencha todos os campos!")
            return redirect(url_for("index"))

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE email=%s", (email,))
        user = cursor.fetchone()
        db.close()

        if user and check_password_hash(user["senha"], senha):
            if user["liberado"] != "sim":
                flash("Seu cadastro ainda não foi liberado!")
                return redirect(url_for("index"))

            user_obj = User(id=user["id"], username=user["username"], email=user["email"])
            login_user(user_obj)
            return redirect(url_for("dashboard"))
        else:
            flash("Email ou senha incorretos!")
            return redirect(url_for("index"))

    return render_template("login.html", hide_sidebar=True)

# ================= REGISTRO =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("password")
        username = request.form.get("username")

        if not email or not senha or not username:
            flash("Preencha todos os campos!")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(senha)
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute(
                "INSERT INTO usuarios (username, email, senha, liberado) VALUES (%s, %s, %s, %s)",
                (username, email, hashed_password, "nao")
            )
            db.commit()
            flash("Cadastro realizado! Aguarde liberação do acesso.")
        except mysql.connector.IntegrityError:
            flash("Email já cadastrado!")
        finally:
            db.close()

        return redirect(url_for("index"))

    return render_template("register.html", hide_sidebar=True)

# ================= DASHBOARD =================
@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Buscar publicações do usuário
    cursor.execute("""
        SELECT p.*, c.username 
        FROM publicacoes p 
        LEFT JOIN contas c ON p.conta_id=c.id 
        WHERE p.usuario_id=%s 
        ORDER BY p.data_hora DESC
    """, (current_user.id,))
    publicacoes = cursor.fetchall()
    db.close()

    # Buscar contas do usuário
    contas = get_all_accounts(current_user.id)

    return render_template(
        "dashboard.html",
        publicacoes=publicacoes,
        contas=contas
    )

# ================= UPLOAD DE VÍDEO =================
@app.route("/upload_video", methods=["POST"])
@login_required
def upload_video():
    video_file = request.files.get("video")
    legenda = request.form.get("legenda")
    agendamento = request.form.get("agendamento")
    conta_id = request.form.get("conta_id")

    if not video_file or not legenda or not conta_id:
        flash("Preencha todos os campos e selecione a conta!")
        return redirect(url_for("dashboard"))

    filename = secure_filename(video_file.filename)
    video_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    video_file.save(video_path)

    result = publish_reel(current_user.id, conta_id, video_path, legenda, agendamento)
    flash(result)

    return redirect(url_for("dashboard"))

# ================= PUBLICAÇÕES =================
@app.route('/publicacoes')
@login_required
def publicacoes():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM publicacoes")
    publicacoes = cursor.fetchall()
    db.close()
    return render_template("publicacoes.html", publicacoes=publicacoes)

# ================= ADICIONAR CONTAS =================
@app.route("/contas", methods=["GET", "POST"])
@login_required
def contas():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":
        username = request.form.get("username")
        ig_user_id = request.form.get("ig_user_id")
        access_token = request.form.get("access_token")

        if username and ig_user_id and access_token:
            cursor.execute(
                "INSERT INTO contas (usuario_id, username, ig_user_id, access_token) VALUES (%s, %s, %s, %s)",
                (current_user.id, username, ig_user_id, access_token)
            )
            db.commit()
            flash("Conta adicionada com sucesso!")
        else:
            flash("Preencha todos os campos!")

    cursor.execute("SELECT id, username, ig_user_id FROM contas WHERE usuario_id=%s", (current_user.id,))
    contas = cursor.fetchall()
    db.close()

    return render_template("contas.html", contas=contas)

# ================= CANCELAR AGENDAMENTO =================
@app.route("/cancel_agendamento/<int:pub_id>", methods=["POST"])
@login_required
def cancel_agendamento(pub_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM publicacoes WHERE id=%s AND usuario_id=%s", (pub_id, current_user.id))
    db.commit()
    db.close()
    flash("Agendamento cancelado com sucesso!")
    return redirect(url_for("dashboard"))

# ================= LOGOUT =================
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
