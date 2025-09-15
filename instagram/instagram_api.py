# instagram_api.py (versão final com upload em duas etapas)

import os
import mysql.connector
import requests
from datetime import datetime
from dotenv import load_dotenv
import time

load_dotenv()

GRAPH_API_URL = "https://graph.facebook.com/v19.0" # Atualizado para a versão mais recente da API

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
    Publica ou agenda um Reel no Instagram usando o fluxo de upload em duas etapas.
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

    try:
        # --- ETAPA 1: INICIAR A SESSÃO DE UPLOAD ---
        init_upload_url = f"{GRAPH_API_URL}/{ig_user_id}/media"
        init_params = {
            'media_type': 'REELS',
            'caption': caption,
            'access_token': access_token
        }
        init_res = requests.post(init_upload_url, data=init_params)
        init_data = init_res.json()

        if 'id' not in init_data:
            raise Exception(f"Erro ao iniciar o upload: {init_data}")

        creation_id = init_data['id']

        # --- ETAPA 2: FAZER O UPLOAD DO ARQUIVO PARA A URL FORNECIDA ---
        # A API de vídeo exige um endpoint diferente para o upload real do arquivo
        upload_video_url = f"{GRAPH_API_URL}/{creation_id}"
        headers = {
            'Authorization': f'OAuth {access_token}',
        }
        with open(video_path, 'rb') as video_file:
            upload_res = requests.post(upload_video_url, headers=headers, data=video_file)
        
        upload_data = upload_res.json()
        if not upload_data.get('success'):
             raise Exception(f"Erro durante o upload do arquivo de vídeo: {upload_data}")


        # --- ETAPA 3: VERIFICAR O STATUS DO UPLOAD (Opcional, mas boa prática) ---
        # O processamento do vídeo pode levar um tempo.
        # Vamos verificar o status algumas vezes antes de tentar publicar.
        for _ in range(5): # Tenta verificar 5 vezes
            status_url = f"{GRAPH_API_URL}/{creation_id}?fields=status_code&access_token={access_token}"
            status_res = requests.get(status_url)
            status_data = status_res.json()
            if status_data.get('status_code') == 'FINISHED':
                break
            time.sleep(5) # Espera 5 segundos entre as verificações
        else: # Se o loop terminar sem 'break'
            raise Exception(f"Processamento do vídeo demorou demais. Status: {status_data.get('status_code')}")


        # --- ETAPA 4: PUBLICAR O CONTEÚDO ---
        publish_url = f"{GRAPH_API_URL}/{ig_user_id}/media_publish"
        publish_params = {
            'creation_id': creation_id,
            'access_token': access_token
        }
        publish_res = requests.post(publish_url, data=publish_params)
        publish_data = publish_res.json()

        if 'id' not in publish_data:
            raise Exception(f"Erro ao publicar a mídia: {publish_data}")

        status = "publicado"
        message = "Vídeo publicado com sucesso!"

    except Exception as e:
        status = "erro"
        message = str(e)

    # --- SALVAR O RESULTADO FINAL NO BANCO DE DADOS ---
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
    
    return message


def get_all_accounts(usuario_id=None):
    """
    Retorna todas as contas cadastradas.
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