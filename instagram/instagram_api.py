import os
import mysql.connector
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

GRAPH_API_URL = "https://graph.facebook.com/v18.0"

# Função para criar a conexão com o banco de dados MySQL
def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )

def publish_reel(usuario_id, conta_id, video_path, caption, agendamento=None, publicacao_id=None):
    """
    Publica ou agenda um Reel no Instagram.
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Buscar conta e token
    cursor.execute("SELECT * FROM contas WHERE id=%s AND usuario_id=%s", (conta_id, usuario_id))
    conta = cursor.fetchone()
    if not conta:
        db.close()
        return "Conta não encontrada."

    access_token = conta['access_token']
    ig_user_id = conta['ig_user_id']

    # Se tiver agendamento futuro, salva no banco como 'agendado'
    if agendamento:
        cursor.execute(
            "INSERT INTO publicacoes (usuario_id, conta_id, video, legenda, data_hora, status) VALUES (%s,%s,%s,%s,%s,%s)",
            (usuario_id, conta_id, video_path, caption, agendamento, "agendado")
        )
        db.commit()
        db.close()
        return "Vídeo agendado com sucesso!"

    # Senão, publica imediatamente
    if not os.path.exists(video_path):
        db.close()
        return "Arquivo de vídeo não encontrado."

    files = {'file': open(video_path, 'rb')}
    params = {
        'caption': caption,
        'media_type': 'VIDEO',
        'access_token': access_token
    }

    upload_url = f"{GRAPH_API_URL}/{ig_user_id}/media"
    res = requests.post(upload_url, files=files, data=params)
    res_json = res.json()
    files['file'].close()

    if 'id' not in res_json:
        db.close()
        return f"Erro ao criar mídia: {res_json}"

    creation_id = res_json['id']

    publish_url = f"{GRAPH_API_URL}/{ig_user_id}/media_publish"
    publish_res = requests.post(publish_url, data={'creation_id': creation_id, 'access_token': access_token})
    publish_json = publish_res.json()

    status = "publicado" if 'id' in publish_json else "erro"

    # Se já existia um registro no banco (agendado), atualiza, senão cria novo
    if publicacao_id:
        cursor.execute(
            "UPDATE publicacoes SET status=%s, data_hora=%s WHERE id=%s",
            (status, datetime.now(), publicacao_id)
        )
    else:
        cursor.execute(
            "INSERT INTO publicacoes (usuario_id, conta_id, video, legenda, data_hora, status) VALUES (%s,%s,%s,%s,%s,%s)",
            (usuario_id, conta_id, video_path, caption, datetime.now(), status)
        )

    db.commit()
    db.close()

    if status == "publicado":
        return "Vídeo publicado com sucesso!"
    else:
        return f"Erro ao publicar: {publish_json}"

def get_all_accounts(usuario_id=None):
    """
    Retorna todas as contas cadastradas.
    Se usuario_id for fornecido, filtra apenas as contas desse usuário.
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)

    if usuario_id:
        cursor.execute("SELECT * FROM contas WHERE usuario_id=%s", (usuario_id,))
    else:
        cursor.execute("SELECT * FROM contas")

    contas = cursor.fetchall()
    db.close()
    return contas
