# instagram_api.py (versão final com publicação via video_url)

import os
import mysql.connector
import requests
from datetime import datetime
from dotenv import load_dotenv
import time
from flask import url_for # Importante para criar a URL pública

load_dotenv()

GRAPH_API_URL = "https://graph.facebook.com/v19.0"

def get_db():
    """Cria a conexão com o banco de dados."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )

def publish_reel(usuario_id, ig_user_id, video_path, caption, agendamento=None, publicacao_id=None):
    """Publica ou agenda um Reel no Instagram usando o método video_url."""
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM contas WHERE ig_user_id=%s AND usuario_id=%s", (ig_user_id, usuario_id))
    conta = cursor.fetchone()
    if not conta:
        db.close()
        return "Conta não encontrada ou não pertence a este usuário."

    access_token = conta['access_token']

    # Se for agendamento, apenas salvamos no banco para ser processado depois
    if agendamento:
        cursor.execute(
            "INSERT INTO publicacoes (usuario_id, ig_user_id, video, legenda, data_hora, status, mensagem_erro) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (usuario_id, ig_user_id, video_path, caption, agendamento, "agendado", None)
        )
        db.commit()
        db.close()
        return "Vídeo agendado com sucesso!"

    # Se não for agendamento, publica imediatamente
    if not os.path.exists(video_path):
        db.close()
        return "Arquivo de vídeo não encontrado."

    try:
        # --- ETAPA 1: Criar a URL pública para o nosso vídeo salvo ---
        # O nome do arquivo é extraído do caminho completo
        video_filename = os.path.basename(video_path)
        # O _external=True é crucial para gerar a URL completa (https://...)
        public_video_url = url_for('uploaded_file', filename=video_filename, _external=True)

        # --- ETAPA 2: Criar o contêiner de mídia passando a video_url ---
        container_url = f"{GRAPH_API_URL}/{ig_user_id}/media"
        container_params = {
            'media_type': 'REELS',
            'video_url': public_video_url,
            'caption': caption,
            'access_token': access_token
        }
        container_res = requests.post(container_url, data=container_params)
        container_data = container_res.json()

        if 'id' not in container_data:
            raise Exception(f"Erro ao criar o contêiner de mídia: {container_data.get('error', container_data)}")

        creation_id = container_data['id']
        
        # --- ETAPA 3: VERIFICAR O STATUS (A Meta vai baixar e processar o vídeo) ---
        for _ in range(30): 
            status_url = f"{GRAPH_API_URL}/{creation_id}?fields=status_code,status&access_token={access_token}"
            status_res = requests.get(status_url)
            status_data = status_res.json()
            status_code = status_data.get('status_code')
            
            if status_code == 'FINISHED':
                break
            if status_code == 'ERROR':
                 error_details = status_data.get('status', 'Erro desconhecido')
                 raise Exception(f"O processamento do vídeo pela Meta falhou. Detalhes: {error_details}")
            time.sleep(5) 
        else:
            raise Exception(f"Processamento do vídeo demorou demais. Status: {status_code}")

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
            "UPDATE publicacoes SET status=%s, data_hora=%s, mensagem_erro=%s WHERE id=%s",
            (status, datetime.now(), None if status == 'publicado' else message, publicacao_id)
        )
    else:
        cursor.execute(
            "INSERT INTO publicacoes (usuario_id, ig_user_id, video, legenda, data_hora, status, mensagem_erro) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (usuario_id, ig_user_id, video_path, caption, datetime.now(), status, None if status == 'publicado' else message)
        )
    
    # Se deu erro, e foi uma nova publicação, precisamos garantir que a mensagem de erro seja salva
    if status == "erro" and not publicacao_id:
        # Pegamos o ID da publicação que acabamos de inserir
        last_id = cursor.lastrowid
        if last_id:
            cursor.execute(
                "UPDATE publicacoes SET mensagem_erro=%s WHERE id=%s",
                (message, last_id)
            )

    db.commit()
    db.close()
    
    return message

def get_all_accounts(usuario_id=None):
    """Retorna todas as contas cadastradas."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    if usuario_id:
        cursor.execute("SELECT * FROM contas WHERE usuario_id=%s", (usuario_id,))
    else:
        cursor.execute("SELECT * FROM contas")
    contas = cursor.fetchall()
    db.close()
    return contas