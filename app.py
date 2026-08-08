from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
import mercadopago
from datetime import datetime, timedelta, UTC
import os

app = Flask(__name__)

# ✅ CORS LIBERADO TOTALMENTE
CORS(app)

# ✅ RESPOSTA OBRIGATÓRIA PRA NAVEGADOR
@app.before_request
def tratar_options():
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Usuario-ID"
        return resp, 200

@app.after_request
def aplicar_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

# ==============================================
# 🔑 VARIÁVEIS DO RENDER
# ==============================================
MONGO_URI = os.getenv("MONGO_URI")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
CHAVE_ADM = os.getenv("CHAVE_ADM", "").strip()

# ✅ NÃO TRAVA O APP — SÓ AVISA
if not MONGO_URI: print("⚠️ MONGO_URI vazia!")
if not MP_ACCESS_TOKEN: print("⚠️ MP_ACCESS_TOKEN vazia!")
if not CHAVE_ADM: print("⚠️ CHAVE_ADM vazia!")

# ==============================================
# BANCO DE DADOS
# ==============================================
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
db = client.flow
grupos_col = db.grupos
codigos_col = db.codigos_vip
denuncias_col = db.denuncias
print("✅ BANCO CONECTADO!")

# ==============================================
# FUNÇÕES AUXILIARES
# ==============================================
def codigo_valido(codigo):
    if not codigo: return False
    codigo = codigo.strip()
    if codigo == CHAVE_ADM: return True
    return codigos_col.find_one({"codigo": codigo, "usado": False}) is not None

def senha_adm_valida(senha):
    return bool(senha and senha.strip() == CHAVE_ADM)

# ==============================================
# ROTAS
# ==============================================
@app.route("/")
def index():
    return jsonify({"mensagem": "✅ ONLINE!", "agora": datetime.now(UTC).isoformat()})

@app.route("/grupos-dados")
def grupos_dados():
    agora = datetime.now(UTC)
    lista = list(grupos_col.find({
        "ativo": True,
        "$or": [{"expira_em": {"$gte": agora}}, {"expira_em": {"$exists": False}}]
    }).sort([("$natural", -1)]))
    for g in lista: g["_id"] = str(g["_id"])
    return jsonify(lista)

@app.route("/meus-grupos", methods=["GET"])
def meus_grupos():
    usuario_id = request.headers.get("X-Usuario-ID", "").strip()
    print(f"📤 /meus-grupos → {usuario_id}")
    if not usuario_id:
        return jsonify({"erro": "Sem identificador"}), 400
    agora = datetime.now(UTC)
    lista = list(grupos_col.find({"usuario_id": usuario_id, "ativo": True}).sort([("criado_em", -1)]))
    for g in lista:
        g["_id"] = str(g["_id"])
        eh_vip = g.get("vip", False) and g.get("expira_em", agora) >= agora
        g["vip"] = eh_vip
        prox = g.get("proximo_impulso", agora)
        g["pode_impulsionar"] = not eh_vip or prox <= agora
        g["proximo_impulso"] = prox.isoformat() if isinstance(prox, datetime) else None
    return jsonify(lista)

@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    try:
        dados = request.get_json(silent=True, force=True) or {}
        motivo = dados.get("motivo", "outro")
        outros = dados.get("outros_motivos", "").strip()
        grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"denuncias": 1}})
        denuncias_col.insert_one({
            "grupo_id": grupo_id, "motivo": motivo,
            "outros_motivos": outros, "data": datetime.now(UTC)
        })
        print(f"✅ DENÚNCIA SALVA: {grupo_id} | {motivo}")
        return jsonify({"sucesso": "✅ Denúncia enviada!"})
    except Exception as e:
        print(f"❌ ERRO DENÚNCIA: {e}")
        return jsonify({"erro": str(e)}), 500

@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    link = request.form.get("link", "").strip()
    nome = request.form.get("nome", "").strip()
    categoria = request.form.get("categoria", "Amizade")
    foto = request.form.get("foto", "").strip()
    plano = request.form.get("plano", "5")
    codigo_adm = request.form.get("codigo_adm", "").strip()
    usuario_id = request.headers.get("X-Usuario-ID", "").strip()

    if not link or not nome:
        return jsonify({"erro": "Preencha link e nome!"})
    if not link.startswith("https://chat.whatsapp.com/"):
        return jsonify({"erro": "Link inválido! Use link do WhatsApp"})

    if codigo_adm and codigo_valido(codigo_adm):
        dias = 1 if plano == "5" else 2
        expira_em = datetime.now(UTC) + timedelta(days=dias)
        grupos_col.insert_one({
            "usuario_id": usuario_id, "link": link, "nome": nome,
            "foto": foto or "https://files.catbox.moe/0aa6f2.png",
            "categoria": categoria, "vip": dias>0, "dias_vip": dias,
            "expira_em": expira_em, "proximo_impulso": datetime.now(UTC),
            "cliques": 0, "denuncias": 0, "criado_em": datetime.now(UTC), "ativo": True
        })
        codigos_col.update_one({"codigo": codigo_adm}, {"$set": {"usado": True}})
        return jsonify({"sucesso": "✅ Grupo enviado GRÁTIS!", "sem_pix": True})

    valor = 5.00 if plano == "5" else 10.00
    dias = 1 if plano == "5" else 2
    pix_data = {
        "transaction_amount": valor,
        "description": f"VIP Grupo WhatsApp — {dias} dia(s)",
        "payment_method_id": "pix",
        "payer": {"email": "pagamento@flow.com.br"}
    }
    resultado = sdk.payment().create(pix_data)
    pag = resultado.get("response", {})
    if "point_of_interaction" not in pag:
        return jsonify({"erro": "Não foi possível gerar o PIX"})
    return jsonify({
        "sucesso": "✅ PIX gerado!",
        "codigo_pix": pag["point_of_interaction"]["transaction_data"]["qr_code"],
        "dias_vip": dias, "link_grupo": link, "nome_grupo": nome, "foto_grupo": foto
    })

@app.route("/impulsionar/<grupo_id>", methods=["POST"])
def impulsionar(grupo_id):
    usuario_id = request.headers.get("X-Usuario-ID", "").strip()
    if not usuario_id:
        return jsonify({"erro": "Sem identificador"}), 400
    agora = datetime.now(UTC)
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": usuario_id})
    if not grupo:
        return jsonify({"erro": "Grupo não encontrado!"})
    prox = grupo.get("proximo_impulso", agora)
    if prox > agora:
        return jsonify({"erro": "⏳ Aguarde 24h para impulsionar de novo!"})
    expira_em = agora + timedelta(days=1)
    prox_impulso = agora + timedelta(days=1)
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {
        "$set": {"vip": True, "expira_em": expira_em, "proximo_impulso": prox_impulso}
    })
    return jsonify({"sucesso": "✅ Impulsionado! Em destaque por 24h!"})

@app.route("/apagar-meu-grupo/<grupo_id>", methods=["POST"])
def apagar_meu_grupo(grupo_id):
    usuario_id = request.headers.get("X-Usuario-ID", "").strip()
    res = grupos_col.delete_one({"_id": ObjectId(grupo_id), "usuario_id": usuario_id})
    if res.deleted_count == 0:
        return jsonify({"erro": "Não foi possível apagar!"})
    return jsonify({"sucesso": "✅ Grupo apagado!"})

@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
    return jsonify({"ok": True})

@app.route("/verificar-senha-adm", methods=["POST"])
def verificar_senha_adm():
    senha = request.form.get("senha", "").strip()
    if senha_adm_valida(senha):
        return jsonify({"sucesso": "✅ Senha correta!"})
    return jsonify({"erro": "❌ Senha incorreta! Acesso NEGADO!"}), 403

@app.route("/admin/grupos", methods=["GET"])
def admin_grupos():
    senha = request.args.get("senha", "").strip()
    if not senha_adm_valida(senha):
        return jsonify({"erro": "❌ Acesso negado!"}), 403
    lista = list(grupos_col.find({}).sort([("criado_em", -1)]))
    for g in lista: g["_id"] = str(g["_id"])
    return jsonify(lista)

@app.route("/admin/apagar-grupo/<grupo_id>", methods=["POST"])
def admin_apagar_grupo(grupo_id):
    senha = request.args.get("senha", "").strip()
    if not senha_adm_valida(senha):
        return jsonify({"erro": "❌ Acesso negado!"}), 403
    grupos_col.delete_one({"_id": ObjectId(grupo_id)})
    return jsonify({"sucesso": "✅ Grupo apagado!"})

@app.route("/admin/denuncias", methods=["GET"])
def admin_denuncias():
    senha = request.args.get("senha", "").strip()
    if not senha_adm_valida(senha):
        return jsonify({"erro": "❌ Acesso negado!"}), 403
    lista = list(denuncias_col.find({}).sort([("data", -1)]))
    for d in lista: d["_id"] = str(d["_id"])
    return jsonify(lista)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
