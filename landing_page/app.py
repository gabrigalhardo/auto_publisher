# app.py (versão completa e atualizada)

import os
import sys
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from instagram.instagram_api import publish_reel, get_all_accounts
# from instagram.tasks import run_scheduled_reels # Comente ou remova se não estiver usando ainda

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Configurações de upload
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ================= ROTA PARA SERVIR ARQUIVOS =================
# ESSENCIAL: Torna os vídeos enviados acessíveis por uma URL pública
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

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
login_manager.login_view = "index"

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
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
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
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == "POST":
        email = request.form.get("email")
        # O campo de senha no register.html pode ter name="password" ou name="senha"
        senha = request.form.get("password") or request.form.get("senha")
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

    cursor.execute("""
        SELECT p.*, c.username 
        FROM publicacoes p 
        LEFT JOIN contas c ON p.ig_user_id = c.ig_user_id
        WHERE p.usuario_id = %s 
        ORDER BY p.data_hora DESC
    """, (current_user.id,))
    publicacoes = cursor.fetchall()
    
    # Buscar contas do usuário
    cursor.execute("SELECT * FROM contas WHERE usuario_id=%s", (current_user.id,))
    contas = cursor.fetchall()
    db.close()

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
    selected_ig_user_id = request.form.get("conta_id") 
    if not video_file or not legenda or not selected_ig_user_id:
        flash("Preencha todos os campos e selecione a conta!")
        return redirect(url_for("dashboard"))
    filename = secure_filename(f"{int(datetime.now().timestamp())}-{video_file.filename}")
    video_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    video_file.save(video_path)
    result = publish_reel(current_user.id, selected_ig_user_id, video_path, legenda, agendamento)
    flash(result)
    return redirect(url_for("dashboard"))

@app.route('/publicacoes')
@login_required
def publicacoes():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.*, c.username 
        FROM publicacoes p 
        LEFT JOIN contas c ON p.ig_user_id = c.ig_user_id
        WHERE p.usuario_id=%s
        ORDER BY p.data_hora DESC
    """, (current_user.id,))
    publicacoes = cursor.fetchall()
    db.close()
    return render_template("publicacoes.html", publicacoes=publicacoes)

@app.route("/contas")
@login_required
def contas():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, username, ig_user_id FROM contas WHERE usuario_id=%s", (current_user.id,))
    contas_cadastradas = cursor.fetchall()
    db.close()
    return render_template("contas.html", contas=contas_cadastradas)

@app.route("/iniciar_conexao_instagram")
@login_required
def iniciar_conexao_instagram():
    meta_app_id = os.getenv("META_APP_ID")
    redirect_uri = url_for('callback', _external=True)
    scopes = "instagram_basic,pages_show_list,instagram_content_publish,business_management"
    auth_url = (f"https://www.facebook.com/v19.0/dialog/oauth?"
                f"client_id={meta_app_id}&redirect_uri={redirect_uri}&scope={scopes}&response_type=code")
    return redirect(auth_url)

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

    # --- LÓGICA DE OBTENÇÃO DE TOKEN REFORÇADA ---
    try:
        # 1. Trocar código por token de curta duração
        token_url = (f"https://graph.facebook.com/v19.0/oauth/access_token?"
                     f"client_id={meta_app_id}&redirect_uri={redirect_uri}"
                     f"&client_secret={meta_app_secret}&code={code}")
        token_res = requests.get(token_url)
        token_res.raise_for_status() # Lança um erro se a requisição falhar
        token_data = token_res.json()
        if 'error' in token_data:
            raise Exception(f"Erro ao obter token de curta duração: {token_data['error']['message']}")
        
        short_lived_token = token_data['access_token']

        # 2. Trocar token de curta duração por um de longa duração
        long_lived_url = (f"https://graph.facebook.com/oauth/access_token?"
                          f"grant_type=fb_exchange_token&client_id={meta_app_id}"
                          f"&client_secret={meta_app_secret}&fb_exchange_token={short_lived_token}")
        long_lived_res = requests.get(long_lived_url)
        long_lived_res.raise_for_status()
        long_lived_data = long_lived_res.json()
        if 'error' in long_lived_data:
            raise Exception(f"Erro ao obter token de longa duração: {long_lived_data['error']['message']}")

        long_lived_token = long_lived_data['access_token']

        # 3. Obter páginas do usuário
        pages_url = f"https://graph.facebook.com/me/accounts?access_token={long_lived_token}"
        pages_data = requests.get(pages_url).json().get('data', [])
        if not pages_data:
            flash("Nenhuma página do Facebook encontrada. É necessário ter uma página vinculada a uma conta do Instagram Business.")
            return redirect(url_for('contas'))

        # 4. Encontrar conta do Instagram e salvar
        found_ig_account = False
        for page in pages_data:
            page_id = page['id']
            ig_url = (f"https://graph.facebook.com/v19.0/{page_id}?"
                      f"fields=instagram_business_account{{id,username}}"
                      f"&access_token={long_lived_token}")
            ig_data = requests.get(ig_url).json()

            if 'instagram_business_account' in ig_data:
                ig_account = ig_data['instagram_business_account']
                ig_user_id = ig_account['id']
                ig_username = ig_account['username']

                db = get_db()
                cursor = db.cursor()
                cursor.execute(
                    """
                    INSERT INTO contas (usuario_id, username, ig_user_id, access_token) 
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE access_token = VALUES(access_token), username = VALUES(username)
                    """,
                    (current_user.id, ig_username, ig_user_id, long_lived_token)
                )
                db.commit()
                db.close()
                flash(f"Conta do Instagram '{ig_username}' conectada/atualizada com sucesso!")
                found_ig_account = True
        
        if not found_ig_account:
            flash("Nenhuma conta do Instagram Business foi encontrada vinculada às suas páginas do Facebook.")

    except requests.exceptions.RequestException as e:
        flash(f"Erro de rede ao comunicar com a API da Meta: {e}")
    except Exception as e:
        flash(f"Um erro inesperado ocorreu: {e}")

    return redirect(url_for('contas'))

# ================= REMOVER CONTA =================
@app.route("/remover_conta/<string:ig_user_id>", methods=["POST"])
@login_required
def remover_conta(ig_user_id):
    db = get_db()
    cursor = db.cursor()
    try:
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
    
    # Opcional: buscar o caminho do arquivo para deletá-lo do servidor
    cursor.execute("SELECT video FROM publicacoes WHERE id=%s AND usuario_id=%s", (pub_id, current_user.id))
    pub = cursor.fetchone()
    
    cursor.execute("DELETE FROM publicacoes WHERE id=%s AND usuario_id=%s", (pub_id, current_user.id))
    db.commit()
    db.close()
    
    # Deleta o arquivo de vídeo se ele foi encontrado
    if pub and os.path.exists(pub[0]):
        try:
            os.remove(pub[0])
        except OSError as e:
            print(f"Erro ao deletar o arquivo {pub[0]}: {e}")

    flash("Agendamento cancelado com sucesso!")
    return redirect(url_for("publicacoes"))

# ================= LOGOUT =================
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)