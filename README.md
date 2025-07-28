# spotify_playlist_importer

📦 Утилита для автоматической загрузки треков из файла в новый плейлист Spotify.

## ⚙️ Установка

1. Клонируй проект:
   git clone https://github.com/yourusername/spotify_playlist_importer.git
   cd spotify_playlist_importer

2. Установи зависимости:
   pip install -r requirements.txt

3. Создай .env на основе .env.example:
   SPOTIFY_CLIENT_ID="..."
   SPOTIFY_CLIENT_SECRET="..."
   SPOTIFY_REDIRECT_URI="http://127.0.0.1:8888/callback"
   SPOTIFY_USERNAME="..."

📄 tracks.txt
Каждая строка должна содержать название песни и исполнителя, например:

Clavaito (Bachata Version) - Chanel, Abraham Mateo
No Me Toca - Pinto Picasso, sP Polanco

🚀 Запуск
python main.py
python3 main.py
