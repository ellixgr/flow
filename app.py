from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
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

# ✅ CORS LIBERADO
CORS(app, resources={r"/*": {"origins": [
    "https://ellixgr.github.io",
    "https://ellixgr.github.io/flow/",
    "http://localhost:5500"
]}})

@app.after_request
def liberar_cors(resposta):
    resposta.headers["Access-Control-Allow-Origin"] = "*"
    resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resposta.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Usuario-ID"
    return resposta

# ==============================================
# 🔑 VARIÁVEIS
# ==============================================
MONGO_URI = os.getenv("MONGO_URI")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
ADMIN_SENHA = os.getenv("ADMIN_SENHA", "admin123")

if not MONGO_URI:
    raise Exception("❌ MONGO_URI NÃO CONFIGURADA!")
if not MP_ACCESS_TOKEN:
    raise Exception("❌ MP_ACCESS_TOKEN NÃO CONFIGURADA!")

# ==============================================
# CONEXÃO BANCO
# ==============================================
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
db = client.flow
grupos_col = db.grupos
codigos_col = db.codigos_vip
denuncias_col = db.denuncias

CATEGORIAS = ["Todos", "Amizade", "Namoro", "Zoeira", "Outros"]

# ==============================================
# 🔒 FUNÇÕES
# ==============================================
def gerar_id_usuario():
    return str(uuid.uuid4())

def obter_usuario(request):
    return request.headers.get("X-Usuario-ID", gerar_id_usuario())

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
    except Exception as e:
        print("Erro comprimir:", e)
        return None

# ✅ CÓDIGO VIP — CORRIGIDO
def codigo_valido(codigo):
    if not codigo or len(codigo.strip()) < 2:
        return False
    codigo = codigo.strip().upper()
    # Tenta código EXATO primeiro
    res = codigos_col.find_one({"codigo": codigo, "usado": False})
    if res:
        return True
    # Tenta sem diferenciar maiúsculas/minúsculas
    res = codigos_col.find_one({"codigo": {"$regex": f"^{codigo}$", "$options": "i"}, "usado": False})
    return res is not None

def marcar_codigo_usado(codigo):
    codigo = codigo.strip().upper()
    codigos_col.update_one(
        {"codigo": {"$regex": f"^{codigo}$", "$options": "i"}},
        {"$set": {"usado": True, "usado_em": datetime.utcnow()}}
    )

def gerar_pix(valor, descricao):
    try:
        pix_data = {
            "transaction_amount": valor,
            "description": descricao,
            "payment_method_id": "pix",
            "payer": {"email": "pagamento@flow.com.br"}
        }
        resultado = sdk.payment().create(pix_data)
        pagamento = resultado.get("response", {})
        if "point_of_interaction" in pagamento:
            return {
                "sucesso": True,
                "id_pagamento": pagamento["id"],
                "codigo_pix": pagamento["point_of_interaction"]["transaction_data"]["qr_code"]
            }
        return {"erro": "Não foi possível gerar o PIX"}
    except Exception as e:
        return {"erro": str(e)}

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
# 🌐 ROTAS
# ==============================================
@app.route("/")
def index():
    return render_template("index.html", categorias=CATEGORIAS)

# ✅ CORRIGIDA — ERRO NA RESPOSTA TAVA AQUI!
@app.route("/grupos-dados")
def grupos_dados():
    try:
        agora = datetime.utcnow()
        cat = request.args.get("categoria", "Todos")
        filtro = {"ativo": True, "expira_em": {"$gte": agora}}
        if cat != "Todos":
            filtro["categoria"] = cat
        lista = list(grupos_col.find(filtro).sort([("impulsionado_em", -1), ("criado_em", -1)]))
        resultado = []
        for g in lista:
            g["_id"] = str(g["_id"])
            g.pop("usuario_id", None)
            resultado.append(g)
        return jsonify(resultado)
    except Exception as e:
        print("ERRO grupos-dados:", e)
        return jsonify({"erro": str(e)}), 500

# ✅ CORRIGIDA — ENVIAR GRUPO
@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    try:
        usuario_id = obter_usuario(request)
        link = request.form.get("link", "").strip()
        nome = request.form.get("nome", "").strip()
        foto_base64 = request.form.get("foto_base64", "").strip()
        categoria = request.form.get("categoria", "Outros")
        plano = request.form.get("plano", "5")
        codigo_adm = request.form.get("codigo_adm", "").strip()

        if not link or not nome:
            return jsonify({"erro": "Preencha link e nome!"})
        if not link.startswith("https://chat.whatsapp.com/"):
            return jsonify({"erro": "Link inválido!"})
        if categoria not in CATEGORIAS:
            categoria = "Outros"

        foto_final = "https://files.catbox.moe/0aa6f2.png"
        if foto_base64:
            comprimida = comprimir_foto(foto_base64)
            if comprimida:
                foto_final = comprimida

        dados_grupo = {"link": link, "nome": nome, "foto": foto_final, "categoria": categoria}

        # ✅ SE CÓDIGO FOR VÁLIDO → SALVA DIRETO, SEM GERAR PIX!
        if codigo_adm and codigo_valido(codigo_adm):
            dias = 1 if plano == "5" else 2
            salvar_grupo(dados_grupo, dias, usuario_id)
            marcar_codigo_usado(codigo_adm)
            return jsonify({"sucesso": "✅ Grupo enviado GRÁTIS!", "usuario_id": usuario_id})

        # ❌ SEM CÓDIGO VÁLIDO → GERA PIX
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
    except Exception as e:
        print("ERRO enviar-grupo:", e)
        return jsonify({"erro": str(e)}), 500

@app.route("/meus-grupos")
def meus_grupos():
    try:
        usuario_id = obter_usuario(request)
        lista = list(grupos_col.find({"usuario_id": usuario_id, "ativo": True}).sort([("criado_em", -1)]))
        agora = datetime.utcnow()
        resultado = []
        for g in lista:
            g["_id"] = str(g["_id"])
            g["pode_impulsionar"] = True
            if g.get("impulsionado_em"):
                proximo = g["impulsionado_em"] + timedelta(hours=2)
                g["pode_impulsionar"] = agora >= proximo
                g["proximo_impulso"] = proximo.isoformat()
            g.pop("usuario_id", None)
            resultado.append(g)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

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
            return jsonify({"erro": f"Aguarde até {proximo.strftime('%H:%M')}!"})
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"impulsionado_em": agora}})
    return jsonify({"sucesso": "✅ Grupo impulsionado!"})

@app.route("/apagar-grupo/<grupo_id>", methods=["POST"])
def apagar_grupo(grupo_id):
    usuario_id = obter_usuario(request)
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": usuario_id})
    if not grupo:
        return jsonify({"erro": "Não é dono desse grupo!"})
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"ativo": False}})
    return jsonify({"sucesso": "✅ Grupo apagado!"})

@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
