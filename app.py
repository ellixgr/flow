from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import os
from uuid import uuid4
from dotenv import load_dotenv
import time
from collections import defaultdict

load_dotenv(override=True)
app = Flask(__name__)

# ✅ Anti-Flood
limite_requisitos = defaultdict(list)
LIMITE_POR_IP = 4
JANELA_TEMPO = 60

@app.before_request
def verificar_anti_flood():
    rota = request.path
    if rota == "/enviar-grupo":
        ip = request.remote_addr
        agora = time.time()
        limite_requisitos[ip] = [t for t in limite_requisitos[ip] if agora - t < JANELA_TEMPO]
        if len(limite_requisitos[ip]) >= LIMITE_POR_IP:
            return jsonify({"erro": "⚠️ Muitas requisições! Aguarde 1 minuto antes de enviar novamente."}), 429
        limite_requisitos[ip].append(agora)

# ✅ CORS — GitHub + 2 servidores Render
CORS(app, resources={r"/*": {
    "origins": [
        "https://ellixgr.github.io",
        "https://ellixgr.github.io/flow",
        "https://flow-81mj.onrender.com",
        "https://flow-mohn.onrender.com"
    ],
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type", "X-Usuario-ID", "X-Chave-Adm"],
    "supports_credentials": True
}})

# 🔑 VARIÁVEIS DO RENDER — NADA EXPOSTO!
MONGO_URI = os.getenv("MONGO_URI")
CHAVE_ADM = os.getenv("CHAVE_ADM")  # ✅ NOME CORRETO DO RENDER
CODIGO_VIP_SECRETO = os.getenv("CODIGO_VIP")

if not MONGO_URI:
    print("⚠️ AVISO: MONGO_URI não configurada!")
if not CHAVE_ADM:
    print("⚠️ AVISO: CHAVE_ADM não configurada no Render!")

TEMPO_IMPULSIONAR = timedelta(hours=2)

# 🗄️ CONEXÃO BANCO
try:
    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=10000,
        connectTimeoutMS=20000,
        socketTimeoutMS=45000,
        retryWrites=True,
        retryReads=True
    )
    db = client["flow_db"]
    grupos_col = db["grupos"]
    denuncias_col = db["denuncias"]
    cliques_col = db["cliques"]

    cliques_col.create_index("chave", unique=True, name="idx_chave_unica",
                             partialFilterExpression={"chave": {"$exists": True}})
except Exception as e:
    print(f"⚠️ ERRO CONEXÃO BANCO: {e}")

def verificar_chave_adm():
    recebida = (request.headers.get("X-Chave-Adm") or "").strip()
    return bool(CHAVE_ADM and recebida == CHAVE_ADM)

# 📄 ROTAS PÚBLICAS
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/grupos-dados")
def grupos_dados():
    try:
        cat = request.args.get("categoria", "Todos")
        filtro = {"ativo": True}
        if cat != "Todos":
            filtro["categoria"] = cat

        grupos = list(grupos_col.find(filtro).sort([
            ("ultimo_impulso", -1), ("vip", -1), ("criado_em", -1)
        ]))
        agora = datetime.utcnow()
        uid = request.headers.get("X-Usuario-ID", "").strip()[:64]

        for g in grupos:
            g["_id"] = str(g["_id"])
            dono_grupo = g.get("usuario_id", "")
            g["cliques"] = g.get("cliques", 0)

            if g.get("vip_ate") and agora < g["vip_ate"]:
                g["vip_ativo"] = True
                if dono_grupo and uid and dono_grupo == uid:
                    g["vip_restante_segundos"] = int((g["vip_ate"] - agora).total_seconds())
                else:
                    g["vip_restante_segundos"] = None
            else:
                g["vip_ativo"] = False
                g["vip_restante_segundos"] = None
                g["vip"] = False

            if dono_grupo and uid and dono_grupo == uid:
                ultimo = g.get("ultimo_impulso")
                if ultimo:
                    proximo = ultimo + TEMPO_IMPULSIONAR
                    g["pode_impulsionar"] = agora >= proximo
                    g["tempo_restante_impulso"] = int((proximo - agora).total_seconds()) if not g["pode_impulsionar"] else 0
                else:
                    g["pode_impulsionar"] = True
                    g["tempo_restante_impulso"] = 0
            else:
                g["pode_impulsionar"] = None
                g["tempo_restante_impulso"] = None

        return jsonify(grupos)
    except Exception as e:
        print("ERRO grupos-dados:", str(e))
        return jsonify({"erro": str(e)}), 500

# ✅ CONTAR CLIQUES — 1 por usuário
@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "").strip()[:64] or str(uuid4())
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    try:
        chave = f"{uid}||{grupo_id}"
        if not cliques_col.find_one({"chave": chave}):
            cliques_col.insert_one({"chave": chave, "data": datetime.utcnow()})
            grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
            return jsonify({"sucesso": True, "mensagem": "Clique contado!"})
        return jsonify({"sucesso": True, "mensagem": "Já contado antes"})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ✅ ENVIAR GRUPO — GRÁTIS, SEM PIX, JÁ APARECE!
@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    try:
        if not MONGO_URI:
            return jsonify({"erro": "❌ Banco de dados não configurado!"}), 500

        dados = request.form
        link = dados.get("link", "").strip()[:256]
        nome = dados.get("nome", "").strip()[:100]
        categoria = dados.get("categoria", "Outros")[:50]
        foto = dados.get("foto", "").strip() or "https://files.catbox.moe/0aa6f2.png"
        codigo = dados.get("codigo_adm", "").strip()[:64]
        uid = request.headers.get("X-Usuario-ID", "").strip()[:64] or str(uuid4())

        if not link or not nome:
            return jsonify({"erro": "Preencha link e nome!"}), 400
        if not link.startswith("https://chat.whatsapp.com/"):
            return jsonify({"erro": "Link só do WhatsApp!"}), 400
        if grupos_col.find_one({"link": link, "ativo": True}):
            return jsonify({"erro": "Esse grupo já está cadastrado!"}), 400

        agora = datetime.utcnow()

        # 🎁 Código VIP grátis
        if CODIGO_VIP_SECRETO and codigo == CODIGO_VIP_SECRETO:
            grupos_col.insert_one({
                "link": link, "nome": nome, "categoria": categoria, "foto": foto,
                "usuario_id": uid, "cliques": 0, "ativo": True,
                "vip": True, "vip_ate": agora + timedelta(days=1),
                "ultimo_impulso": agora, "criado_em": agora
            })
            return jsonify({"sucesso": "✅ Grupo publicado com VIP grátis!", "vip": True})

        # ✅ CADASTRO NORMAL — GRÁTIS, JÁ APARECE!
        grupos_col.insert_one({
            "link": link, "nome": nome, "categoria": categoria, "foto": foto,
            "usuario_id": uid, "cliques": 0, "ativo": True,
            "vip": False, "ultimo_impulso": agora, "criado_em": agora
        })
        return jsonify({"sucesso": "✅ Grupo publicado com sucesso! 🎉"})

    except Exception as e:
        print("ERRO envio:", str(e))
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

# ✅ MEUS GRUPOS
@app.route("/meus-grupos")
def meus_grupos():
    uid = request.headers.get("X-Usuario-ID", "").strip()[:64]
    if not uid:
        return jsonify([])
    try:
        agora = datetime.utcnow()
        grupos = list(grupos_col.find({"usuario_id": uid}).sort("ultimo_impulso", -1))
        todos = []
        for g in grupos:
            g["_id"] = str(g["_id"])
            g["cliques"] = g.get("cliques", 0)
            g["vip_ativo"] = bool(g.get("vip_ate") and agora < g["vip_ate"])
            if g["vip_ativo"]:
                g["vip_restante_segundos"] = int((g["vip_ate"] - agora).total_seconds())
            ultimo = g.get("ultimo_impulso")
            g["pode_impulsionar"] = not ultimo or agora >= ultimo + TEMPO_IMPULSIONAR
            if not g["pode_impulsionar"]:
                g["proximo_impulso_segundos"] = int((ultimo + TEMPO_IMPULSIONAR - agora).total_seconds())
            todos.append(g)
        return jsonify(todos)
    except Exception as e:
        print("Erro meus-grupos:", e)
        return jsonify([])

# ✅ IMPULSIONAR — a cada 2h
@app.route("/impulsionar/<grupo_id>", methods=["POST"])
def impulsionar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "").strip()[:64]
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": uid})
    if not grupo:
        return jsonify({"erro": "Não é dono desse grupo!"}), 403
    ultimo = grupo.get("ultimo_impulso")
    if ultimo and datetime.utcnow() - ultimo < TEMPO_IMPULSIONAR:
        t = int((ultimo + TEMPO_IMPULSIONAR - datetime.utcnow()).total_seconds())
        return jsonify({"erro": f"Aguarde {t//3600}h {(t%3600)//60}min"}), 429
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"ultimo_impulso": datetime.utcnow()}})
    return jsonify({"sucesso": True, "mensagem": "✅ Impulsionado!"})

# ✅ APAGAR GRUPO — só o dono
@app.route("/apagar-grupo/<grupo_id>", methods=["POST"])
def apagar_grupo(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "").strip()[:64]
    if not uid or not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "Dados inválidos"}), 400
    obj_id = ObjectId(grupo_id)
    res_grupo = grupos_col.delete_one({"_id": obj_id, "usuario_id": uid})
    if res_grupo.deleted_count == 0:
        return jsonify({"erro": "Você não é o dono ou grupo não existe!"}), 403
    cliques_col.delete_many({"chave": {"$regex": f"\\Q{grupo_id}\\E"}})
    denuncias_col.delete_many({"grupo_id": grupo_id})
    return jsonify({"sucesso": True, "mensagem": "✅ Grupo apagado com sucesso!"})

# ✅ DENUNCIAR
@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    dados = request.json or {}
    denuncias_col.insert_one({
        "grupo_id": grupo_id,
        "motivo": dados.get("motivo", "")[:250],
        "data": datetime.utcnow(),
        "lida": False
    })
    return jsonify({"sucesso": True})

# 🔐 PAINEL ADM — VERIFICAR CHAVE DO RENDER!
@app.route("/adm/login", methods=["POST"])
def adm_login():
    dados = request.json or {}
    chave_digitada = (dados.get("chave_adm", "") or "").strip()
    if CHAVE_ADM and chave_digitada == CHAVE_ADM:
        return jsonify({"sucesso": True, "mensagem": "✅ Acesso liberado!"})
    return jsonify({"erro": "❌ CHAVE ERRADA!"}), 403

@app.route("/adm/grupos")
def adm_grupos():
    if not verificar_chave_adm():
        return jsonify({"erro": "❌ CHAVE ERRADA!"}), 403
    todos = list(grupos_col.find().sort("criado_em", -1))
    for g in todos:
        g["_id"] = str(g["_id"])
        g["cliques"] = g.get("cliques", 0)
    return jsonify(todos)

@app.route("/adm/cadastrar-grupo", methods=["POST"])
def adm_cadastrar_grupo():
    if not verificar_chave_adm():
        return jsonify({"erro": "❌ CHAVE ERRADA!"}), 403
    try:
        dados = request.json or {}
        link = dados.get("link", "").strip()[:256]
        nome = dados.get("nome", "").strip()[:100]
        categoria = dados.get("categoria", "Outros")[:50]
        foto = dados.get("foto", "").strip() or "https://files.catbox.moe/0aa6f2.png"

        if not link or not nome:
            return jsonify({"erro": "Preencha link e nome!"}), 400
        if not link.startswith("https://chat.whatsapp.com/"):
            return jsonify({"erro": "Link só do WhatsApp!"}), 400
        if grupos_col.find_one({"link": link, "ativo": True}):
            return jsonify({"erro": "Esse grupo já está cadastrado!"}), 400

        grupos_col.insert_one({
            "link": link, "nome": nome, "categoria": categoria, "foto": foto,
            "usuario_id": "ADM", "cliques": 0, "ativo": True,
            "vip": False, "ultimo_impulso": datetime.utcnow(), "criado_em": datetime.utcnow()
        })
        return jsonify({"sucesso": "✅ Grupo cadastrado com sucesso!"})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route("/adm/apagar-grupo/<grupo_id>", methods=["POST"])
def adm_apagar_grupo(grupo_id):
    if not verificar_chave_adm():
        return jsonify({"erro": "❌ CHAVE ERRADA!"}), 403
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    obj_id = ObjectId(grupo_id)
    grupos_col.delete_one({"_id": obj_id})
    denuncias_col.delete_many({"grupo_id": grupo_id})
    cliques_col.delete_many({"chave": {"$regex": f"\\Q{grupo_id}\\E"}})
    return jsonify({"sucesso": True, "mensagem": "✅ Grupo APAGADO completamente!"})

@app.route("/adm/denuncias")
def adm_denuncias():
    if not verificar_chave_adm():
        return jsonify({"erro": "❌ CHAVE ERRADA!"}), 403
    den = list(denuncias_col.find({"lida": False}).sort("data", -1))
    res = []
    for d in den:
        try:
            obj_grupo_id = ObjectId(d["grupo_id"])
            g = grupos_col.find_one({"_id": obj_grupo_id})
            if not g:
                denuncias_col.delete_one({"_id": d["_id"]})
                continue
            res.append({
                "_id": str(d["_id"]),
                "grupo_id": str(d["grupo_id"]),
                "grupo_nome": g.get("nome", "Apagado"),
                "grupo_link": g.get("link", ""),
                "grupo_foto": g.get("foto", ""),
                "motivo": d.get("motivo", ""),
                "data": d.get("data")
            })
        except:
            continue
    return jsonify(res)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
