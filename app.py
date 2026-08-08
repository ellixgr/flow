from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
import mercadopago
from datetime import datetime, timedelta, UTC
import os

app = Flask(__name__)
CORS(app)

# ==============================================
# 🔑 PEGA DAS VARIÁVEIS DO RENDER
# ==============================================
MONGO_URI = os.getenv("MONGO_URI")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
CHAVE_ADM = os.getenv("CHAVE_ADM", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

if not MONGO_URI:
    raise Exception("❌ MONGO_URI NÃO CONFIGURADA!")
if not MP_ACCESS_TOKEN:
    raise Exception("❌ MP_ACCESS_TOKEN NÃO CONFIGURADA!")

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
    print("✅ CONECTADO AO MONGODB!")
except Exception as e:
    print(f"❌ ERRO BANCO: {e}")
    raise

# ✅ VALIDA CÓDIGO VIP
def codigo_valido(codigo):
    if not codigo:
        return False
    codigo = codigo.strip()
    if codigo == CHAVE_ADM or codigo == SECRET_KEY:
        return True
    return codigos_col.find_one({"codigo": codigo, "usado": False}) is not None

# ✅ VALIDA SENHA ADM
def senha_adm_valida(senha):
    if not senha:
        return False
    return senha.strip() == CHAVE_ADM

# ✅ NÃO MARCA CHAVES FIXAS COMO USADAS
def marcar_codigo_usado(codigo):
    codigo = codigo.strip()
    if codigo == CHAVE_ADM or codigo == SECRET_KEY:
        return
    codigos_col.update_one({"codigo": codigo}, {"$set": {"usado": True, "usado_em": datetime.now(UTC)}})

# ✅ GERA PIX
def gerar_pix(valor, descricao):
    try:
        pix_data = {
            "transaction_amount": valor,
            "description": descricao,
            "payment_method_id": "pix",
            "payer": {"email": "pagamento@flow.com.br"}
        }
        resultado = sdk.payment().create(pix_data)
        pagamento = resultado["response"]
        if "point_of_interaction" in pagamento:
            return {
                "sucesso": True,
                "id_pagamento": pagamento["id"],
                "codigo_pix": pagamento["point_of_interaction"]["transaction_data"]["qr_code"]
            }
        return {"erro": "Não foi possível gerar o PIX"}
    except Exception as e:
        return {"erro": str(e)}

# ✅ SALVA GRUPO
def salvar_grupo(dados, dias_vip):
    expira_em = datetime.now(UTC) + timedelta(days=dias_vip)
    grupo = {
        "link": dados["link"],
        "nome": dados["nome"],
        "foto": dados.get("foto") or "https://files.catbox.moe/0aa6f2.png",
        "categoria": dados.get("categoria", "Amizade"),
        "vip": True,
        "dias_vip": dias_vip,
        "expira_em": expira_em,
        "cliques": 0,
        "denuncias": 0,
        "criado_em": datetime.now(UTC),
        "ativo": True
    }
    return grupos_col.insert_one(grupo)

# 🌐 PÁGINA PRINCIPAL
@app.route("/")
def index():
    agora = datetime.now(UTC)
    lista = list(grupos_col.find({"ativo": True, "expira_em": {"$gte": agora}}).sort([("$natural", -1)]))
    for g in lista: g["_id"] = str(g["_id"])
    return render_template("index.html", grupos=lista)

# 📤 ENVIAR GRUPO
@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    link = request.form.get("link", "").strip()
    nome = request.form.get("nome", "").strip()
    foto = request.form.get("foto", "").strip()
    categoria = request.form.get("categoria", "Amizade")
    plano = request.form.get("plano", "5")
    codigo_adm = request.form.get("codigo_adm", "").strip()

    if not link or not nome:
        return jsonify({"erro": "Preencha link e nome!"})
    if not link.startswith("https://chat.whatsapp.com/"):
        return jsonify({"erro": "Link inválido! Use link do WhatsApp"})

    # ✅ CÓDIGO VIP → SALVA GRÁTIS
    if codigo_adm and codigo_valido(codigo_adm):
        dias = 1 if plano == "5" else 2
        salvar_grupo({"link": link, "nome": nome, "foto": foto, "categoria": categoria}, dias)
        marcar_codigo_usado(codigo_adm)
        return jsonify({"sucesso": "✅ Grupo enviado GRÁTIS!"})

    # ❌ CÓDIGO ERRADO
    if codigo_adm:
        return jsonify({"erro": "❌ Código VIP inválido!"})

    # 💳 SEM CÓDIGO → GERA PIX
    valor = 5.00 if plano == "5" else 10.00
    dias = 1 if plano == "5" else 2
    pix = gerar_pix(valor, f"VIP Grupo WhatsApp — {dias} dia(s)")
    if "erro" in pix: return jsonify(pix)
    return jsonify({
        "sucesso": "✅ PIX gerado! Pague e aparecerá automaticamente!",
        "codigo_pix": pix["codigo_pix"],
        "dias_vip": dias,
        "link_grupo": link,
        "nome_grupo": nome,
        "foto_grupo": foto
    })

# 🔐 VERIFICAR SENHA ADM — CORRIGIDO! NÃO ACEITA QUALQUER COISA!
@app.route("/verificar-senha-adm", methods=["POST"])
def verificar_senha_adm():
    senha = request.form.get("senha", "").strip()
    if senha_adm_valida(senha):
        return jsonify({"sucesso": "✅ Senha correta! Acesso liberado!"})
    return jsonify({"erro": "❌ Senha incorreta! Tente novamente."})

# 📋 LISTA GRUPOS (PAINEL ADM)
@app.route("/admin/grupos", methods=["GET"])
def admin_grupos():
    senha = request.args.get("senha", "").strip()
    if not senha_adm_valida(senha):
        return jsonify({"erro": "❌ Acesso negado!"}), 403
    lista = list(grupos_col.find({}).sort([("criado_em", -1)]))
    for g in lista: g["_id"] = str(g["_id"])
    return jsonify(lista)

# 🗑️ APAGAR GRUPO (PAINEL ADM)
@app.route("/admin/apagar-grupo/<grupo_id>", methods=["POST"])
def apagar_grupo(grupo_id):
    senha = request.form.get("senha", "").strip()
    if not senha_adm_valida(senha):
        return jsonify({"erro": "❌ Acesso negado!"}), 403
    grupos_col.delete_one({"_id": ObjectId(grupo_id)})
    return jsonify({"sucesso": "✅ Grupo apagado!"})

# 🚩 DENUNCIAR
@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    dados = request.get_json() or {}
    motivo = dados.get("motivo", "outro")
    outros_motivos = dados.get("outros_motivos", "").strip()

    # ✅ INCREMENTA CONTADOR DE DENÚNCIAS
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"denuncias": 1}})

    # ✅ SALVA DENÚNCIA COMPLETA
    denuncia = {
        "grupo_id": grupo_id,
        "motivo": motivo,
        "outros_motivos": outros_motivos if motivo == "outro" else "",
        "data": datetime.now(UTC)
    }
    denuncias_col.insert_one(denuncia)

    return jsonify({"sucesso": "✅ Denúncia enviada! Obrigado!"})

# 📋 LISTA DENÚNCIAS (PAINEL ADM)
@app.route("/admin/denuncias", methods=["GET"])
def admin_denuncias():
    senha = request.args.get("senha", "").strip()
    if not senha_adm_valida(senha):
        return jsonify({"erro": "❌ Acesso negado!"}), 403
    lista = list(denuncias_col.find({}).sort([("data", -1)]))
    for d in lista: d["_id"] = str(d["_id"])
    return jsonify(lista)

# 📋 JSON GRUPOS PÚBLICO
@app.route("/grupos-dados")
def grupos_dados():
    agora = datetime.now(UTC)
    lista = list(grupos_col.find({"ativo": True, "expira_em": {"$gte": agora}}).sort([("$natural", -1)]))
    for g in lista: g["_id"] = str(g["_id"])
    return jsonify(lista)

# 👆 CLIQUES
@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
