import json
import mimetypes
import os
import traceback
import sqlite3
import secrets
from hashlib import pbkdf2_hmac
from hmac import compare_digest
import urllib.request
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from ytmusicapi import YTMusic

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PORT = int(os.environ.get("PORT", "8000"))
DB = ROOT / "opentune.db"
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
HF_MODEL = os.environ.get("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct").strip()

SESSION_TTL_SECONDS = 60 * 60 * 24 * 30


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=10000")
    c.execute("PRAGMA journal_mode=WAL")
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
    """)
    cleanup_expired_sessions(c)
    c.commit(); c.close()


def cleanup_expired_sessions(connection=None):
    own_connection = connection is None
    c = connection or db()
    cutoff = time.time() - SESSION_TTL_SECONDS
    c.execute("DELETE FROM sessions WHERE strftime('%s', created_at) < ?", (int(cutoff),))
    if own_connection:
        c.commit(); c.close()


def hash_password(value, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = pbkdf2_hmac("sha256", value.encode(), salt.encode(), 180000).hex()
    return digest, salt


def check_password(value, digest, salt):
    return compare_digest(hash_password(value, salt)[0], digest)


def user_from_token(token):
    if not token: return None
    cleanup_expired_sessions()
    c = db(); row = c.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=?", (token,)).fetchone(); c.close()
    return row


def body(handler):
    n = int(handler.headers.get("Content-Length", "0"))
    return json.loads(handler.rfile.read(n) or b"{}")


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
                file=(STATIC / ("index.html" if p.path=="/" else p.path.lstrip("/"))).resolve()
                if STATIC not in file.parents and file!=STATIC: return send_json(self,{"error":"not found"},404)
                if not file.exists() or not file.is_file(): return send_json(self,{"error":"not found"},404)
                data=file.read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(file.name)[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
            except Exception as e:
                traceback.print_exc(); send_json(self,{"error":str(e)},500)

        def do_POST(self):
            try:
                p=urlparse(self.path); data=body(self)
                if p.path=="/api/auth/register":
                    username=str(data.get("username","")).strip(); password=str(data.get("password","")); recovery=str(data.get("recovery",""))
                    if len(username)<2 or len(password)<4 or not recovery: return send_json(self,{"error":"Username, password and recovery answer are required."},400)
                    ph,ps=hash_password(password); rh,rs=hash_password(recovery.lower())
                    c=db()
                    try: c.execute("INSERT INTO users(username,password_hash,recovery_hash,recovery_salt) VALUES(?,?,?,?)",(username,ph+":"+ps,rh,rs)); c.commit()
                    except sqlite3.IntegrityError: c.close(); return send_json(self,{"error":"Username already exists."},409)
                    uid=c.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()[0]; token=secrets.token_urlsafe(32); c.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)",(token,uid)); c.commit(); c.close(); return send_json(self,{"token":token,"username":username})
                if p.path=="/api/auth/login":
                    username=str(data.get("username","")).strip(); password=str(data.get("password","")); c=db(); u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone(); c.close()
                    if not u: return send_json(self,{"error":"Invalid username or password."},401)
                    digest,salt=u["password_hash"].split(":",1)
                    if not check_password(password,digest,salt): return send_json(self,{"error":"Invalid username or password."},401)
                    token=secrets.token_urlsafe(32); c=db(); c.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)",(token,u["id"])); c.commit(); c.close(); return send_json(self,{"token":token,"username":username})
                if p.path=="/api/auth/reset":
                    username=str(data.get("username","")).strip(); recovery=str(data.get("recovery","")).lower(); newpw=str(data.get("password","")); c=db(); u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
                    if not u: c.close(); return send_json(self,{"error":"Account not found."},404)
                    if not check_password(recovery,u["recovery_hash"],u["recovery_salt"]): c.close(); return send_json(self,{"error":"Recovery answer is incorrect."},401)
                    ph,ps=hash_password(newpw); c.execute("UPDATE users SET password_hash=? WHERE id=?",(ph+":"+ps,u["id"])); c.execute("DELETE FROM sessions WHERE user_id=?",(u["id"],)); c.commit(); c.close(); return send_json(self,{"ok":True})
                if p.path=="/api/auth/logout":
                    token=self.headers.get("Authorization","").removeprefix("Bearer "); c=db(); c.execute("DELETE FROM sessions WHERE token=?",(token,)); c.commit(); c.close(); return send_json(self,{"ok":True})
                token=self.headers.get("Authorization","").removeprefix("Bearer "); u=user_from_token(token)
                if p.path=="/api/history":
                    if not u: return send_json(self,{"error":"Login required"},401)
                    c=db(); c.execute("INSERT INTO history(user_id,video_id,title,artist,thumbnail) VALUES(?,?,?,?,?)",(u["id"],data.get("videoId"),data.get("title"),data.get("artist"),data.get("thumbnail"))); c.commit(); c.close(); return send_json(self,{"ok":True})
                if p.path=="/api/likes":
                    if not u: return send_json(self,{"error":"Login required"},401)
                    c=db(); c.execute("INSERT OR IGNORE INTO likes(user_id,video_id,title,artist,thumbnail) VALUES(?,?,?,?,?)",(u["id"],data.get("videoId"),data.get("title"),data.get("artist"),data.get("thumbnail"))); c.commit(); c.close(); return send_json(self,{"ok":True})
                send_json(self,{"error":"not found"},404)
            except Exception as e:
                traceback.print_exc(); send_json(self,{"error":str(e)},500)

    server=ThreadingHTTPServer(("0.0.0.0",PORT),Handler)
    print(f"OpenTune -> http://localhost:{PORT}")
    print("Catalog -> ytmusicapi (unauthenticated YouTube Music public search)")
    server.serve_forever()

if __name__=="__main__": main()
