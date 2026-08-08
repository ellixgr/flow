from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from datetime import datetime, timedelta
import requests
import os
import uuid
from dotenv import load_dotenv
from functools import wraps
import mercadopago  # ✅ ADICIONA ESSA BIBLIOTECA!

load_dotenv()
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("SECRET_KEY", "chave_secreta_super_segura_123456")

# 🔗 DADOS DE CONEXÃO
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://sanibronx21_db_user:efeitoalmanaque@cluster0.olwogxx.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
MP_TOKEN = os.getenv("MP_ACCESS_TOKEN", "APP_USR-2233798366076054-072321-1ebc8660b5623826d8e956f1d629fa98-805811682")
CHAVE_ADM = os.getenv("CHAVE_ADM", "labareta444")

# 📦 CONEXÃO BANCO DE DADOS
client = MongoClient(MONGO_URI)
db = client["flow_grupos"]
grupos_col = db["grupos"]
transacoes_col = db["transacoes"]
denuncias_col = db["denuncias"]
sessoes_col = db["sessoes"]

# 📌 ÍNDICES DE SEGURANÇA
grupos_col.create_index("link", unique=True)
grupos_col.create_index("vip_ate")
denuncias_col.create_index([("ip", 1), ("grupo_id", 1)], unique=True)
sessoes_col.create_index("criado_em", expireAfterSeconds=60)

# 🛡️ SISTEMA ANTI-FLOOD
def limite_requisicoes(segundos=10):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.remote_addr
            acao = request.endpoint
            chave = f"{ip}:{acao}"
            tempo_limite = datetime.utcnow() - timedelta(seconds=segundos)
            existente = sessoes_col.find_one({"ip": ip, "acao": acao, "criado_em": {"$gte": tempo_limite}})
            if existente:
                return jsonify({"erro": "⏳ Aguarde! Você está enviando muito rápido."}), 429
            sessoes_col.delete_many({"ip": ip, "acao": acao})
            sessoes_col.insert_one({"ip": ip, "acao": acao, "criado_em": datetime.utcnow()})
            return f(*args, **kwargs)
        return wrapper
    return decorator

# 💰 GERAR PIX DIRETO (SEM SAIR DO SITE!)
def criar_pix_pagamento(valor, descricao, grupo_id, ip_usuario):
    sdk = mercadopago.SDK(MP_TOKEN)
    
    dados_pagamento = {
        "transaction_amount": float(valor),
        "description": descricao,
        "payment_method_id": "pix",
        "payer": {
            "email": f"usuario_{ip_usuario.replace('.','_')}@flow-grupos.com.br",
            "first_name": "Usuario",
            "last_name": "Flow"
        },
        "notification_url": f"{request.url_root}webhook-mercadopago",
        "external_reference": str(grupo_id)  # ✅ ID DO GRUPO PARA SABER QUEM PAGOU!
    }
    
    try:
        resultado = sdk.payment().create(dados_pagamento)
        if resultado["status"] in [200, 201]:
            pix_dados = resultado["response"]
            return {
                "sucesso": True,
                "codigo_pix": pix_dados["point_of_interaction"]["transaction_data"]["qr_code"],
                "pix_base64": pix_dados["point_of_interaction"]["transaction_data"]["qr_code_base64"],
                "id_pagamento": pix_dados["id"]
            }
    except Exception as e:
        print(f"Erro ao gerar PIX: {e}")
    return {"sucesso": False}

# 🏠 PÁGINA PRINCIPAL
@app.route("/")
def index():
    grupos_col.update_many({"vip_ate": {"$lt": datetime.utcnow()}}, {"$set": {"vip": False}})
    grupos = list(grupos_col.find().sort([("vip", -1), ("criado_em", -1)]))
    for g in grupos:
        g["_id"] = str(g["_id"])
        g.setdefault("cliques", 0)
        g.setdefault("foto", "https://files.catbox.moe/6av9dl.png")
    return render_template("index.html", grupos=grupos)

# 📤 ENVIAR GRUPO → AGORA GERA PIX DIRETO!
@app.route("/enviar-grupo", methods=["POST"])
@limite_requisicoes(15)
def enviar_grupo():
    dados = request.form
    link = dados.get("link", "").strip()
    nome = dados.get("nome", "").strip()
    foto = dados.get("foto", "").strip() or "https://files.catbox.moe/6av9dl.png"
    codigo_adm = dados.get("codigo_adm", "").strip()
    plano = dados.get("plano", "5")
    ip_usuario = request.remote_addr

    # VALIDAÇÕES
    if not link.startswith(("https://chat.whatsapp.com/", "https://gruposwhats.app/")):
        return jsonify({"erro": "🔗 Link inválido! Use apenas link de grupo do WhatsApp"}), 400
    if len(nome) < 3:
        return jsonify({"erro": "📛 Nome muito curto! Mínimo 3 caracteres"}), 400

    # CÓDIGO ADMIN = GRÁTIS
    if codigo_adm == CHAVE_ADM:
        novo_grupo = {
            "nome": nome, "link": link, "foto": foto,
            "vip": True, "vip_ate": datetime.utcnow() + timedelta(days=3650),
            "cliques": 0, "criado_em": datetime.utcnow(), "gratuito": True
        }
        grupos_col.insert_one(novo_grupo)
        return jsonify({"sucesso": "✅ GRUPO ENVIADO GRATUITAMENTE! 🎉"})

    # ESCOLHA DE VALORES
    if plano == "5":
        valor, dias = 5.00, 1
    elif plano == "10":
        valor, dias = 10.00, 2
    else:
        return jsonify({"erro": "❌ Plano inválido!"}), 400

    # SALVA GRUPO TEMPORÁRIO
    grupo_temp = {
        "nome": nome, "link": link, "foto": foto,
        "vip": False, "cliques": 0, "criado_em": datetime.utcnow()
    }
    try:
        resultado = grupos_col.insert_one(grupo_temp)
        grupo_id = str(resultado.inserted_id)
    except DuplicateKeyError:
        return jsonify({"erro": "⚠️ Esse grupo JÁ foi enviado anteriormente!"}), 409

    # 🎯 GERA O PIX DIRETO AQUI!
    pix = criar_pix_pagamento(valor, f"VIP Grupo - {dias} Dia(s)", grupo_id, ip_usuario)
    if not pix["sucesso"]:
        grupos_col.delete_one({"_id": resultado.inserted_id})
        return jsonify({"erro": "❌ Erro ao gerar código PIX. Tente novamente."}), 500

    # SALVA TRANSAÇÃO
    transacoes_col.insert_one({
        "grupo_id": grupo_id, "id_pagamento_mp": pix["id_pagamento"],
        "valor": valor, "dias": dias, "ip_usuario": ip_usuario,
        "status": "pendente", "criado_em": datetime.utcnow()
    })

    # ✅ RETORNA O CÓDIGO PIX PARA O SEU SITE MOSTRAR!
    return jsonify({
        "sucesso": "✅ Grupo cadastrado! Use o PIX abaixo para ativar o VIP 👇",
        "codigo_pix": pix["codigo_pix"],
        "grupo_id": grupo_id
    })

# 💳 WEBHOOK → QUANDO PAGAR, ATIVA AUTOMATICAMENTE!
@app.route("/webhook-mercadopago", methods=["POST"])
def webhook_mp():
    dados = request.get_json() or request.form
    if dados.get("action") == "payment.created" or dados.get("topic") == "payment":
        pagamento_id = dados.get("data", {}).get("id") or dados.get("id")
        if not pagamento_id:
            return "OK", 200
        
        # BUSCA DADOS DO PAGAMENTO
        sdk = mercadopago.SDK(MP_TOKEN)
        resp = sdk.payment().get(pagamento_id)
        if resp["status"] == 200 and resp["response"]["status"] == "approved":
            grupo_id = resp["response"]["external_reference"]
            transacao = transacoes_col.find_one({"grupo_id": grupo_id, "status": "pendente"})
            
            if transacao:
                # ATIVA VIP E MARCA PAGO
                transacoes_col.update_one({"grupo_id": grupo_id}, {"$set": {"status": "aprovado"}})
                grupos_col.update_one({"_id": grupo_id}, {
                    "$set": {
                        "vip": True,
                        "vip_ate": datetime.utcnow() + timedelta(days=transacao["dias"])
                    }
                })
                print(f"✅ PAGAMENTO CONFIRMADO! Grupo {grupo_id} ativado!")
    return "OK", 200

# DEMAIS ROTAS (clicar, denunciar, etc) CONTINUAM IGUAIS
@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    ip = request.remote_addr
    chave = f"clicou:{ip}:{grupo_id}"
    if not sessoes_col.find_one({"ip": ip, "acao": chave, "criado_em": {"$gte": datetime.utcnow() - timedelta(hours=24)}}):
        grupos_col.update_one({"_id": grupo_id}, {"$inc": {"cliques": 1}})
        sessoes_col.insert_one({"ip": ip, "acao": chave, "criado_em": datetime.utcnow()})
    return jsonify({"total": grupos_col.find_one({"_id": grupo_id}).get("cliques", 0) if grupos_col.find_one({"_id": grupo_id}) else 0})

@app.route("/denunciar/<grupo_id>", methods=["POST"])
@limite_requisicoes(120)
def denunciar(grupo_id):
    ip = request.remote_addr
    motivo = (request.get_json() or {}).get("motivo", "Não informado")
    try:
        denuncias_col.insert_one({"grupo_id": grupo_id, "ip": ip, "motivo": motivo, "criado_em": datetime.utcnow()})
        return jsonify({"sucesso": "✅ Denúncia enviada!"})
    except DuplicateKeyError:
        return jsonify({"erro": "⚠️ Você já denunciou esse grupo!"}), 429

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
