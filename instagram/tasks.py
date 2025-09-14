# tasks.py (versão corrigida e completa)

from datetime import datetime
from .instagram_api import get_db, publish_reel
import os

def run_scheduled_reels():
    """Processa todos os agendamentos no banco"""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Query SQL ajustada para buscar também o usuario_id e ig_user_id
    cursor.execute("""
        SELECT p.id, p.usuario_id, p.ig_user_id, p.video, p.legenda
        FROM publicacoes p
        WHERE p.status='agendado' AND p.data_hora <= %s
    """, (now,))
    
    agendados = cursor.fetchall()
    print(f"[{datetime.now()}] Encontrados {len(agendados)} agendamentos para publicar.")

    for item in agendados:
        # A função de publicação agora é chamada com os parâmetros corretos
        publish_reel(
            usuario_id=item['usuario_id'], 
            ig_user_id=item['ig_user_id'], 
            video_path=item['video'], 
            caption=item['legenda'], 
            publicacao_id=item['id']
        )
    
    cursor.close()
    conn.close()