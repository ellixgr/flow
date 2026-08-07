from flask import Flask, render_template, request, jsonify, redirect, url_for
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from datetime import datetime, timedelta
import requests
import os
import uuid
from dotenv import load_dotenv
from functools import wraps

load_dotenv()
app = Flask(__name__)
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
denuncias_col.create_index([("ip", 1), ("grupo_id", 1)], unique=True)# ✅ ÍNDICES DE SEGURANÇA — CORRIGIDO
grupos_col.create_index("link", unique=True)
grupos_col.create_index("vip_ate")
denuncias_col.create_index([("ip", 1), ("grupo_id", 1)], unique=True)
# ✅ TTL em CAMPO ÚNICO — funciona!
sessoes_col.create_index("criado_em", expireAfterSeconds=60)

# 🛡️ SISTEMA ANTI-FLOOD / ANTI-HACKER
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
                return jsonify({"erro": "⏳ Aguarde! Você está enviando muito rápido. Tente novamente em alguns segundos."}), 429
            sessoes_col.delete_many({"ip": ip, "acao": acao})
            sessoes_col.insert_one({"ip": ip, "acao": acao, "criado_em": datetime.utcnow()})
            return f(*args, **kwargs)
        return wrapper
    return decorator

# 💰 GERAR PAGAMENTO MERCADO PAGO
def criar_pagamento(valor, descricao, grupo_id):
    url = "https://api.mercadopago.com/checkout/preferences"
    headers = {
        "Authorization": f"Bearer {MP_TOKEN}",
        "Content-Type": "application/json"
    }
    dados = {
        "items": [{
            "id": str(grupo_id),
            "title": descricao,
            "quantity": 1,
            "unit_price": float(valor)
        }],
        "notification_url": f"{request.url_root}webhook-mercadopago",
        "back_urls": {
            "success": f"{request.url_root}sucesso",
            "failure": f"{request.url_root}",
            "pending": f"{request.url_root}"
        }
    }
    try:
        resp = requests.post(url, json=dados, headers=headers, timeout=15)
        if resp.status_code == 201:
            return resp.json()
    except Exception as e:
        print(f"Erro MP: {e}")
    return None

# 🏠 PÁGINA PRINCIPAL
@app.route("/")
def index():
    # ✅ REMOVE VIP AUTOMATICAMENTE APÓS EXPIRAR
    grupos_col.update_many({"vip_ate": {"$lt": datetime.utcnow()}}, {"$set": {"vip": False}})
    # 📋 BUSCA GRUPOS (VIP PRIMEIRO)
    grupos = list(grupos_col.find().sort([("vip", -1), ("criado_em", -1)]))
    # CONVERTE ID PARA STRING
    for g in grupos:
        g["_id"] = str(g["_id"])
        g.setdefault("visualizacoes", 0)
        g.setdefault("foto", "https://files.catbox.moe/6av9dl.png")
    return render_template("index.html", grupos=grupos)

# 📤 ENVIAR GRUPO / FORMULÁRIO
@app.route("/enviar-grupo", methods=["POST"])
@limite_requisicoes(15)
def enviar_grupo():
    dados = request.form
    link = dados.get("link", "").strip()
    nome = dados.get("nome", "").strip()
    foto = dados.get("foto", "").strip() or "https://files.catbox.moe/6av9dl.png"
    codigo_adm = dados.get("codigo_adm", "").strip()
    plano = dados.get("plano", "5")

    # ✅ VALIDAÇÕES
    if not link.startswith(("https://chat.whatsapp.com/", "https://gruposwhats.app/")):
        return jsonify({"erro": "🔗 Link inválido! Use apenas link de grupo do WhatsApp"}), 400
    if len(nome) < 3:
        return jsonify({"erro": "📛 Nome muito curto! Mínimo 3 caracteres"}), 400

    # 🔑 CÓDIGO ADMIN — ENVIA GRÁTIS!
    if codigo_adm == CHAVE_ADM:
        novo_grupo = {
            "nome": nome,
            "link": link,
            "foto": foto,
            "vip": True,
            "vip_ate": datetime.utcnow() + timedelta(days=365*10),
            "visualizacoes": 0,
            "criado_em": datetime.utcnow(),
            "gratuito": True
        }
        grupos_col.insert_one(novo_grupo)
        return jsonify({"sucesso": "✅ GRUPO ENVIADO GRATUITAMENTE! Código Admin aceito! 🎉"})

    # 💳 ESCOLHA DE PLANO
    if plano == "5":
        valor, dias = 5.00, 1
    elif plano == "10":
        valor, dias = 10.00, 2
    else:
        return jsonify({"erro": "❌ Plano inválido!"}), 400

    # ⚠️ SALVA GRUPO TEMPORÁRIO
    grupo_temp = {
        "nome": nome,
        "link": link,
        "foto": foto,
        "vip": False,
        "visualizacoes": 0,
        "criado_em": datetime.utcnow()
    }
    try:
        resultado = grupos_col.insert_one(grupo_temp)
        grupo_id = str(resultado.inserted_id)
    except DuplicateKeyError:
        return jsonify({"erro": "⚠️ Esse grupo JÁ foi enviado anteriormente!"}), 409

    # 💰 CRIA PAGAMENTO
    pagamento = criar_pagamento(valor, f"VIP Grupo — {dias} Dia(s)", grupo_id)
    if not pagamento:
        grupos_col.delete_one({"_id": resultado.inserted_id})
        return jsonify({"erro": "❌ Erro ao gerar pagamento. Tente novamente."}), 500

    # 📝 REGISTRA TRANSAÇÃO
    transacoes_col.insert_one({
        "grupo_id": grupo_id,
        "valor": valor,
        "dias": dias,
        "status": "pendente",
        "criado_em": datetime.utcnow()
    })

    return jsonify({
        "sucesso": "✅ Grupo cadastrado! Conclua o pagamento para ativar o VIP ⬇️",
        "pagamento_url": pagamento["init_point"],
        "grupo_id": grupo_id
    })

# 💳 WEBHOOK — ATIVA VIP APÓS PAGAMENTO
@app.route("/webhook-mercadopago", methods=["POST"])
def webhook_mp():
    dados = request.get_json()
    if not dados:
        dados = request.form
    if dados.get("action") == "payment.created" or dados.get("topic") == "payment":
        pagamento_id = dados.get("data", {}).get("id") or dados.get("id")
        if not pagamento_id:
            return "OK", 200
        # CONSULTA PAGAMENTO
        url = f"https://api.mercadopago.com/v1/payments/{pagamento_id}"
        headers = {"Authorization": f"Bearer {MP_TOKEN}"}
        try:
            resp = requests.get(url, headers=headers, timeout=15).json()
            status = resp.get("status")
            if status == "approved":
                ref = resp["additional_info"]["items"][0]["id"]
                transacao = transacoes_col.find_one({"grupo_id": ref})
                if transacao and transacao["status"] != "aprovado":
                    transacoes_col.update_one({"grupo_id": ref}, {"$set": {"status": "aprovado"}})
                    grupos_col.update_one({"_id": ref}, {
                        "$set": {
                            "vip": True,
                            "vip_ate": datetime.utcnow() + timedelta(days=transacao["dias"])
                        }
                    })
        except Exception as e:
            print(f"Webhook erro: {e}")
    return "OK", 200

# ✅ PÁGINA DE SUCESSO
@app.route("/sucesso")
def sucesso():
    return """
    <html><body style="background:#090a0f;color:white;font-family:sans-serif;text-align:center;padding-top:50px;">
        <h1 style="color:#25d366">✅ PAGAMENTO APROVADO!</h1>
        <p style="font-size:18px">Seu grupo ficará em DESTAQUE por 1 ou 2 dias 🥇</p>
        <p>Volte para a página principal ↓</p>
        <a href="/" style="background:#25d366;color:black;padding:12px 24px;border-radius:12px;text-decoration:none;font-weight:bold;">VOLTAR AO SITE</a>
    </body></html>
    """

# 👁️ CONTADOR DE VISUALIZAÇÕES (PROTEGIDO)
@app.route("/visualizar/<grupo_id>", methods=["POST"])
def visualizar(grupo_id):
    ip = request.remote_addr
    chave_ja_viu = f"visualizou:{ip}:{grupo_id}"
    ja_viu = sessoes_col.find_one({"ip": ip, "acao": chave_ja_viu, "criado_em": {"$gte": datetime.utcnow() - timedelta(hours=24)}})
    if not ja_viu:
        grupos_col.update_one({"_id": grupo_id}, {"$inc": {"visualizacoes": 1}})
        sessoes_col.insert_one({"ip": ip, "acao": chave_ja_viu, "criado_em": datetime.utcnow()})
    grupo = grupos_col.find_one({"_id": grupo_id})
    total = grupo.get("visualizacoes", 0) if grupo else 0
    return jsonify({"total": total})

# 🚩 DENUNCIAR GRUPO
@app.route("/denunciar/<grupo_id>", methods=["POST"])
@limite_requisicoes(120)
def denunciar(grupo_id):
    ip = request.remote_addr
    dados = request.get_json() or {}
    motivo = dados.get("motivo", "Não informado")
    try:
        denuncias_col.insert_one({
            "grupo_id": grupo_id,
            "ip": ip,
            "motivo": motivo,
            "criado_em": datetime.utcnow()
        })
        return jsonify({"sucesso": "✅ Denúncia enviada! O dono vai verificar."})
    except DuplicateKeyError:
        return jsonify({"erro": "⚠️ Você JÁ denunciou esse grupo!"}), 429

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
