import os
import time
import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth
from tqdm import tqdm

# Загружаем переменные из .env
load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
SCOPE = "playlist-modify-public playlist-modify-private"

sp = spotipy.Spotify(
    auth_manager=SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SCOPE,
    )
)


def load_tracks_from_file(filename):
    with open(filename, "r", encoding="utf-8") as f:
        # Удаляем дубли строк
        lines = list(dict.fromkeys([line.strip() for line in f if line.strip()]))
    return lines


def search_track_on_spotify(track_name):
    results = sp.search(q=track_name, type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    if items:
        return items[0]["uri"]
    return None


def create_playlist(user_id, name, description="Imported from file"):
    playlist = sp.user_playlist_create(
        user=user_id, name=name, public=False, description=description
    )
    return playlist["id"]


def main():
    print("📥 Загрузка треков из файла...")
    track_lines = load_tracks_from_file("tracks.txt")
    total = len(track_lines)
    print(f"🔍 Уникальных треков для импорта: {total}")

    print("🎧 Поиск треков в Spotify...")
    found_uris = set()
    not_found = []

    for line in tqdm(track_lines, desc="Поиск", unit="трек"):
        uri = search_track_on_spotify(line)
        if uri:
            found_uris.add(uri)
        else:
            not_found.append(line)
        time.sleep(0.2)  # анти-спам

    print(f"\n✅ Найдено: {len(found_uris)} / {total} треков")
    if not_found:
        print("⚠️ Не найдены треки:")
        for nf in not_found:
            print(f" - {nf}")

    user_id = sp.current_user()["id"]
    playlist_name = input("📛 Название нового плейлиста в Spotify: ").strip()
    playlist_id = create_playlist(user_id, playlist_name)

    print("🚀 Загружаем треки в плейлист...")
    BATCH_SIZE = 100
    uris_list = list(found_uris)
    for i in tqdm(
        range(0, len(uris_list), BATCH_SIZE), desc="Добавление", unit="пакет"
    ):
        batch = uris_list[i : i + BATCH_SIZE]
        sp.playlist_add_items(playlist_id, batch)
        time.sleep(0.1)

    print("\n🎉 Готово! Плейлист создан и загружен.")
    print(f"📁 Всего добавлено уникальных треков: {len(uris_list)} из {total} строк.")


if __name__ == "__main__":
    main()
