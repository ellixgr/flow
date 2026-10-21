import os
import json
import uuid
import time
import base64
import io
import requests
from flask import Flask, request, jsonify, render_template_string
from pymongo import MongoClient
from bson.objectid import ObjectId
from PIL import Image

app = Flask(__name__)

# ==============================================
# 🔗 VARIÁVEIS DE AMBIENTE (PROTEGIDAS)
# ==============================================
MONGO_URI = os.getenv("MONGO_URI")
MP_TOKEN = os.getenv("MP_TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD") # Corrigido para bater certo com o Render

if not MONGO_URI or not MP_TOKEN or not ADMIN_PASSWORD:
    print("⚠️ AVISO: As variáveis de ambiente MONGO_URI, MP_TOKEN ou ADMIN_PASSWORD não foram totalmente configuradas no Render!")

try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = mongo_client.get_database("bot_database")
    colecao_grupos = db["grupos_site"]
    colecao_denuncias = db["denuncias"]
    colecao_pagamentos = db["pagamentos_pendentes"]
    print("✅ Conectado ao MongoDB com sucesso!")
except Exception as e:
    print(f"❌ Erro ao conectar no MongoDB: {e}")

# Tabela de 10 Planos
PLANOS_SITE = {
    1: {"dias": 7, "nome": "1 Semana", "valor": 7.00},
    2: {"dias": 14, "nome": "2 Semanas", "valor": 12.00},
    3: {"dias": 21, "nome": "3 Semanas", "valor": 17.00},
    4: {"dias": 30, "nome": "1 Mês", "valor": 22.00},
    5: {"dias": 60, "nome": "2 Meses", "valor": 40.00},
    6: {"dias": 90, "nome": "3 Meses", "valor": 55.00},
    7: {"dias": 120, "nome": "4 Meses", "valor": 70.00},
    8: {"dias": 150, "nome": "5 Meses", "valor": 85.00},
    9: {"dias": 180, "nome": "6 Meses", "valor": 100.00},
    10: {"dias": 365, "nome": "1 Ano (VIP)", "valor": 150.00}
}

# ==============================================
# 🌐 ROTAS DO SITE E API
# ==============================================

@app.route('/')
def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.route('/adm')
def adm_panel():
    with open("adm.html", "r", encoding="utf-8") as f:
        return f.read()

@app.route('/api/grupos', methods=['GET'])
def listar_grupos():
    grupos = list(colecao_grupos.find({}, {"_id": 1, "nome": 1, "link": 1, "categoria": 1, "descricao": 1, "foto": 1}))
    for g in grupos:
        g["_id"] = str(g["_id"])
    return jsonify(grupos)

@app.route('/api/criar-pagamento', methods=['POST'])
def criar_pagamento():
    data = request.json or {}
    nome = data.get("nome")
    link = data.get("link", "").strip()
    categoria = data.get("categoria", "Outros")
    descricao = data.get("descricao", "")[:30]
    foto_input = data.get("foto", "").strip()
    
    foto_final = "https://files.catbox.moe/0aa6f2.png"
    if foto_input and "base64," in foto_input:
        try:
            header, encoded = foto_input.split(",", 1)
            img_data = base64.b64decode(encoded)
            img = Image.open(io.BytesIO(img_data))
            img = img.convert("RGB")
            img.thumbnail((300, 300))
            
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=85)
            compressed_base64 = base64.b64encode(output.getvalue()).decode("utf-8")
            foto_final = f"data:image/jpeg;base64,{compressed_base64}"
        except Exception as img_err:
            print(f"Erro ao processar imagem enviada: {img_err}")

    plano_id = int(data.get("plano_id", 1))

    if not link or ("chat.whatsapp.com" not in link and "whatsapp.com/channel" not in link):
        return jsonify({"erro": "Apenas links oficiais de grupos ou canais do WhatsApp são permitidos!"}), 400

    if colecao_grupos.find_one({"link": link}):
        return jsonify({"erro": "Este link de grupo já está publicado no site!"}), 400

    plano = PLANOS_SITE.get(plano_id, PLANOS_SITE[1])
    valor = plano["valor"]

    url = "https://api.mercadopago.com/v1/payments"
    headers = {
        "Authorization": f"Bearer {MP_TOKEN}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid.uuid4())
    }
    payload = {
        "transaction_amount": float(valor),
        "description": f"Anúncio Grupo: {nome}",
        "payment_method_id": "pix",
        "payer": {"email": f"cliente_{int(time.time())}@flowsite.com"}
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code == 201:
            res = r.json()
            pid = str(res["id"])
            qr_code = res.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code", "")

            colecao_pagamentos.insert_one({
                "payment_id": pid,
                "nome": nome,
                "link": link,
                "categoria": categoria,
                "descricao": descricao,
                "foto": foto_final,
                "ativado": False,
                "criado_em": time.time()
            })

            return jsonify({"payment_id": pid, "pix_code": qr_code})
        else:
            print(f"Erro MP resposta: {r.text}")
    except Exception as e:
        print(f"Erro Mercado Pago: {e}")

    return jsonify({"erro": "Falha ao gerar o Pix no Mercado Pago. Verifique o token."}), 500

@app.route('/api/verificar-pagamento', methods=['GET'])
def verificar_pagamento():
    pid = request.args.get("id")
    status = "pending"
    
    try:
        headers = {"Authorization": f"Bearer {MP_TOKEN}"}
        r = requests.get(f"https://api.mercadopago.com/v1/payments/{pid}", headers=headers, timeout=10)
        if r.status_code == 200:
            d = r.json()
            status = d.get("status", "pending")
            if status == "approved":
                pendente = colecao_pagamentos.find_one({"payment_id": str(pid)})
                if pendente and not pendente.get("ativado"):
                    colecao_grupos.insert_one({
                        "nome": pendente["nome"],
                        "link": pendente["link"],
                        "categoria": pendente["categoria"],
                        "descricao": pendente["descricao"],
                        "foto": pendente["foto"],
                        "criado_em": time.time()
                    })
                    colecao_pagamentos.update_one({"payment_id": str(pid)}, {"$set": {"ativado": True}})
    except Exception as e:
        print(f"Erro ao checar Pix: {e}")

    return jsonify({"status": status})

@app.route('/api/denunciar', methods=['POST'])
def denunciar():
    data = request.json or {}
    colecao_denuncias.insert_one({
        "grupo_id": data.get("grupo_id"),
        "motivo": data.get("motivo"),
        "data": time.time()
    })
    return jsonify({"sucesso": True})

# ==============================================
# 🛡️ ROTAS DO PAINEL ADM (CORRIGIDAS PARA POST E ADMIN_PASSWORD)
# ==============================================

@app.route('/api/adm/dados', methods=['POST'])
def adm_dados():
    data = request.json or {}
    if data.get("senha") != ADMIN_PASSWORD:
        return jsonify({"erro": "Senha incorreta!"}), 401
    
    denuncias = list(colecao_denuncias.find({}))
    for d in denuncias:
        d["_id"] = str(d["_id"])

    grupos = list(colecao_grupos.find({}))
    for g in grupos:
        g["_id"] = str(g["_id"])

    return jsonify({"denuncias": denuncias, "grupos": grupos})

@app.route('/api/adm/cadastrar', methods=['POST'])
def adm_cadastrar_direto():
    data = request.json or {}
    if data.get("senha") != ADMIN_PASSWORD:
        return jsonify({"erro": "Senha incorreta!"}), 401
    
    nome = data.get("nome")
    link = data.get("link", "").strip()
    categoria = data.get("categoria", "Outros")
    descricao = data.get("descricao", "")[:30]
    foto_input = data.get("foto", "").strip()
    
    if not link or ("chat.whatsapp.com" not in link and "whatsapp.com/channel" not in link):
        return jsonify({"erro": "Apenas links oficiais de grupos ou canais do WhatsApp são permitidos!"}), 400

    if colecao_grupos.find_one({"link": link}):
        return jsonify({"erro": "Este link de grupo já está publicado no site!"}), 400

    foto_final = "https://files.catbox.moe/0aa6f2.png"
    if foto_input and "base64," in foto_input:
        try:
            header, encoded = foto_input.split(",", 1)
            img_data = base64.b64decode(encoded)
            img = Image.open(io.BytesIO(img_data))
            img = img.convert("RGB")
            img.thumbnail((300, 300))
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=85)
            compressed_base64 = base64.b64encode(output.getvalue()).decode("utf-8")
            foto_final = f"data:image/jpeg;base64,{compressed_base64}"
        except Exception as img_err:
            print(f"Erro ao processar imagem ADM: {img_err}")

    colecao_grupos.insert_one({
        "nome": nome,
        "link": link,
        "categoria": categoria,
        "descricao": descricao,
        "foto": foto_final,
        "criado_em": time.time()
    })

    return jsonify({"sucesso": True})

@app.route('/api/adm/remover', methods=['POST'])
def adm_remover():
    data = request.json or {}
    if data.get("senha") != ADMIN_PASSWORD:
        return jsonify({"erro": "Senha incorreta!"}), 401
    
    gid = data.get("id")
    try:
        colecao_grupos.delete_one({"_id": ObjectId(gid)})
    except:
        colecao_grupos.delete_one({"_id": gid})
        
    return jsonify({"sucesso": True})

@app.route('/api/adm/remover-denuncia', methods=['POST'])
def adm_remover_denuncia():
    data = request.json or {}
    if data.get("senha") != ADMIN_PASSWORD:
        return jsonify({"erro": "Senha incorreta!"}), 401
    
    did = data.get("id")
    try:
        colecao_denuncias.delete_one({"_id": ObjectId(did)})
    except:
        colecao_denuncias.delete_one({"_id": did})
        
    return jsonify({"sucesso": True})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
