import os
import sys
import requests
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
        LEFT JOIN contas c ON p.ig_user_id=c.id 
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
    ig_user_id = request.form.get("ig_user_id")

    if not video_file or not legenda or not ig_user_id:
        flash("Preencha todos os campos e selecione a conta!")
        return redirect(url_for("dashboard"))

    filename = secure_filename(video_file.filename)
    video_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    video_file.save(video_path)

    result = publish_reel(current_user.id, ig_user_id, video_path, legenda, agendamento)
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

# ================= ADICIONAR CONTAS (FLUXO OAUTH) =================

# Rota para exibir a página de gerenciamento de contas
@app.route("/contas")
@login_required
def contas():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, username, ig_user_id FROM contas WHERE usuario_id=%s", (current_user.id,))
    contas_cadastradas = cursor.fetchall()
    db.close()
    return render_template("contas.html", contas=contas_cadastradas)

# Rota para iniciar o fluxo de login com o Facebook
@app.route("/iniciar_conexao_instagram")
@login_required
def iniciar_conexao_instagram():
    meta_app_id = os.getenv("META_APP_ID")
    # A URL de callback deve ser exatamente a mesma cadastrada no painel da Meta
    redirect_uri = url_for('callback', _external=True)

    # Permissões necessárias para buscar páginas e publicar conteúdo no Instagram
    scopes = "instagram_basic,pages_show_list,instagram_content_publish,business_management"
    
    # Monta a URL de autorização do Facebook
    auth_url = (
        f"https://www.facebook.com/v18.0/dialog/oauth?"
        f"client_id={meta_app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scopes}"
        f"&response_type=code"
    )
    return redirect(auth_url)

# Rota de callback que o Facebook chama após a autorização do usuário
@app.route("/callback")
@login_required
def callback():
    code = request.args.get('code')
    if not code:
        flash("Ocorreu um erro durante a autorização. Tente novamente.")
        return redirect(url_for('contas'))

    meta_app_id = os.getenv("META_APP_ID")
    meta_app_secret = os.getenv("META_APP_SECRET")
    redirect_uri = url_for('callback', _external=True)

    # 1. Trocar o código por um Access Token de curta duração
    token_url = (
        f"https://graph.facebook.com/v18.0/oauth/access_token?"
        f"client_id={meta_app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&client_secret={meta_app_secret}"
        f"&code={code}"
    )
    response = requests.get(token_url)
    token_data = response.json()
    if 'error' in token_data:
        flash(f"Erro ao obter o token: {token_data['error']['message']}")
        return redirect(url_for('contas'))
    
    short_lived_token = token_data['access_token']

    # 2. Trocar o token de curta duração por um de longa duração (60 dias)
    long_lived_url = (
        f"https://graph.facebook.com/oauth/access_token?"
        f"grant_type=fb_exchange_token"
        f"&client_id={meta_app_id}"
        f"&client_secret={meta_app_secret}"
        f"&fb_exchange_token={short_lived_token}"
    )
    response = requests.get(long_lived_url)
    long_lived_data = response.json()
    long_lived_token = long_lived_data.get('access_token', short_lived_token) # Usa o de longa duração se disponível

    # 3. Obter as contas de página do usuário
    pages_url = f"https://graph.facebook.com/me/accounts?access_token={long_lived_token}"
    response = requests.get(pages_url)
    pages_data = response.json().get('data', [])

    if not pages_data:
        flash("Nenhuma página do Facebook encontrada. É necessário ter uma página vinculada a uma conta do Instagram Business.")
        return redirect(url_for('contas'))

    # 4. Encontrar a conta do Instagram vinculada e salvar no banco
    found_ig_account = False
    for page in pages_data:
        page_id = page['id']
        # Busca a conta do Instagram Business conectada à página do Facebook
        ig_url = (
            f"https://graph.facebook.com/v18.0/{page_id}?"
            f"fields=instagram_business_account{{id,username}}"
            f"&access_token={long_lived_token}"
        )
        response = requests.get(ig_url)
        ig_data = response.json()

        if 'instagram_business_account' in ig_data:
            ig_account = ig_data['instagram_business_account']
            ig_user_id = ig_account['id']
            ig_username = ig_account['username']

            # Salvar no banco de dados
            db = get_db()
            cursor = db.cursor()
            try:
                # Usamos ON DUPLICATE KEY UPDATE para atualizar o token caso a conta já exista
                cursor.execute(
                    """
                    INSERT INTO contas (usuario_id, username, ig_user_id, access_token) 
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE access_token = VALUES(access_token), username = VALUES(username)
                    """,
                    (current_user.id, ig_username, ig_user_id, long_lived_token)
                )
                db.commit()
                flash(f"Conta do Instagram '{ig_username}' conectada/atualizada com sucesso!")
                found_ig_account = True
            except mysql.connector.Error as err:
                flash(f"Erro ao salvar a conta: {err}")
            finally:
                db.close()
    
    if not found_ig_account:
        flash("Nenhuma conta do Instagram Business foi encontrada vinculada às suas páginas do Facebook.")

    return redirect(url_for('contas'))

# ================= REMOVER CONTA =================
@app.route("/remover_conta/<string:ig_user_id>", methods=["POST"]) # MUDANÇA 1: espera um 'string'
@login_required
def remover_conta(ig_user_id): # MUDANÇA 2: o nome da variável é claro
    db = get_db()
    cursor = db.cursor()
    try:
        # MUDANÇA 3: O comando agora deleta procurando pelo ig_user_id
        cursor.execute(
            "DELETE FROM contas WHERE ig_user_id=%s AND usuario_id=%s",
            (ig_user_id, current_user.id)
        )
        db.commit()

        if cursor.rowcount > 0:
            flash("Conta removida com sucesso!")
        else:
            flash("Não foi possível remover a conta.")
    except mysql.connector.Error as err:
        flash(f"Ocorreu um erro ao remover a conta: {err}")
    finally:
        db.close()
    
    return redirect(url_for('contas'))

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
