from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
import mercadopago
from datetime import datetime, timedelta, UTC
import os

app = Flask(__name__)

# ✅ LIBERA ACESSO DO GITHUB PAGES — CORRIGIDO
CORS(app, resources={r"/*": {
    "origins": [
        "https://ellixgr.github.io",
        "https://ellixgr.github.io/flow",
        "https://ellixgr.github.io/flow/"
    ]
}})

# ==============================================
# 🔑 VARIÁVEIS DO RENDER
# ==============================================
MONGO_URI = os.getenv("MONGO_URI")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
CHAVE_ADM = os.getenv("CHAVE_ADM", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

if not MONGO_URI: raise Exception("❌ MONGO_URI NÃO CONFIGURADA!")
if not MP_ACCESS_TOKEN: raise Exception("❌ MP_ACCESS_TOKEN NÃO CONFIGURADA!")
if not CHAVE_ADM: raise Exception("❌ CHAVE_ADM NÃO CONFIGURADA!")

# ==============================================
# CONEXÃO BANCO
# ==============================================
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

try:
    client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
    db = client.flow
    grupos_col = db.grupos
    codigos_col = db.codigos_vip
    denuncias_col = db.denuncias
    print("✅ CONECTADO AO BANCO!")
except Exception as e:
    print(f"❌ ERRO BANCO: {e}")
    raise

# ==============================================
# ✅ FUNÇÕES AUXILIARES
# ==============================================
def codigo_valido(codigo):
    if not codigo: return False
    codigo = codigo.strip()
    if codigo == CHAVE_ADM or codigo == SECRET_KEY: return True
    return codigos_col.find_one({"codigo": codigo, "usado": False}) is not None

def senha_adm_valida(senha):
    if not senha: return False
    return senha.strip() == CHAVE_ADM

def marcar_codigo_usado(codigo):
    codigo = codigo.strip()
    if codigo in [CHAVE_ADM, SECRET_KEY]: return
    codigos_col.update_one({"codigo": codigo}, {"$set": {"usado": True, "usado_em": datetime.now(UTC)}})

def gerar_pix(valor, descricao):
    try:
        pix_data = {
            "transaction_amount": valor,
            "description": descricao,
            "payment_method_id": "pix",
            "payer": {"email": "pagamento@flow.com.br"}
        }
        resultado = sdk.payment().create(pix_data)
        pag = resultado["response"]
        if "point_of_interaction" in pag:
            return {"sucesso": True, "id_pagamento": pag["id"],
                    "codigo_pix": pag["point_of_interaction"]["transaction_data"]["qr_code"]}
        return {"erro": "Não foi possível gerar o PIX"}
    except Exception as e:
        return {"erro": str(e)}

# ==============================================
# ✅ SALVA GRUPO COM USUÁRIO
# ==============================================
def salvar_grupo(dados, dias_vip, usuario_id):
    expira_em = datetime.now(UTC) + timedelta(days=dias_vip)
    prox_impulso = datetime.now(UTC)
    grupo = {
        "usuario_id": usuario_id,
        "link": dados["link"],
        "nome": dados["nome"],
        "foto": dados.get("foto") or "https://files.catbox.moe/0aa6f2.png",
        "categoria": dados.get("categoria", "Amizade"),
        "vip": dias_vip > 0,
        "dias_vip": dias_vip,
        "expira_em": expira_em,
        "proximo_impulso": prox_impulso,
        "cliques": 0,
        "denuncias": 0,
        "criado_em": datetime.now(UTC),
        "ativo": True
    }
    return grupos_col.insert_one(grupo)

# ==============================================
# 🌐 ROTAS PÚBLICAS
# ==============================================
@app.route("/")
def index():
    return jsonify({"mensagem": "✅ Servidor FLOW ONLINE!"})

@app.route("/grupos-dados")
def grupos_dados():
    agora = datetime.now(UTC)
    lista = list(grupos_col.find({
        "ativo": True,
        "$or": [{"expira_em": {"$gte": agora}}, {"expira_em": {"$exists": False}}]
    }).sort([("$natural", -1)]))
    for g in lista: g["_id"] = str(g["_id"])
    return jsonify(lista)

# ==============================================
# 📤 ENVIAR GRUPO
# ==============================================
@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    link = request.form.get("link", "").strip()
    nome = request.form.get("nome", "").strip()
    categoria = request.form.get("categoria", "Amizade")
    foto = request.form.get("foto", "").strip()
    plano = request.form.get("plano", "5")
    codigo_adm = request.form.get("codigo_adm", "").strip()
    usuario_id = request.headers.get("X-Usuario-ID
