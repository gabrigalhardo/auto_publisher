# instagram_api.py (versão final simplificada com multipart/form-data)

import os
import mysql.connector
import requests
from datetime import datetime
from dotenv import load_dotenv
import time
import json

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
    """Publica ou agenda um Reel no Instagram."""
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
        # --- ETAPA 1 e 2 COMBINADAS: Upload do vídeo via formulário ---
        # Esta é a forma mais simples e direta de enviar um vídeo
        video_upload_url = f"{GRAPH_API_URL}/{ig_user_id}/media"
        
        payload = {
            'media_type': 'REELS', # Usando o tipo correto que a API exige
            'caption': caption,
            'access_token': access_token
        }
        
        with open(video_path, 'rb') as video_file:
            files = {
                # O nome do campo do arquivo DEVE ser 'video', mas o requests trata isso
                # implicitamente. Vamos deixar explícito para clareza.
                'source': video_file
            }
            upload_res = requests.post(video_upload_url, data=payload, files=files)

        upload_data = upload_res.json()

        if 'id' not in upload_data:
            raise Exception(f"Erro ao criar o contêiner de mídia: {upload_data.get('error', upload_data)}")

        creation_id = upload_data['id']
        
        # --- ETAPA 3: VERIFICAR O STATUS DO UPLOAD ---
        for _ in range(30): 
            status_url = f"{GRAPH_API_URL}/{creation_id}?fields=status_code&access_token={access_token}"
            status_res = requests.get(status_url)
            status_data = status_res.json()
            status_code = status_data.get('status_code')
            if status_code == 'FINISHED':
                break
            if status_code == 'ERROR':
                 raise Exception("Ocorreu um erro no processamento do vídeo pela Meta.")
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