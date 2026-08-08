from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from datetime import datetime, timedelta
import uuid
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# 🔗 CONEXÃO COM BANCO
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["flow_db"]
grupos_col = db["grupos"]
denuncias_col = db["denuncias"]
codigos_vip_col = db["codigos_vip"]

# 🔐 SENHA ADMIN
SENHA_ADM = "admin123"

# INDEX
@app.route("/")
def index():
    return render_template("index.html")

# 📋 CARREGAR GRUPOS
@app.route("/grupos-dados")
def grupos_dados():
    cat = request.args.get("categoria", "Todos")
    filtro = {"ativo": True}
    if cat != "Todos":
        filtro["categoria"] = cat
    grupos = list(grupos_col.find(filtro).sort([("vip", -1), ("criado_em", -1)]))
    for g in grupos:
        g["_id"] = str(g["_id"])
    return jsonify(grupos)

# 👆 REGISTRAR CLIQUE
@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not uid:
        return jsonify({"erro": "Sem ID"}), 400
    # Evita múltiplos cliques do mesmo usuário
    chave_clique = f"clique:{uid}:{grupo_id}"
    if db.cliques.find_one({"_id": chave_clique}):
        return jsonify({"sucesso": "Contado anteriormente"})
    db.cliques.insert_one({"_id": chave_clique, "tempo": datetime.utcnow()})
    grupos_col.update_one({"_id": uuid.UUID(grupo_id)}, {"$inc": {"cliques": 1}})
    return jsonify({"sucesso": True})

# 📤 ENVIAR GRUPO
@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    dados = request.form
    link = dados.get("link", "").strip()
    nome = dados.get("nome", "").strip()
    categoria = dados.get("categoria", "Outros")
    foto = dados.get("foto_base64", "")
    plano = dados.get("plano", "0")
    codigo = dados.get("codigo_adm", "").strip()
    uid = request.headers.get("X-Usuario-ID", "")

    if not link or not nome:
        return jsonify({"erro": "Preencha link e nome!"}), 400

    # ✅ CÓDIGO VIP — SEM PIX
    if codigo:
        codigo_ok = codigos_vip_col.find_one({"codigo": codigo, "usado": False})
        if codigo_ok:
            codigos_vip_col.update_one({"_id": codigo_ok["_id"]}, {"$set": {"usado": True}})
            novo_grupo = {
                "link": link, "nome": nome, "categoria": categoria, "foto": foto,
                "usuario_id": uid, "cliques": 0, "ativo": True, "vip": True,
                "criado_em": datetime.utcnow()
            }
            grupos_col.insert_one(novo_grupo)
            return jsonify({"sucesso": "✅ Grupo cadastrado com VIP! Sem pagamento.", "sem_pix": True})
        else:
            return jsonify({"erro": "❌ Código inválido ou já usado!"}), 400

    # 💳 GERAR PIX (simulação)
    codigo_pix = f"00020126580014br.gov.bcb.pix0104TEST{uuid.uuid4().hex[:16].upper()}5204000053039865802BR5904FLOW6007RIO DE JANEIRO62070503***6304"
    return jsonify({"codigo_pix": codigo_pix, "valor": f"R$ {plano},00"})

# 👤 MEUS GRUPOS
@app.route("/meus-grupos")
def meus_grupos():
    uid = request.headers.get("X-Usuario-ID", "")
    grupos = list(grupos_col.find({"usuario_id": uid}).sort("criado_em", -1))
    prox_impulso = {}
    for g in grupos:
        g["_id"] = str(g["_id"])
        ultimo = g.get("ultimo_impulso")
        if ultimo and (datetime.utcnow() - ultimo) < timedelta(hours=1):
            g["pode_impulsionar"] = False
            g["proximo_impulso"] = (ultimo + timedelta(hours=1)).isoformat() + "Z"
        else:
            g["pode_impulsionar"] = True
    return jsonify(grupos)

# 🚀 IMPULSIONAR
@app.route("/impulsionar/<grupo_id>", methods=["POST"])
def impulsionar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    try:
        grupo = grupos_col.find_one({"_id": uuid.UUID(grupo_id), "usuario_id": uid})
        if not grupo:
            return jsonify({"erro": "Não encontrado"}), 404
        ultimo = grupo.get("ultimo_impulso")
        if ultimo and (datetime.utcnow() - ultimo) < timedelta(hours=1):
            return jsonify({"erro": "⏰ Aguarde 1 hora!"}), 429
        grupos_col.update_one({"_id": uuid.UUID(grupo_id)}, {"$set": {"vip": True, "ultimo_impulso": datetime.utcnow()}})
        return jsonify({"sucesso": "✅ Impulsionado!"})
    except Exception as e:
        return jsonify({"erro": str(e)}), 400

# 🗑️ APAGAR GRUPO
@app.route("/apagar-grupo/<grupo_id>", methods=["POST"])
def apagar_grupo(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    grupos_col.delete_one({"_id": uuid.UUID(grupo_id), "usuario_id": uid})
    return jsonify({"sucesso": "✅ Apagado!"})

# ⚠️ DENUNCIAR
@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    dados = request.json
    denuncias_col.insert_one({
        "grupo_id": grupo_id,
        "motivo": dados.get("motivo", ""),
        "denunciado_em": datetime.utcnow(),
        "lida": False
    })
    return jsonify({"sucesso": "✅ Denunciado!"})

# 🔐 PAINEL ADM — ROTAS QUE ESTAVAM FALTANDO!
@app.route("/adm/grupos")
def adm_grupos():
    if request.headers.get("X-Adm-Senha") != SENHA_ADM:
        return jsonify({"erro": "Acesso negado"}), 403
    todos = list(grupos_col.find().sort("criado_em", -1))
    for g in todos:
        g["_id"] = str(g["_id"])
        g["ativo"] = g.get("ativo", True)
    return jsonify(todos)

@app.route("/adm/denuncias")
def adm_denuncias():
    if request.headers.get("X-Adm-Senha") != SENHA_ADM:
        return jsonify({"erro": "Acesso negado"}), 403
    den = list(denuncias_col.find({"lida": False}).sort("denunciado_em", -1))
    for d in den:
        d["_id"] = str(d["_id"])
    return jsonify(den)

@app.route("/adm/desativar/<grupo_id>", methods=["POST"])
def adm_desativar(grupo_id):
    if request.headers.get("X-Adm-Senha") != SENHA_ADM:
        return jsonify({"erro": "Acesso negado"}), 403
    grupos_col.update_one({"_id": uuid.UUID(grupo_id)}, {"$set": {"ativo": False}})
    return jsonify({"sucesso": "✅ Desativado!"})

@app.route("/adm/marcar-lida/<denuncia_id>", methods=["POST"])
def adm_marcar_lida(denuncia_id):
    if request.headers.get("X-Adm-Senha") != SENHA_ADM:
        return jsonify({"erro": "Acesso negado"}), 403
    denuncias_col.update_one({"_id": uuid.UUID(denuncia_id)}, {"$set": {"lida": True}})
    return jsonify({"sucesso": "✅ Marcada como lida!"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
