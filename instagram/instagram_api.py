# instagram_api.py (versão final com a correção definitiva de envio de parâmetros)

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
        # --- ETAPA 1: INICIAR A SESSÃO DE UPLOAD ---
        init_upload_url = f"{GRAPH_API_URL}/{ig_user_id}/media"
        init_params = {
            'media_type': 'REELS',
            'upload_type': 'resumable',
            'caption': caption,
            'access_token': access_token
        }
        
        # Enviamos os parâmetros na URL (params) para garantir que sejam lidos pela API
        init_res = requests.post(init_upload_url, params=init_params)
        init_data = init_res.json()

        if 'id' not in init_data:
            raise Exception(f"Erro ao iniciar o upload: {init_data.get('error', init_data)}")

        creation_id = init_data['id']

        # --- ETAPA 2: FAZER O UPLOAD DO ARQUIVO ---
        upload_video_url = f"https://rupload.facebook.com/ig-api-upload/v19.0/{creation_id}"
        
        with open(video_path, 'rb') as video_file:
            video_data = video_file.read()
            video_size = str(len(video_data))

            headers = {
                'Authorization': f'OAuth {access_token}',
                'Content-Type': 'application/octet-stream',
                'Content-Length': video_size,
                'Offset': '0'
            }
            
            upload_res = requests.post(upload_video_url, headers=headers, data=video_data)

        upload_data = upload_res.json()
        if not upload_data.get('success'):
             if upload_data.get('debug_info', {}).get('retriable') is False:
                raise Exception(f"Erro durante o upload do arquivo de vídeo: {upload_data}")
        
        # --- ETAPA 3: VERIFICAR O STATUS DO UPLOAD ---
        for _ in range(30): 
            status_url = f"{GRAPH_API_URL}/{creation_id}?fields=status_code&access_token={access_token}"
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
            "UPDATE publicacoes SET status=%s, data_hora=%s, mensagem_erro=NULL WHERE id=%s",
            (status, datetime.now(), publicacao_id)
        )
    else:
        cursor.execute(
            "INSERT INTO publicacoes (usuario_id, ig_user_id, video, legenda, data_hora, status, mensagem_erro) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (usuario_id, ig_user_id, video_path, caption, datetime.now(), status, None if status == 'publicado' else message)
        )
    
    # Se deu erro, atualizamos a mensagem de erro no banco
    if status == "erro":
        # Precisamos pegar o ID da publicação que acabamos de inserir
        pub_id_to_update = publicacao_id
        if not pub_id_to_update:
            # Se foi uma nova inserção, pegamos o último ID inserido
            cursor.execute("SELECT LAST_INSERT_ID() as id")
            res = cursor.fetchone()
            if res:
                pub_id_to_update = res['id']
        
        if pub_id_to_update:
            cursor.execute("UPDATE publicacoes SET mensagem_erro=%s WHERE id=%s", (message, pub_id_to_update))

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