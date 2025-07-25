from flask import Flask, Response, render_template, request, jsonify
import yt_dlp
import os
import json
import time
from threading import Thread, Lock
import logging
import re
from collections import deque
import configparser
import shutil
import traceback
import subprocess
import requests

app = Flask(__name__, static_folder='static')
# Configuración
config = configparser.ConfigParser()
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, 'config.ini')
config.read(config_path)

if 'General' not in config:
    config['General'] = {}
if 'FFmpeg' not in config:
    config['FFmpeg'] = {}

DOWNLOAD_FOLDER = config['General'].get('download_folder', 'downloads')
FFMPEG_PATH = config['FFmpeg'].get('ffmpeg_path', r'C:\ffmpeg\ffmpeg-7.0.2-full_build\bin')

app.config['DOWNLOAD_FOLDER'] = DOWNLOAD_FOLDER
logging.basicConfig(level=logging.DEBUG) # Cambiar a DEBUG para más detalles
logger = logging.getLogger(__name__)

# Configurar el logger de yt_dlp para ver mensajes de depuración
yt_dlp_logger = logging.getLogger('yt_dlp')
yt_dlp_logger.setLevel(logging.DEBUG)

os.environ['PATH'] += os.pathsep + FFMPEG_PATH

FFMPEG_READY = False # Global flag for FFmpeg status

def _check_ffmpeg_path():
    """Verifica si ffmpeg es accesible en la ruta configurada."""
    global FFMPEG_READY
    ffmpeg_executable = shutil.which('ffmpeg')
    if not ffmpeg_executable:
        logger.error(f"FFmpeg no encontrado en la ruta: {FFMPEG_PATH}. Asegúrate de que FFmpeg esté instalado y su ruta esté configurada correctamente en config.ini.")
        FFMPEG_READY = False
        return False
    logger.info(f"FFmpeg encontrado en: {ffmpeg_executable}")
    FFMPEG_READY = True
    return True

# Sistema centralizado de progreso
progress_data = {
    'progress': 0,
    'completed_songs': deque(maxlen=100),
    'lock': Lock(),
    'total_songs': 1,
    'current_song': 0,
    'error': None,
    'status': 'idle', # New status: idle, downloading, finished, error
    'cancel_requested': False
}

def embed_thumbnail_manually(filepath, thumbnail_path, artist=None, album=None):
    """Incrusta portada y escribe artist/album en las etiquetas ID3."""
    logger.info(f"Intentando incrustar miniatura desde {thumbnail_path} en {filepath}")
    if not os.path.exists(thumbnail_path):
        logger.error(f"El archivo de la miniatura no existe en {thumbnail_path}")
        return False

    try:
        temp_file = filepath + ".temp.mp3"
        
        # Comando para incrustar la miniatura
        cmd = [
            'ffmpeg',
            '-i', filepath,         # Archivo de audio de entrada
            '-i', thumbnail_path,   # Archivo de miniatura
            '-c', 'copy',           # Copiar streams sin re-encodear
            '-map', '0',            # Mapear todos los streams del primer archivo
            '-map', '1',            # Mapear todos los streams del segundo archivo
            '-id3v2_version', '3',  # Usar ID3v2.3 para compatibilidad
            '-metadata:s:v', 'title="Album cover"',
            '-metadata:s:v', 'comment="Cover (front)"',
        ]
        # Añadimos artist y album si los tenemos
        if artist:
            cmd += ['-metadata', f'artist={artist}']
        if album:
            cmd += ['-metadata', f'album={album}']
        cmd.append(temp_file)               # Archivo temporal de salida
        
        logger.info(f"Ejecutando comando FFmpeg: {' '.join(cmd)}")
        # Ejecutar FFmpeg
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Salida de FFmpeg: {result.stdout}")
        logger.error(f"Errores de FFmpeg: {result.stderr}")

        
        # Reemplazar el archivo original
        os.replace(temp_file, filepath)
        logger.info(f"Archivo temporal {temp_file} reemplazado por {filepath}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error de FFmpeg al incrustar la miniatura: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Error incrustando miniatura: {str(e)}")
        return False

def progress_hook(d):
    with progress_data['lock']:
        if progress_data['cancel_requested']:
            raise Exception("Download cancelled by user.")
        if d['status'] == 'downloading':
            try:
                percent_str = d['_percent_str']
                clean_percent = ''.join(c for c in percent_str if c.isdigit() or c == '.')
                current_progress = float(clean_percent) if clean_percent else 0
                
                base_progress = (progress_data['current_song'] / progress_data['total_songs']) * 100
                song_progress = (current_progress / 100) * (100 / progress_data['total_songs'])
                progress_data['progress'] = min(int(base_progress + song_progress), 100)
                logger.info(f"Descargando: {d['filename']} - {progress_data['progress']}%")
                
            except (ValueError, ZeroDivisionError) as e:
                logger.error(f"Error al calcular el progreso: {e}")
                progress_data['progress'] = 0
                
        elif d['status'] == 'finished':
            if 'info_dict' in d:
                title = d['info_dict'].get('title', 'Título Desconocido')
                thumbnail = d['info_dict'].get('thumbnail', '')
                artist = d['info_dict'].get('artist', 'Artista Desconocido')
                album = d['info_dict'].get('album', 'Álbum Desconocido')
                
                # Obtener la ruta real del archivo descargado
                filepath = None
                if d.get('info_dict', {}).get('requested_downloads'):
                    filepath = d['info_dict']['requested_downloads'][0].get('filepath')
                elif d['info_dict'].get('filepath'):
                    filepath = d['info_dict'].get('filepath')
                
                
                # Agregar a la lista de canciones completadas
                progress_data['completed_songs'].append({
                    'title': title, 
                    'thumbnail': thumbnail,
                    'artist': artist,
                    'album': album
                })
                progress_data['current_song'] += 1
                logger.info(f"Descarga completada: {title}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/progress')
def progress():
    def generate():
        last_song_count = 0
        while True:
            with progress_data['lock']:
                # Obtener solo nuevas canciones completadas
                new_songs = list(progress_data['completed_songs'])
                if len(new_songs) > last_song_count:
                    new_songs = new_songs[last_song_count:]
                    last_song_count = len(progress_data['completed_songs'])
                else:
                    new_songs = []
                
                data = {
                    'progress': progress_data['progress'],
                    'new_completed_songs': new_songs,
                    'error': progress_data['error'],
                    'status': progress_data['status'] # Send the status
                }
            
            yield f"data: {json.dumps(data)}\n\n"
            time.sleep(0.5)  # Actualización más frecuente
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/download_info', methods=['POST'])
def download_info():
    try:
        data = request.get_json()
        url = data.get('url')
        if not url:
            raise ValueError("URL no proporcionada")

        url = _normalize_url(url)

        # Use extract_flat=False to ensure full metadata for all entries in a playlist
        # Set quiet=False and verbose=True for detailed debugging output from yt-dlp
        ydl_opts = {'quiet': False, 'verbose': True, 'ignoreerrors': True, 'extract_flat': False}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                logger.info(f"Attempting to extract info for URL: {url}")
                info = ydl.extract_info(url, download=False)
                
                if info:
                    logger.info(f"Successfully extracted info. Type: {info.get('_type')}, Title: {info.get('title')}")
                    if info.get('_type') == 'playlist':
                        songs = []
                        # Ensure 'entries' is a list and not None
                        for entry in info.get('entries', []):
                            if entry: # Check if entry is not None (can happen with ignoreerrors)
                                thumbnail_url = entry.get('thumbnail')
                                if not thumbnail_url and entry.get('thumbnails'):
                                    thumbnails = sorted(entry['thumbnails'], key=lambda x: x.get('width', 0), reverse=True)
                                    if thumbnails:
                                        thumbnail_url = thumbnails[0].get('url')

                                songs.append({
                                    'title': entry.get('title', 'Título Desconocido'),
                                    'thumbnail': thumbnail_url or 'https://via.placeholder.com/120?text=No+Thumbnail',
                                    'artist': entry.get('artist', 'Artista Desconocido'),
                                    'album': entry.get('album', 'Álbum Desconocido')
                                })
                        logger.info(f"Playlist info extracted: {len(songs)} songs found.")
                        return jsonify({
                            'title': info.get('title', 'Título Desconocido'),
                            'type': 'playlist',
                            'count': len(songs),
                            'songs': songs
                        })
                    else: # Handle single video or other types that are not playlists
                        thumbnail_url = info.get('thumbnail')
                        if not thumbnail_url and info.get('thumbnails'):
                            thumbnails = sorted(info['thumbnails'], key=lambda x: x.get('width', 0), reverse=True)
                            if thumbnails:
                                thumbnail_url = thumbnails[0].get('url')
                        logger.info(f"Single video info extracted: {info.get('title')}")
                        return jsonify({
                            'title': info.get('title', 'Título Desconocido'),
                            'type': 'video',
                            'count': 1,
                            'songs': [{
                                'title': info.get('title', 'Título Desconocido'),
                                'thumbnail': thumbnail_url or 'https://via.placeholder.com/120?text=No+Thumbnail',
                                'artist': info.get('artist', 'Artista Desconocido'),
                                'album': info.get('album', 'Álbum Desconocido')
                            }]
                        })
                else:
                    logger.warning(f"yt-dlp returned no info for URL: {url}")
                    return jsonify({'error': "No se pudo obtener información del video/playlist. La URL podría ser inválida o el contenido no está disponible."}), 400
            except yt_dlp.utils.DownloadError as e:
                logger.error(f"yt_dlp DownloadError in download_info: {e}")
                return jsonify({'error': f"Download error: {str(e)}"}), 400
            except ValueError as e:
                logger.error(f"ValueError in download_info: {e}")
                return jsonify({'error': f"Invalid input: {str(e)}"}), 400
            except TypeError as e:
                logger.error(f"TypeError in download_info: {e}")
                return jsonify({'error': f"Type error: {str(e)}"}), 400
            except Exception as e:
                logger.error(f"Unexpected error in download_info: {e}\n{traceback.format_exc()}")
                return jsonify({'error': f"An unexpected error occurred: {str(e)}"}), 400

    except Exception as e:
        logger.error(f"Error al obtener información: {e}\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 400

@app.route('/save_ffmpeg_path', methods=['POST'])
def save_ffmpeg_path():
    try:
        data = request.get_json()
        new_path = data.get('ffmpeg_path')
        if not new_path:
            return jsonify({'success': False, 'error': 'Ruta no proporcionada.'}), 400

        config['FFmpeg']['ffmpeg_path'] = new_path
        with open('config.ini', 'w') as configfile:
            config.write(configfile)
        
        # Actualizar la variable de entorno y verificar FFmpeg
        os.environ['PATH'] = os.pathsep.join(filter(None, [new_path] + os.environ['PATH'].split(os.pathsep)))
        if _check_ffmpeg_path():
            return jsonify({'success': True, 'message': 'Ruta de FFmpeg guardada y verificada con éxito.'})
        else:
            return jsonify({'success': False, 'error': 'FFmpeg no encontrado en la nueva ruta. Por favor, verifica la ruta.'}), 400
    except Exception as e:
        logger.error(f"Error al guardar la ruta de FFmpeg: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': f"Error interno al guardar la ruta: {str(e)}"}), 500

@app.route('/start_download', methods=['POST'])
def start_download():
    try:
        if not FFMPEG_READY:
            log_msg = "FFmpeg no está configurado correctamente. La descarga no puede iniciar."
            logger.error(log_msg)
            return jsonify({'error': log_msg}), 500

        data = request.get_json()
        url = data.get('url')
        selected_songs = data.get('selected_songs', [])
        quality = data.get('quality', '320') # Default to 320 if not provided
        output_format = data.get('format', 'mp3') # Default to mp3 if not provided

        if not url:
            raise ValueError("URL no proporcionada")
        
        # Resetear el progreso antes de comenzar
        with progress_data['lock']:
            progress_data['progress'] = 0
            progress_data['completed_songs'].clear()
            progress_data['current_song'] = 0
            progress_data['error'] = None
            progress_data['cancel_requested'] = False

        def download_task():
            logger.info("Iniciando hilo de descarga...")
            success = False
            try:
                download_url = _normalize_url(url)
                ydl_opts = _configure_ydl_options(quality)

                total_songs = _get_total_songs(download_url)
                with progress_data['lock']:
                    progress_data['total_songs'] = total_songs

                _configure_playlist_items(ydl_opts, selected_songs)

                logger.debug(f"Opciones de yt-dlp: {ydl_opts}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    retries = 3
                    for attempt in range(retries):
                        try:
                            ydl.download([download_url])
                            success = True
                            break
                        except yt_dlp.utils.DownloadError as e:
                            log_msg = f"Advertencia en descarga (intento {attempt + 1}/{retries}): {e}"
                            logger.warning(log_msg)
                            with progress_data['lock']:
                                progress_data['error'] = log_msg
                            if attempt == retries - 1:
                                raise
            except yt_dlp.utils.DownloadError as e:
                log_msg = f"Algunos videos no pudieron descargarse: {e}"
                logger.warning(log_msg)
                with progress_data['lock']:
                    progress_data['error'] = log_msg
                    progress_data['status'] = 'error'
            except Exception as e:
                log_msg = f"Error crítico en descarga: {e}"
                logger.exception(log_msg)
                with progress_data['lock']:
                    progress_data['error'] = log_msg
                    progress_data['status'] = 'error'
                    if "cancelled by user" in str(e):
                        progress_data['error'] = "Download cancelled."
            finally:
                if success:
                    with progress_data['lock']:
                        progress_data['status'] = 'finished'
                        progress_data['progress'] = 100
                
                time.sleep(2)
                
                with progress_data['lock']:
                    progress_data['status'] = 'idle'
                    progress_data['progress'] = 0

        Thread(target=download_task).start()
        return jsonify({'status': 'started'})
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt_dlp DownloadError: {e}\n{traceback.format_exc()}")
        return jsonify({'error': f"Download error: {str(e)}"}), 400
    except ValueError as e:
        logger.error(f"ValueError: {e}\n{traceback.format_exc()}")
        return jsonify({'error': f"Invalid input: {str(e)}"}), 400
    except TypeError as e:
        logger.error(f"TypeError: {e}\n{traceback.format_exc()}")
        return jsonify({'error': f"Type error: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
        return jsonify({'error': f"An unexpected error occurred: {str(e)}"}), 400

@app.route('/clear_history', methods=['POST'])
def clear_history():
    try:
        with progress_data['lock']:
            progress_data['completed_songs'].clear()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error clearing history: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/cancel_download', methods=['POST'])
def cancel_download():
    try:
        with progress_data['lock']:
            progress_data['cancel_requested'] = True
        logger.info("Cancel download requested by user.")
        return jsonify({'status': 'success', 'message': 'Cancel request received.'})
    except Exception as e:
        logger.error(f"Error processing cancel request: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def _normalize_url(url):
    """Normaliza la URL para asegurar que las URLs de YouTube Music se conviertan a formato de YouTube estándar si son listas de reproducción."""
    if "music.youtube.com" in url:
        match = re.search(r'list=([\w-]+)', url)
        if match:
            return f"https://www.youtube.com/playlist?list={match.group(1)}"
    return url

def _configure_ydl_options(quality='320', output_format='mp3'):
    def embed_thumbnail_hook(d):
        if d['status'] == 'finished':
            info = d.get('info_dict', {})
            filepath = info.get('filepath')
            thumbnail_url = info.get('thumbnail')

            # Nos aseguramos de procesar solo MP3 y si hay thumbnail URL
            if not filepath or not filepath.lower().endswith('.mp3'):
                logger.warning("embed_thumbnail_hook: no es MP3 o no hay ruta")
                return
            if not thumbnail_url:
                logger.warning("embed_thumbnail_hook: no se encontró thumbnail URL")
                return

            try:
                import requests
                # 1) Descargar .webp
                thumb_webp = filepath + '.thumb.webp'
                logger.info(f"Descargando thumbnail WebP: {thumbnail_url} → {thumb_webp}")
                resp = requests.get(thumbnail_url, stream=True, timeout=10)
                resp.raise_for_status()
                with open(thumb_webp, 'wb') as f:
                    for chunk in resp.iter_content(1024):
                        f.write(chunk)

                # 2) Convertir a JPG
                thumb_jpg = filepath + '.thumb.jpg'
                cmd_conv = [
                    'ffmpeg', '-y',
                    '-i', thumb_webp,
                    thumb_jpg
                ]
                logger.info(f"Convertir WebP→JPG: {' '.join(cmd_conv)}")
                subprocess.run(cmd_conv, check=True, capture_output=True, text=True)

                # 3) Incrustar miniatura JPG en MP3
                # —————— NUEVO: borrar cualquier .webp residual ——————
                import glob
                base = os.path.splitext(filepath)[0]
                for f in glob.glob(f"{base}.webp"):
                    try: os.remove(f)
                    except: pass
                # ————————————————————————————————————————————————
                
                artist = info.get('artist', '')
                album  = info.get('album', '')
                success = embed_thumbnail_manually(filepath, thumb_jpg, artist, album)
                if success:
                    logger.info("Miniatura incrustada correctamente")
                    # Limpiar archivos temporales
                    os.remove(thumb_webp)
                    os.remove(thumb_jpg)
                else:
                    logger.error("Falló la incrustación de la miniatura JPG")

            except Exception as e:
                logger.error(f"embed_thumbnail_hook error: {e}")

    ydl_opts = {
        'format': 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], '%(title)s.%(ext)s'),
        'progress_hooks': [progress_hook],
        'ffmpeg_location': FFMPEG_PATH,
        'ignoreerrors': True,
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'writethumbnail': False,  # No descargar la miniatura automáticamente
        'keepvideo': False,      # No mantener el archivo de video
        'logger': logger,
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': output_format,
                'preferredquality': quality,
            }
        ]
    }
    
    # Para formatos sin pérdida, ajustar calidad
    if output_format in ['flac', 'wav']:
        ydl_opts['postprocessors'][0]['preferredquality'] = '0'
    
    ydl_opts['postprocessor_hooks'] = [embed_thumbnail_hook]
    
    return ydl_opts

def _get_total_songs(download_url):
    with yt_dlp.YoutubeDL({'quiet': True, 'ignoreerrors': True}) as ydl:
        info = ydl.extract_info(download_url, download=False)
        if info and 'entries' in info:
            valid_entries = [e for e in info.get('entries', []) if e]
            return len(valid_entries)
        else:
            return 1

def _configure_playlist_items(ydl_opts, selected_songs):
    if selected_songs and isinstance(selected_songs, list):
        ydl_opts['playlist_items'] = ",".join(str(i+1) for i in selected_songs)
        with progress_data['lock']:
            progress_data['total_songs'] = len(selected_songs)
    else:
        ydl_opts['playlist'] = True

if __name__ == '__main__':
    os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)

    # Crear archivo de configuración si no existe
    if not os.path.exists('config.ini'):
        config['General']['download_folder'] = 'downloads'
        config['FFmpeg']['ffmpeg_path'] = r'C:\ffmpeg\ffmpeg-7.0.2-full_build\bin'
        with open('config.ini', 'w') as configfile:
            config.write(configfile)
    
    if not _check_ffmpeg_path():
        logger.error("La aplicación no se iniciará debido a que FFmpeg no está configurado correctamente.")
    else:
        app.run(debug=True, threaded=True, port=5001)
