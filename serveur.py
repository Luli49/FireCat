"""
Serveur "navigateur Scratch" - scratchattach
=============================================
Ce script attend des requêtes depuis un projet TurboWarp (via cloud variables)
et renvoie le HTML et le CSS d'une page web demandée.

Option 1 : pas d'exécution JavaScript, juste le HTML/CSS brut nettoyé
(scripts retirés, images <img> retirées, SVG et texte conservés).

Crédit : ce script utilise la librairie scratchattach de TimMcCool
(https://github.com/TimMcCool/scratchattach) - pensez à le créditer
dans la description de votre projet Scratch, comme demandé par la lib.
"""

import os
import time
import threading
from urllib.parse import urljoin
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from bs4 import BeautifulSoup
import scratchattach as scratch3

# ----------------------------------------------------------------------
# CONFIGURATION - à adapter
# ----------------------------------------------------------------------

PROJECT_ID = "REMPLACEZ_PAR_VOTRE_ID"   # l'ID numérique de votre projet Scratch
PURPOSE = "Serveur navigateur Scratch"   # décrit l'usage du bot (évite d'être bloqué par TurboWarp)
CONTACT = "REMPLACEZ_PAR_VOTRE_PSEUDO_SCRATCH"  # votre pseudo Scratch ou un autre contact

MAX_LENGTH = 150_000   # taille max renvoyée par requête, pour éviter un transfert trop long
REQUEST_TIMEOUT = 8    # secondes, timeout des requêtes HTTP vers les sites visités
CACHE_TTL = 10          # secondes, durée de vie du cache (évite de télécharger 2x la même page)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ScratchBrowserBot/1.0)"
}

# Balises qu'on retire entièrement du HTML (JS, médias non supportés, etc.)
TAGS_TO_REMOVE = ["script", "noscript", "iframe", "video", "audio", "object", "embed"]

# ----------------------------------------------------------------------
# CACHE SIMPLE (évite de refaire la requête HTTP pour get_html ET get_css)
# ----------------------------------------------------------------------

_cache = {}  # url -> (timestamp, BeautifulSoup, base_url)


def normalize_url(url):
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


def fetch_page(url):
    url = normalize_url(url)
    now = time.time()

    cached = _cache.get(url)
    if cached and (now - cached[0]) < CACHE_TTL:
        return cached[1], cached[2]

    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    _cache[url] = (now, soup, url)

    # Petit nettoyage du cache pour ne pas accumuler indéfiniment
    if len(_cache) > 50:
        oldest_url = min(_cache, key=lambda u: _cache[u][0])
        _cache.pop(oldest_url, None)

    return soup, url


# ----------------------------------------------------------------------
# NETTOYAGE HTML / EXTRACTION CSS
# ----------------------------------------------------------------------

def clean_html(soup):
    soup = BeautifulSoup(str(soup), "html.parser")  # copie pour ne pas abîmer le cache

    for tag in soup.find_all(TAGS_TO_REMOVE):
        tag.decompose()

    # On retire les images bitmap (png/jpg/gif/webp...) mais on garde les <svg> inline
    for img in soup.find_all("img"):
        img.decompose()

    body = soup.body if soup.body else soup
    html = str(body)

    if len(html) > MAX_LENGTH:
        html = html[:MAX_LENGTH] + "\n<!-- ... contenu tronqué (page trop longue) ... -->"

    return html


def extract_css(soup, base_url):
    parts = []

    # CSS inline dans des balises <style>
    for style in soup.find_all("style"):
        parts.append(style.get_text())

    # Feuilles de style liées (<link rel="stylesheet">)
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href")
        if not href:
            continue
        css_url = urljoin(base_url, href)
        try:
            r = requests.get(css_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            if r.status_code == 200:
                parts.append(r.text)
        except requests.RequestException:
            pass  # on ignore les feuilles de style qui échouent

    css = "\n".join(parts)

    if len(css) > MAX_LENGTH:
        css = css[:MAX_LENGTH] + "\n/* ... CSS tronqué (trop long) ... */"

    return css


# ----------------------------------------------------------------------
# MINI SERVEUR WEB DE "KEEP-ALIVE" (nécessaire pour Render.com)
# ----------------------------------------------------------------------
# Render endort les services gratuits après 15 min sans requête HTTP entrante.
# Ce mini serveur répond juste "OK" : un pingeur externe (cron-job.org,
# UptimeRobot...) l'appellera toutes les 10 minutes pour empêcher l'endormissement.
# Inutile en local ou sur une VM classique : vous pouvez l'ignorer dans ce cas.

class _KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - serveur navigateur Scratch actif")

    def log_message(self, format, *args):
        pass  # on évite de spammer les logs avec chaque ping


def start_keepalive_server():
    port = int(os.environ.get("PORT", 10000))  # Render fournit la variable PORT
    server = HTTPServer(("0.0.0.0", port), _KeepAliveHandler)
    print(f"Mini serveur keep-alive en écoute sur le port {port}")
    server.serve_forever()


# ----------------------------------------------------------------------
# CONNEXION SCRATCHATTACH
# ----------------------------------------------------------------------

conn = scratch3.get_tw_cloud(PROJECT_ID, purpose=PURPOSE, contact=CONTACT)
client = scratch3.CloudRequests(conn)


@client.request
def get_html(url):
    try:
        soup, base_url = fetch_page(url)
        return clean_html(soup)
    except requests.RequestException as e:
        return f"ERREUR: impossible de charger la page ({e})"
    except Exception as e:
        return f"ERREUR: {e}"


@client.request
def get_css(url):
    try:
        soup, base_url = fetch_page(url)
        return extract_css(soup, base_url)
    except requests.RequestException as e:
        return f"ERREUR CSS: impossible de charger la page ({e})"
    except Exception as e:
        return f"ERREUR CSS: {e}"


@client.event
def on_ready():
    print("Serveur prêt, en attente de requêtes depuis Scratch...")


if __name__ == "__main__":
    # Le mini serveur web tourne dans un thread séparé pour ne pas bloquer
    # la connexion cloud (utile seulement sur Render ; inoffensif ailleurs).
    threading.Thread(target=start_keepalive_server, daemon=True).start()
    client.run()
