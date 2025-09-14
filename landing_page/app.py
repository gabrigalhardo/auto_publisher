import os
import sys
from flask import Flask, render_template, request, redirect, url_for, session, flash
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

# Pasta para salvar uploads temporários
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Função para criar a conexão com o banco de dados MySQL
def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )

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

            session["user_id"] = user["id"]
            session["user_email"] = user["email"]
            return redirect(url_for("dashboard"))
        else:
            flash("Email ou senha incorretos!")
            return redirect(url_for("index"))

    return render_template("login.html")

# ================= REGISTRO =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")
        if not email or not senha:
            flash("Preencha todos os campos!")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(senha)
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute(
                "INSERT INTO usuarios (email, senha, liberado) VALUES (%s, %s, %s)",
                (email, hashed_password, "nao")
            )
            db.commit()
            flash("Cadastro realizado! Aguarde liberação do acesso.")
        except mysql.connector.IntegrityError:
            flash("Email já cadastrado!")
        finally:
            db.close()

        return redirect(url_for("index"))

    return render_template("register.html")

# ================= DASHBOARD =================
@app.route("/dashboard", methods=["GET"])
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("index"))

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Buscar publicações do usuário
    cursor.execute("SELECT p.*, c.username FROM publicacoes p LEFT JOIN contas c ON p.conta_id=c.id WHERE p.usuario_id=%s ORDER BY p.data_hora DESC", (session["user_id"],))
    publicacoes = cursor.fetchall()
    db.close()

    # Buscar contas do usuário
    contas = get_all_accounts(session["user_id"])

    return render_template(
        "dashboard.html",
        publicacoes=publicacoes,
        user_email=session["user_email"],
        contas=contas
    )

# ================= UPLOAD DE VÍDEO =================
@app.route("/upload_video", methods=["POST"])
def upload_video():
    if "user_id" not in session:
        return redirect(url_for("index"))

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

    # Publicar ou agendar o vídeo
    result = publish_reel(session["user_id"], conta_id, video_path, legenda, agendamento)
    flash(result)

    return redirect(url_for("dashboard"))

@app.route('/publicacoes')
def publicacoes():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM publicacoes")
    publicacoes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("publicacoes.html", publicacoes=publicacoes)


# ================= ADICIONAR CONTAS =================
@app.route("/contas", methods=["GET", "POST"])
def contas():
    if "user_id" not in session:
        return redirect(url_for("index"))

    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":
        username = request.form.get("username")
        ig_user_id = request.form.get("ig_user_id")
        access_token = request.form.get("access_token")

        if username and ig_user_id and access_token:
            cursor.execute(
                "INSERT INTO contas (usuario_id, username, ig_user_id, access_token) VALUES (%s, %s, %s, %s)",
                (session["user_id"], username, ig_user_id, access_token)
            )
            db.commit()
            flash("Conta adicionada com sucesso!")
        else:
            flash("Preencha todos os campos!")

    # Buscar contas do usuário
    cursor.execute("SELECT id, username, ig_user_id FROM contas WHERE usuario_id=%s", (session["user_id"],))
    contas = cursor.fetchall()
    db.close()

    return render_template("contas.html", contas=contas)

# ================= CANCELAR AGENDAMENTO =================
@app.route("/cancel_agendamento/<int:pub_id>", methods=["POST"])
def cancel_agendamento(pub_id):
    if "user_id" not in session:
        return redirect(url_for("index"))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM publicacoes WHERE id=%s AND usuario_id=%s", (pub_id, session["user_id"]))
    db.commit()
    db.close()
    flash("Agendamento cancelado com sucesso!")
    return redirect(url_for("dashboard"))

# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
