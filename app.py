import json
import mimetypes
import os
import re
import traceback
import sqlite3
import secrets
from hashlib import pbkdf2_hmac
from hmac import compare_digest
import urllib.request
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from ytmusicapi import YTMusic

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PORT = int(os.environ.get("PORT", "8000"))
DB = ROOT / "opentune.db"
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
HF_MODEL = os.environ.get("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct").strip()

MAX_BODY_BYTES = 64 * 1024
MAX_USERNAME_LENGTH = 32
MIN_PASSWORD_LENGTH = 4
MAX_PASSWORD_LENGTH = 256
MAX_PLAYLIST_NAME_LENGTH = 80
MAX_MEDIA_ID_LENGTH = 128
MAX_MEDIA_TEXT_LENGTH = 500
MAX_THUMBNAIL_LENGTH = 2048


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=10000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      recovery_hash TEXT NOT NULL,
      recovery_salt TEXT NOT NULL,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS sessions (
      token TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      video_id TEXT NOT NULL,
      title TEXT,
      artist TEXT,
      thumbnail TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS likes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      video_id TEXT NOT NULL,
      title TEXT,
      artist TEXT,
      thumbnail TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(user_id, video_id)
    );
    CREATE TABLE IF NOT EXISTS playlists (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(user_id, name),
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS playlist_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      playlist_id INTEGER NOT NULL,
      video_id TEXT NOT NULL,
      title TEXT,
      artist TEXT,
      thumbnail TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(playlist_id, video_id),
      FOREIGN KEY(playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
    );
    """)
    c.commit(); c.close()


def hash_password(value, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = pbkdf2_hmac("sha256", value.encode(), salt.encode(), 180000).hex()
    return digest, salt


def check_password(value, digest, salt):
    candidate = hash_password(value, salt)[0]
    return compare_digest(candidate, digest)


def validate_username(username):
    if not isinstance(username, str):
        return False
    if not 2 <= len(username) <= MAX_USERNAME_LENGTH:
        return False
    return all(ch.isalnum() or ch in "_-" for ch in username)


def validate_password(password):
    return isinstance(password, str) and MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH


def validate_playlist_name(name):
    if not isinstance(name, str):
        raise ValueError("Playlist name must be a string")
    name = name.strip()
    if not name:
        raise ValueError("Playlist name is required")
    if len(name) > MAX_PLAYLIST_NAME_LENGTH:
        raise ValueError("Playlist name is too long")
    return name


def normalize_playlist_item(data):
    video_id = data.get("videoId")
    if not isinstance(video_id, str):
        raise ValueError("videoId must be a string")
    video_id = video_id.strip()
    if not video_id:
        raise ValueError("videoId is required")
    if len(video_id) > MAX_MEDIA_ID_LENGTH:
        raise ValueError("videoId is too long")

    def optional_text(name, max_length):
        value = data.get(name)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        if len(value) > max_length:
            raise ValueError(f"{name} is too long")
        return value

    return (
        video_id,
        optional_text("title", MAX_MEDIA_TEXT_LENGTH),
        optional_text("artist", MAX_MEDIA_TEXT_LENGTH),
        optional_text("thumbnail", MAX_THUMBNAIL_LENGTH),
    )


def _owned_playlist(connection, user_id, playlist_id):
    row = connection.execute(
        "SELECT * FROM playlists WHERE id=? AND user_id=?",
        (playlist_id, user_id),
    ).fetchone()
    if not row:
        raise LookupError("Playlist not found")
    return row


def create_playlist(user_id, name):
    name = validate_playlist_name(name)
    connection = db()
    try:
        cursor = connection.execute(
            "INSERT INTO playlists(user_id,name) VALUES(?,?)",
            (user_id, name),
        )
        connection.commit()
        return dict(
            connection.execute(
                "SELECT * FROM playlists WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("A playlist with that name already exists") from exc
    finally:
        connection.close()


def list_playlists(user_id):
    connection = db()
    try:
        rows = connection.execute(
            """
            SELECT p.id,p.name,p.created_at,COUNT(i.id) AS item_count
            FROM playlists p
            LEFT JOIN playlist_items i ON i.playlist_id=p.id
            WHERE p.user_id=?
            GROUP BY p.id
            ORDER BY p.id DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_playlist(user_id, playlist_id):
    connection = db()
    try:
        playlist = dict(_owned_playlist(connection, user_id, playlist_id))
        items = [
            dict(row)
            for row in connection.execute(
                """
                SELECT id,video_id,title,artist,thumbnail,created_at
                FROM playlist_items
                WHERE playlist_id=?
                ORDER BY id DESC
                """,
                (playlist_id,),
            )
        ]
        playlist["items"] = items
        playlist["item_count"] = len(items)
        return playlist
    finally:
        connection.close()


def add_playlist_item(user_id, playlist_id, data):
    video_id, title, artist, thumbnail = normalize_playlist_item(data)
    connection = db()
    try:
        _owned_playlist(connection, user_id, playlist_id)
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO playlist_items(
              playlist_id,video_id,title,artist,thumbnail
            ) VALUES(?,?,?,?,?)
            """,
            (playlist_id, video_id, title, artist, thumbnail),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def remove_playlist_item(user_id, playlist_id, video_id):
    connection = db()
    try:
        _owned_playlist(connection, user_id, playlist_id)
        cursor = connection.execute(
            "DELETE FROM playlist_items WHERE playlist_id=? AND video_id=?",
            (playlist_id, video_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def delete_playlist(user_id, playlist_id):
    connection = db()
    try:
        _owned_playlist(connection, user_id, playlist_id)
        connection.execute(
            "DELETE FROM playlists WHERE id=? AND user_id=?",
            (playlist_id, user_id),
        )
        connection.commit()
    finally:
        connection.close()


def user_from_token(token):
    if not token: return None
    c = db(); row = c.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=?", (token,)).fetchone(); c.close()
    return row


def body(handler):
    try:
        n = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise ValueError("Invalid Content-Length")
    if n > MAX_BODY_BYTES:
        raise ValueError("Request body is too large")
    raw = handler.rfile.read(n) if n else b"{}"
    try:
        parsed = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Request body must be a JSON object")
    return parsed


def send_json(handler, payload, status=200):
    raw = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers(); handler.wfile.write(raw)


def search_music(query):
    ytm = YTMusic()
    rows = ytm.search(query, filter="songs", limit=25)
    result=[]
    for x in rows:
        vid=x.get("videoId")
        if not vid: continue
        artists=x.get("artists") or []
        result.append({"videoId":vid,"title":x.get("title") or "Unknown","artist":", ".join(a.get("name","") for a in artists),"duration":x.get("duration",""),"thumbnail":(x.get("thumbnails") or [{}])[-1].get("url","")})
    return result


def main():
    init_db()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print("[%s] %s" % (self.log_date_time_string(), fmt % args))

        def do_GET(self):
            try:
                p=urlparse(self.path); q=parse_qs(p.query)
                if p.path=="/api/health": return send_json(self,{"ok":True})
                if p.path=="/api/search":
                    query=(q.get("q") or [""])[0].strip()
                    if not query: return send_json(self,{"results":[]})
                    if len(query) > 200: return send_json(self,{"error":"Search query is too long."},400)
                    return send_json(self,{"results":search_music(query)})
                if p.path=="/api/auth/me":
                    u=user_from_token(self.headers.get("Authorization","").removeprefix("Bearer "))
                    return send_json(self,{"user":dict(u) if u else None})
                if p.path=="/api/history":
                    u=user_from_token(self.headers.get("Authorization","").removeprefix("Bearer "))
                    if not u: return send_json(self,{"history":[]})
                    c=db(); rows=[dict(r) for r in c.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT 100",(u["id"],))]; c.close(); return send_json(self,{"history":rows})
                if p.path=="/api/likes":
                    u=user_from_token(self.headers.get("Authorization","").removeprefix("Bearer "))
                    if not u: return send_json(self,{"likes":[]})
                    c=db(); rows=[dict(r) for r in c.execute("SELECT * FROM likes WHERE user_id=? ORDER BY id DESC",(u["id"],))]; c.close(); return send_json(self,{"likes":rows})
                if p.path=="/api/playlists":
                    u=user_from_token(self.headers.get("Authorization","").removeprefix("Bearer "))
                    if not u: return send_json(self,{"error":"Login required"},401)
                    return send_json(self,{"playlists":list_playlists(u["id"])})
                playlist_match=re.fullmatch(r"/api/playlists/(\d+)",p.path)
                if playlist_match:
                    u=user_from_token(self.headers.get("Authorization","").removeprefix("Bearer "))
                    if not u: return send_json(self,{"error":"Login required"},401)
                    try:
                        playlist=get_playlist(u["id"],int(playlist_match.group(1)))
                    except LookupError:
                        return send_json(self,{"error":"Playlist not found"},404)
                    return send_json(self,{"playlist":playlist})
                file=(STATIC / ("index.html" if p.path=="/" else p.path.lstrip("/"))).resolve()
                if STATIC not in file.parents and file!=STATIC: return send_json(self,{"error":"not found"},404)
                if not file.exists() or not file.is_file(): return send_json(self,{"error":"not found"},404)
                data=file.read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(file.name)[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
            except ValueError as e:
                send_json(self,{"error":str(e)},400)
            except Exception as e:
                traceback.print_exc(); send_json(self,{"error":"Internal server error"},500)

        def do_POST(self):
            try:
                p=urlparse(self.path); data=body(self)
                if p.path=="/api/auth/register":
                    username=str(data.get("username","")).strip(); password=str(data.get("password","")); recovery=str(data.get("recovery",""))
                    if not validate_username(username) or not validate_password(password) or not recovery.strip():
                        return send_json(self,{"error":"Use a valid username, password and recovery answer."},400)
                    ph,ps=hash_password(password); rh,rs=hash_password(recovery.lower())
                    c=db()
                    try: c.execute("INSERT INTO users(username,password_hash,recovery_hash,recovery_salt) VALUES(?,?,?,?)",(username,ph+":"+ps,rh,rs)); c.commit()
                    except sqlite3.IntegrityError: c.close(); return send_json(self,{"error":"Username already exists."},409)
                    uid=c.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()[0]; token=secrets.token_urlsafe(32); c.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)",(token,uid)); c.commit(); c.close(); return send_json(self,{"token":token,"username":username})
                if p.path=="/api/auth/login":
                    username=str(data.get("username","")).strip(); password=str(data.get("password",""));
                    if not validate_username(username) or not validate_password(password): return send_json(self,{"error":"Invalid username or password."},401)
                    c=db(); u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone(); c.close()
                    if not u: return send_json(self,{"error":"Invalid username or password."},401)
                    digest,salt=u["password_hash"].split(":",1)
                    if not check_password(password,digest,salt): return send_json(self,{"error":"Invalid username or password."},401)
                    token=secrets.token_urlsafe(32); c=db(); c.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)",(token,u["id"])); c.commit(); c.close(); return send_json(self,{"token":token,"username":username})
                if p.path=="/api/auth/reset":
                    username=str(data.get("username","")).strip(); recovery=str(data.get("recovery","")).lower(); newpw=str(data.get("password",""));
                    if not validate_username(username) or not validate_password(newpw) or not recovery.strip(): return send_json(self,{"error":"Invalid password reset details."},400)
                    c=db(); u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
                    if not u: c.close(); return send_json(self,{"error":"Account not found."},404)
                    if not check_password(recovery,u["recovery_hash"],u["recovery_salt"]): c.close(); return send_json(self,{"error":"Recovery answer is incorrect."},401)
                    ph,ps=hash_password(newpw); c.execute("UPDATE users SET password_hash=? WHERE id=?",(ph+":"+ps,u["id"])); c.commit(); c.close(); return send_json(self,{"ok":True})
                if p.path=="/api/auth/logout":
                    token=self.headers.get("Authorization","").removeprefix("Bearer "); c=db(); c.execute("DELETE FROM sessions WHERE token=?",(token,)); c.commit(); c.close(); return send_json(self,{"ok":True})
                token=self.headers.get("Authorization","").removeprefix("Bearer "); u=user_from_token(token)
                if p.path=="/api/history":
                    if not u: return send_json(self,{"error":"Login required"},401)
                    video_id=str(data.get("videoId","")).strip()
                    if not video_id: return send_json(self,{"error":"videoId is required"},400)
                    c=db(); c.execute("INSERT INTO history(user_id,video_id,title,artist,thumbnail) VALUES(?,?,?,?,?)",(u["id"],video_id,data.get("title"),data.get("artist"),data.get("thumbnail"))); c.commit(); c.close(); return send_json(self,{"ok":True})
                if p.path=="/api/likes":
                    if not u: return send_json(self,{"error":"Login required"},401)
                    video_id=str(data.get("videoId","")).strip()
                    if not video_id: return send_json(self,{"error":"videoId is required"},400)
                    c=db(); c.execute("INSERT OR IGNORE INTO likes(user_id,video_id,title,artist,thumbnail) VALUES(?,?,?,?,?)",(u["id"],video_id,data.get("title"),data.get("artist"),data.get("thumbnail"))); c.commit(); c.close(); return send_json(self,{"ok":True})
                if p.path=="/api/playlists":
                    if not u: return send_json(self,{"error":"Login required"},401)
                    playlist=create_playlist(u["id"],data.get("name"))
                    return send_json(self,{"playlist":playlist},201)
                playlist_items_match=re.fullmatch(r"/api/playlists/(\d+)/items",p.path)
                if playlist_items_match:
                    if not u: return send_json(self,{"error":"Login required"},401)
                    try:
                        added=add_playlist_item(u["id"],int(playlist_items_match.group(1)),data)
                    except LookupError:
                        return send_json(self,{"error":"Playlist not found"},404)
                    return send_json(self,{"ok":True,"added":added})
                send_json(self,{"error":"not found"},404)
            except ValueError as e:
                send_json(self,{"error":str(e)},400)
            except Exception as e:
                traceback.print_exc(); send_json(self,{"error":"Internal server error"},500)

        def do_DELETE(self):
            try:
                p=urlparse(self.path)
                token=self.headers.get("Authorization","").removeprefix("Bearer ")
                u=user_from_token(token)
                if not u:
                    return send_json(self,{"error":"Login required"},401)

                playlist_match=re.fullmatch(r"/api/playlists/(\d+)",p.path)
                if playlist_match:
                    try:
                        delete_playlist(u["id"],int(playlist_match.group(1)))
                    except LookupError:
                        return send_json(self,{"error":"Playlist not found"},404)
                    return send_json(self,{"ok":True})

                item_match=re.fullmatch(r"/api/playlists/(\d+)/items/([^/]+)",p.path)
                if item_match:
                    try:
                        removed=remove_playlist_item(
                            u["id"],
                            int(item_match.group(1)),
                            unquote(item_match.group(2)),
                        )
                    except LookupError:
                        return send_json(self,{"error":"Playlist not found"},404)
                    return send_json(self,{"ok":True,"removed":removed})

                send_json(self,{"error":"not found"},404)
            except ValueError as e:
                send_json(self,{"error":str(e)},400)
            except Exception:
                traceback.print_exc(); send_json(self,{"error":"Internal server error"},500)

    server=ThreadingHTTPServer(("0.0.0.0",PORT),Handler)
    print(f"OpenTune -> http://localhost:{PORT}")
    print("Catalog -> ytmusicapi (unauthenticated YouTube Music public search)")
    server.serve_forever()

if __name__=="__main__": main()
