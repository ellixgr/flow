from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
import mercadopago
from datetime import datetime, timedelta
import os
import uuid
import base64
from io import BytesIO
from PIL import Image

app = Flask(__name__)

# ==============================================
# 🔑 VARIÁVEIS DO RENDER
# ==============================================
MONGO_URI = os.getenv("MONGO_URI")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
ADMIN_SENHA = os.getenv("ADMIN_SENHA", "admin123")  # Configure no Render!

if not MONGO_URI:
    raise Exception("❌ VARIÁVEL MONGO_URI NÃO CONFIGURADA!")
if not MP_ACCESS_TOKEN:
    raise Exception("❌ VARIÁVEL MP_ACCESS_TOKEN NÃO CONFIGURADA!")

# ==============================================
# CONEXÃO BANCO
# ==============================================
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
db = client.flow
grupos_col = db.grupos
codigos_col = db.codigos_vip
denuncias_col = db.denuncias

# ==============================================
# 📂 CATEGORIAS
# ==============================================
CATEGORIAS = ["Todos", "Amizade", "Namoro", "Zoeira", "Outros"]

# ==============================================
# 🔒 FUNÇÕES DE SEGURANÇA
# ==============================================
def gerar_id_usuario():
    return str(uuid.uuid4())

def obter_usuario(request):
    return request.headers.get("X-Usuario-ID", gerar_id_usuario())

# ==============================================
# 🖼️ COMPRIMIR FOTO
# ==============================================
def comprimir_foto(base64_imagem, largura_max=300):
    try:
        if "," in base64_imagem:
            base64_imagem = base64_imagem.split(",")[1]
        dados = base64.b64decode(base64_imagem)
        img = Image.open(BytesIO(dados))
        w, h = img.size
        if w > largura_max:
            proporcao = largura_max / w
            nova_h = int(h * proporcao)
            img = img.resize((largura_max, nova_h), Image.Resampling.LANCZOS)
        saida = BytesIO()
        img.save(saida, format="JPEG", quality=75)
        return "data:image/jpeg;base64," + base64.b64encode(saida.getvalue()).decode()
    except:
        return None

# ==============================================
# ✅ CÓDIGO VIP
# ==============================================
def codigo_valido(codigo):
    if not codigo:
        return False
    return codigos_col.find_one({"codigo": codigo, "usado": False}) is not None

def marcar_codigo_usado(codigo):
    codigos_col.update_one({"codigo": codigo}, {"$set": {"usado": True, "usado_em": datetime.utcnow()}})

# ==============================================
# 💳 GERAR PIX
# ==============================================
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

# ==============================================
# 💾 SALVAR GRUPO
# ==============================================
def salvar_grupo(dados, dias_vip, usuario_id):
    expira_em = datetime.utcnow() + timedelta(days=dias_vip)
    grupo = {
        "link": dados["link"],
        "nome": dados["nome"],
        "foto": dados.get("foto") or "https://files.catbox.moe/0aa6f2.png",
        "categoria": dados.get("categoria", "Outros"),
        "usuario_id": usuario_id,
        "vip": True,
        "dias_vip": dias_vip,
        "expira_em": expira_em,
        "cliques": 0,
        "impulsionado_em": None,
        "criado_em": datetime.utcnow(),
        "ativo": True
    }
    return grupos_col.insert_one(grupo)

# ==============================================
# 🌐 PÁGINA PRINCIPAL
# ==============================================
@app.route("/")
def index():
    return render_template("index.html", categorias=CATEGORIAS)

# ==============================================
# 📋 GRUPOS POR CATEGORIA
# ==============================================
@app.route("/grupos-dados")
def grupos_dados():
    agora = datetime.utcnow()
    cat = request.args.get("categoria", "Todos")
    filtro = {"ativo": True, "expira_em": {"$gte": agora}}
    if cat != "Todos":
        filtro["categoria"] = cat
    lista = list(grupos_col.find(filtro).sort([("impulsionado_em", -1), ("criado_em", -1)]))
    for g in lista:
        g["_id"] = str(g["_id"])
        del g["usuario_id"]
    return jsonify(lista)

# ==============================================
# 📤 ENVIAR GRUPO
# ==============================================
@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    usuario_id = obter_usuario(request)
    link = request.form.get("link", "").strip()
    nome = request.form.get("nome", "").strip()
    foto_base64 = request.form.get("foto_base64", "").strip()
    foto_url = request.form.get("foto_url", "").strip()
    categoria = request.form.get("categoria", "Outros")
    plano = request.form.get("plano", "5")
    codigo_adm = request.form.get("codigo_adm", "").strip()

    if not link or not nome:
        return jsonify({"erro": "Preencha link e nome!"})
    if not link.startswith("https://chat.whatsapp.com/"):
        return jsonify({"erro": "Link inválido!"})
    if categoria not in CATEGORIAS:
        categoria = "Outros"

    # 🖼️ Processa foto
    foto_final = "https://files.catbox.moe/0aa6f2.png"
    if foto_base64:
        comprimida = comprimir_foto(foto_base64)
        if comprimida:
            foto_final = comprimida
    elif foto_url:
        foto_final = foto_url

    dados_grupo = {"link": link, "nome": nome, "foto": foto_final, "categoria": categoria}

    # ✅ Código VIP → salva direto
    if codigo_adm and codigo_valido(codigo_adm):
        dias = 1 if plano == "5" else 2
        salvar_grupo(dados_grupo, dias, usuario_id)
        marcar_codigo_usado(codigo_adm)
        return jsonify({"sucesso": "✅ Grupo enviado GRÁTIS!", "usuario_id": usuario_id})

    # 💳 Gera PIX
    valor = 5.00 if plano == "5" else 10.00
    dias = 1 if plano == "5" else 2
    pix = gerar_pix(valor, f"VIP Grupo WhatsApp — {dias} dia(s)")
    if "erro" in pix:
        return jsonify({"erro": pix["erro"]})

    return jsonify({
        "sucesso": "✅ PIX gerado! Pague e o grupo aparecerá!",
        "codigo_pix": pix["codigo_pix"],
        "id_pagamento": pix["id_pagamento"],
        "dias_vip": dias,
        "dados_grupo": dados_grupo,
        "usuario_id": usuario_id
    })

# ==============================================
# 👤 MEUS GRUPOS
# ==============================================
@app.route("/meus-grupos")
def meus_grupos():
    usuario_id = obter_usuario(request)
    lista = list(grupos_col.find({"usuario_id": usuario_id, "ativo": True}).sort([("criado_em", -1)]))
    agora = datetime.utcnow()
    for g in lista:
        g["_id"] = str(g["_id"])
        g["pode_impulsionar"] = True
        if g.get("impulsionado_em"):
            proximo = g["impulsionado_em"] + timedelta(hours=2)
            g["pode_impulsionar"] = agora >= proximo
            g["proximo_impulso"] = proximo.isoformat()
        del g["usuario_id"]
    return jsonify(lista)

# ==============================================
# 🚀 IMPULSIONAR GRÁTIS
# ==============================================
@app.route("/impulsionar/<grupo_id>", methods=["POST"])
def impulsionar(grupo_id):
    usuario_id = obter_usuario(request)
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": usuario_id})
    if not grupo:
        return jsonify({"erro": "Grupo não encontrado ou não é seu!"})
    
    agora = datetime.utcnow()
    if grupo.get("impulsionado_em"):
        proximo = grupo["impulsionado_em"] + timedelta(hours=2)
        if agora < proximo:
            return jsonify({"erro": f"Aguarde até {proximo.strftime('%H:%M')} para impulsionar novamente!"})
    
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"impulsionado_em": agora}})
    return jsonify({"sucesso": "✅ Grupo impulsionado! Subiu para o topo!"})

# ==============================================
# 🗑️ APAGAR GRUPO (SÓ DONO)
# ==============================================
@app.route("/apagar-grupo/<grupo_id>", methods=["POST"])
def apagar_grupo(grupo_id):
    usuario_id = obter_usuario(request)
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": usuario_id})
    if not grupo:
        return jsonify({"erro": "Não é dono desse grupo!"})
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"ativo": False}})
    return jsonify({"sucesso": "✅ Grupo apagado!"})

# ==============================================
# 🚩 DENÚNCIA
# ==============================================
@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    dados = request.get_json()
    denuncias_col.insert_one({
        "grupo_id": ObjectId(grupo_id),
        "motivo": dados.get("motivo", "desconhecido"),
        "data": datetime.utcnow(),
        "lida": False
    })
    return jsonify({"sucesso": "✅ Denúncia enviada!"})

# ==============================================
# 🔓 PAINEL ADMIN
# ==============================================
@app.route("/admin/login", methods=["POST"])
def admin_login():
    dados = request.get_json()
    if dados.get("senha") == ADMIN_SENHA:
        return jsonify({"sucesso": True, "token": "admin_ok"})
    return jsonify({"erro": "Senha incorreta!"})

@app.route("/admin/denuncias")
def admin_denuncias():
    if request.args.get("token") != "admin_ok":
        return jsonify({"erro": "Acesso negado!"})
    lista = list(denuncias_col.find({"lida": False}).sort([("data", -1)]))
    for d in lista:
        d["_id"] = str(d["_id"])
        grupo = grupos_col.find_one({"_id": d["grupo_id"]})
        d["grupo_nome"] = grupo["nome"] if grupo else "Desconhecido"
        d["grupo_link"] = grupo["link"] if grupo else "#"
    return jsonify(lista)

@app.route("/admin/apagar-grupo/<grupo_id>", methods=["POST"])
def admin_apagar_grupo(grupo_id):
    if request.headers.get("X-Admin-Token") != "admin_ok":
        return jsonify({"erro": "Acesso negado!"})
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"ativo": False}})
    denuncias_col.update_many({"grupo_id": ObjectId(grupo_id)}, {"$set": {"lida": True}})
    return jsonify({"sucesso": "✅ Grupo apagado!"})

# ==============================================
# 👆 CLIQUES
# ==============================================
@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
