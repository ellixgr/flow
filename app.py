from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["flow_db"]
grupos_col = db["grupos"]
denuncias_col = db["denuncias"]

CODIGO_VIP_SECRETO = os.getenv("HAVE_ADM", "labareta444")
# ✅ SENHA AGORA VEM DO RENDER — NÃO FICA NO GIT!
SENHA_ADM = os.getenv("SENHA_ADM", "admin123")

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
        grupos = list(grupos_col.find(filtro).sort([("vip", -1), ("criado_em", -1)]))
        for g in grupos:
            g["_id"] = str(g["_id"])
        return jsonify(grupos)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not uid: return jsonify({"erro": "Sem ID"}), 400
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    
    try:
        chave_clique = f"clique:{uid}:{grupo_id}"
        ja_contado = db.cliques.find_one({"_id": chave_clique})
        if ja_contado:
            return jsonify({"sucesso": "Contado anteriormente"})
        db.cliques.insert_one({"_id": chave_clique, "tempo": datetime.utcnow()})
        grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
        return jsonify({"sucesso": True})
    except Exception as e:
        grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
        return jsonify({"sucesso": True, "aviso": "Clique contado"})

@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    dados = request.form
    link = dados.get("link", "").strip()
    nome = dados.get("nome", "").strip()
    categoria = dados.get("categoria", "Outros")
    foto = dados.get("foto_base64", "")
    codigo = dados.get("codigo_adm", "").strip()
    uid = request.headers.get("X-Usuario-ID", "")

    if not link or not nome:
        return jsonify({"erro": "Preencha link e nome!"}), 400

    if codigo and codigo.strip() == CODIGO_VIP_SECRETO:
        novo_grupo = {
            "link": link, "nome": nome, "categoria": categoria, "foto": foto,
            "usuario_id": uid, "cliques": 0, "ativo": True, "vip": True,
            "criado_em": datetime.utcnow()
        }
        grupos_col.insert_one(novo_grupo)
        return jsonify({"sucesso": "✅ Grupo cadastrado com VIP!", "sem_pix": True})

    codigo_pix = f"00020126580014br.gov.bcb.pix0104FLOW{os.urandom(7).hex().upper()}5204000053039865802BR5904FLOW6007RIO62070503***6304"
    return jsonify({"codigo_pix": codigo_pix})

@app.route("/meus-grupos")
def meus_grupos():
    uid = request.headers.get("X-Usuario-ID", "")
    grupos = list(grupos_col.find({"usuario_id": uid}).sort("criado_em", -1))
    for g in grupos:
        g["_id"] = str(g["_id"])
        ultimo = g.get("ultimo_impulso")
        g["pode_impulsionar"] = (not ultimo) or (datetime.utcnow() - ultimo >= timedelta(hours=1))
        if not g["pode_impulsionar"]:
            g["proximo_impulso"] = (ultimo + timedelta(hours=1)).isoformat() + "Z"
    return jsonify(grupos)

@app.route("/impulsionar/<grupo_id>", methods=["POST"])
def impulsionar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": uid})
    if not grupo: return jsonify({"erro": "Não encontrado"}), 404
    ultimo = grupo.get("ultimo_impulso")
    if ultimo and (datetime.utcnow() - ultimo) < timedelta(hours=1):
        return jsonify({"erro": "⏰ Aguarde 1h!"}), 429
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"vip": True, "ultimo_impulso": datetime.utcnow()}})
    return jsonify({"sucesso": "✅ Impulsionado!"})

@app.route("/apagar-grupo/<grupo_id>", methods=["POST"])
def apagar_grupo(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    grupos_col.delete_one({"_id": ObjectId(grupo_id), "usuario_id": uid})
    return jsonify({"sucesso": "✅ Apagado!"})

@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    dados = request.json
    denuncias_col.insert_one({
        "grupo_id": grupo_id, "motivo": dados.get("motivo", ""),
        "denunciado_em": datetime.utcnow(), "lida": False
    })
    return jsonify({"sucesso": "✅ Denunciado!"})

def verificar_senha_adm():
    senha_recebida = (request.headers.get("X-Adm-Senha") or "").strip()
    return senha_recebida == SENHA_ADM

@app.route("/adm/grupos")
def adm_grupos():
    if not verificar_senha_adm():
        return jsonify({"erro": "SENHA ERRADA"}), 403
    todos = list(grupos_col.find().sort("criado_em", -1))
    for g in todos: g["_id"] = str(g["_id"]); g["ativo"] = g.get("ativo", True)
    return jsonify(todos)

@app.route("/adm/denuncias")
def adm_denuncias():
    if not verificar_senha_adm():
        return jsonify({"erro": "SENHA ERRADA"}), 403
    den = list(denuncias_col.find({"lida": False}).sort("denunciado_em", -1))
    for d in den: d["_id"] = str(d["_id"])
    return jsonify(den)

@app.route("/adm/desativar/<grupo_id>", methods=["POST"])
def adm_desativar(grupo_id):
    if not verificar_senha_adm():
        return jsonify({"erro": "SENHA ERRADA"}), 403
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"ativo": False}})
    return jsonify({"sucesso": "✅ Desativado!"})

@app.route("/adm/marcar-lida/<denuncia_id>", methods=["POST"])
def adm_marcar_lida(denuncia_id):
    if not verificar_senha_adm():
        return jsonify({"erro": "SENHA ERRADA"}), 403
    if not ObjectId.is_valid(denuncia_id):
        return jsonify({"erro": "ID inválido"}), 400
    denuncias_col.update_one({"_id": ObjectId(denuncia_id)}, {"$set": {"lida": True}})
    return jsonify({"sucesso": "✅ Lida!"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
