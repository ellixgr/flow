from flask import Flask, render_template, request, jsonify
from flask_cors import CORS  # ✅ ADICIONADO: Resolve o erro de conexão!
from pymongo import MongoClient
from bson.objectid import ObjectId
import mercadopago
from datetime import datetime, timedelta, UTC  # ✅ Corrige o aviso de data
import os

app = Flask(__name__)
CORS(app)  # ✅ LIBERA ACESSO DO SEU SITE (resolve o "Erro de conexão")

# ==============================================
# 🔑 PEGA EXCLUSIVAMENTE DAS VARIÁVEIS DO RENDER
# ==============================================

MONGO_URI = os.getenv("MONGO_URI")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

# ✅ VERIFICA SE EXISTE
if not MONGO_URI:
    raise Exception("❌ VARIÁVEL MONGO_URI NÃO CONFIGURADA NO RENDER!")
if not MP_ACCESS_TOKEN:
    raise Exception("❌ VARIÁVEL MP_ACCESS_TOKEN NÃO CONFIGURADA NO RENDER!")

# ==============================================
# NÃO MEXE DAQUI PRA BAIXO
# ==============================================

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# CONEXÃO COM BANCO
try:
    client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
    db = client.flow
    grupos_col = db.grupos
    codigos_col = db.codigos_vip
    print("✅ CONECTADO AO MONGODB COM SUCESSO!")
except Exception as e:
    print(f"❌ ERRO AO CONECTAR NO BANCO: {e}")
    raise

# ✅ CÓDIGO VIP VÁLIDO?
def codigo_valido(codigo):
    if not codigo:
        return False
    return codigos_col.find_one({"codigo": codigo, "usado": False}) is not None

# ✅ MARCA CÓDIGO COMO USADO
def marcar_codigo_usado(codigo):
    codigos_col.update_one(
        {"codigo": codigo},
        {"$set": {"usado": True, "usado_em": datetime.now(UTC)}}  # ✅ Data corrigida
    )

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
                "codigo_pix": pagamento["point_of_interaction"]["transaction_data"]["qr_code"],
                "url_pix": pagamento["point_of_interaction"]["transaction_data"]["ticket_url"]
            }
        return {"erro": "Não foi possível gerar o PIX"}
    except Exception as e:
        return {"erro": str(e)}

# ✅ SALVA GRUPO NO BANCO
def salvar_grupo(dados, dias_vip):
    expira_em = datetime.now(UTC) + timedelta(days=dias_vip)  # ✅ Data corrigida
    grupo = {
        "link": dados["link"],
        "nome": dados["nome"],
        "foto": dados.get("foto") or "https://files.catbox.moe/0aa6f2.png",
        "vip": True,
        "dias_vip": dias_vip,
        "expira_em": expira_em,
        "cliques": 0,
        "criado_em": datetime.now(UTC),  # ✅ Data corrigida
        "ativo": True
    }
    return grupos_col.insert_one(grupo)

# 🌐 PÁGINA PRINCIPAL
@app.route("/")
def index():
    agora = datetime.now(UTC)  # ✅ Data corrigida
    lista = list(grupos_col.find({
        "ativo": True,
        "expira_em": {"$gte": agora}
    }).sort([("$natural", -1)]))
    
    for g in lista:
        g["_id"] = str(g["_id"])
    return render_template("index.html", grupos=lista)

# 📤 ENVIAR GRUPO → SÓ GERA PIX, NÃO SALVA ANTES DE PAGAR!
@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    link = request.form.get("link", "").strip()
    nome = request.form.get("nome", "").strip()
    foto = request.form.get("foto", "").strip()
    plano = request.form.get("plano", "5")
    codigo_adm = request.form.get("codigo_adm", "").strip()

    if not link or not nome:
        return jsonify({"erro": "Preencha link e nome!"})
    if not link.startswith("https://chat.whatsapp.com/"):
        return jsonify({"erro": "Link inválido! Use link do WhatsApp"})

    # ✅ CÓDIGO VIP → SALVA DIRETO GRÁTIS
    if codigo_adm and codigo_valido(codigo_adm):
        dias = 1 if plano == "5" else 2
        salvar_grupo({"link": link, "nome": nome, "foto": foto}, dias)
        marcar_codigo_usado(codigo_adm)
        return jsonify({"sucesso": "✅ Grupo enviado GRÁTIS! Ativado!"})

    # ✅ SEM CÓDIGO → GERA PIX, NÃO SALVA NADA AINDA
    valor = 5.00 if plano == "5" else 10.00
    dias = 1 if plano == "5" else 2
    pix = gerar_pix(valor, f"VIP Grupo WhatsApp — {dias} dia(s)")
    
    if "erro" in pix:
        return jsonify({"erro": pix["erro"]})

    return jsonify({
        "sucesso": "✅ PIX gerado! Pague e o grupo aparecerá automaticamente!",
        "codigo_pix": pix["codigo_pix"],
        "id_pagamento": pix["id_pagamento"],
        "dias_vip": dias,
        "link_grupo": link,
        "nome_grupo": nome,
        "foto_grupo": foto
    })

# 📋 JSON DOS GRUPOS
@app.route("/grupos-dados")
def grupos_dados():
    agora = datetime.now(UTC)  # ✅ Data corrigida
    lista = list(grupos_col.find({
        "ativo": True,
        "expira_em": {"$gte": agora}
    }).sort([("$natural", -1)]))
    for g in lista:
        g["_id"] = str(g["_id"])
    return jsonify(lista)

# 🚩 DENÚNCIA
@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"denuncias": 1}})
    return jsonify({"sucesso": "✅ Denúncia enviada!"})

# 👆 CLIQUES
@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
