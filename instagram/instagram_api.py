# instagram_api.py (versão completa e atualizada com melhor tratamento de erro)

import os
import mysql.connector
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

GRAPH_API_URL = "https://graph.facebook.com/v18.0"

def get_db():
    """Função para criar a conexão com o banco de dados MySQL."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )

def publish_reel(usuario_id, ig_user_id, video_path, caption, agendamento=None, publicacao_id=None):
    """
    Publica ou agenda um Reel no Instagram.
    Recebe o ig_user_id diretamente para identificar a conta.
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM contas WHERE ig_user_id=%s AND usuario_id=%s", (ig_user_id, usuario_id))
    conta = cursor.fetchone()
    if not conta:
        db.close()
        return "Conta não encontrada ou não pertence a este usuário."

    access_token = conta['access_token']

    if agendamento:
        cursor.execute(
            "INSERT INTO publicacoes (usuario_id, ig_user_id, video, legenda, data_hora, status) VALUES (%s,%s,%s,%s,%s,%s)",
            (usuario_id, ig_user_id, video_path, caption, agendamento, "agendado")
        )
        db.commit()
        db.close()
        return "Vídeo agendado com sucesso!"

    if not os.path.exists(video_path):
        db.close()
        return "Arquivo de vídeo não encontrado."

    # Passo 1: Fazer o upload do vídeo para obter um creation_id
    files = {'file': open(video_path, 'rb')}
    params = {
        'caption': caption,
        'media_type': 'REELS',
        'access_token': access_token
    }

    upload_url = f"{GRAPH_API_URL}/{ig_user_id}/media"
    res = requests.post(upload_url, files=files, data=params)
    files['file'].close() # Fechamos o arquivo aqui para liberar recursos

    # CORREÇÃO: Verificamos a resposta da API ANTES de tentar processar como JSON
    if res.status_code != 200 or not res.text.strip().startswith('{'):
        db.close()
        # Retorna uma mensagem de erro mais clara, incluindo o que a API respondeu
        return f"Erro na API da Meta ao tentar criar mídia. Status: {res.status_code}. Resposta: {res.text}"

    res_json = res.json()

    if 'id' not in res_json:
        db.close()
        return f"Erro ao criar mídia: {res_json}"

    creation_id = res_json['id']

    # Passo 2: Publicar o vídeo usando o creation_id
    publish_url = f"{GRAPH_API_URL}/{ig_user_id}/media_publish"
    publish_res = requests.post(publish_url, data={'creation_id': creation_id, 'access_token': access_token})
    publish_json = publish_res.json()

    status = "publicado" if 'id' in publish_json else "erro"

    # Salva ou atualiza o status no banco de dados
    if publicacao_id:
        cursor.execute(
            "UPDATE publicacoes SET status=%s, data_hora=%s WHERE id=%s",
            (status, datetime.now(), publicacao_id)
        )
    else:
        cursor.execute(
            "INSERT INTO publicacoes (usuario_id, ig_user_id, video, legenda, data_hora, status) VALUES (%s,%s,%s,%s,%s,%s)",
            (usuario_id, ig_user_id, video_path, caption, datetime.now(), status)
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