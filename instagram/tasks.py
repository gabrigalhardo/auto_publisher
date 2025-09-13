from datetime import datetime
from .instagram_api import get_db, publish_reel
import os

def run_scheduled_reels():
    """Processa todos os agendamentos no banco"""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        SELECT p.id, p.video, p.legenda, c.ig_user_id, c.access_token
        FROM publicacoes p
        JOIN contas c ON p.conta_id = c.id
        WHERE p.status='agendado' AND p.data_hora <= %s
    """, (now,))
    
    agendados = cursor.fetchall()
    print(f"[{datetime.now()}] Encontrados {len(agendados)} agendamentos para publicar.")

    for item in agendados:
        video_path = os.path.join('static/videos', item['video'])
        publish_reel(item['access_token'], item['ig_user_id'], video_path, item['legenda'], publicacao_id=item['id'])
    
    cursor.close()
    conn.close()
