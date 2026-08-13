from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import os
from uuid import uuid4
from dotenv import load_dotenv
import requests  # ✅ IGUAL NO BOT — SEM BIBLIOTECA MERCADOPAGO!
import time
from collections import defaultdict

load_dotenv(override=True)
app = Flask(__name__)

# ✅ Anti-Flood funcional
limite_requisitos = defaultdict(list)
LIMITE_POR_IP = 4
JANELA_TEMPO = 60

@app.before_request
def verificar_anti_flood():
    rota = request.path
    if rota == "/enviar-grupo":
        ip = request.remote_addr
        agora = time.time()
        limite_requisitos[ip] = [t for t in limite_requisitos[ip] if agora - t < JANELA_TEMPO]
        if len(limite_requisitos[ip]) >= LIMITE_POR_IP:
            return jsonify({"erro": "⚠️ Muitas requisições! Aguarde 1 minuto antes de enviar novamente."}), 429
        limite_requisitos[ip].append(agora)

# ✅ CORS SEGURO E LIBERADO COMPLETAMENTE
CORS(app, resources={r"/*": {
    "origins": [
        "https://ellixgr.github.io", 
        "https://ellixgr.github.io/flow",
        "https://flow-81mj.onrender.com",
        "https://flow-mohn.onrender.com"
    ],
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type", "X-Usuario-ID", "X-Adm-Senha"],
    "supports_credentials": True
}})


# ✅ Variáveis do ambiente — SEM VALIDAÇÃO QUE QUEBRA O SERVIDOR!
MONGO_URI = os.getenv("MONGO_URI")
CODIGO_VIP_SECRETO = os.getenv("CODIGO_VIP")
SENHA_ADM = os.getenv("SENHA_ADM")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "").strip()  # TIRA ESPAÇOS AUTOMÁTICAMENTE!

TEMPO_IMPULSIONAR = timedelta(hours=2)

PLANOS_VIP = {
    "5": {"valor": 5.00, "dias": 1, "nome": "R$ 5,00 → 1 Dia VIP"},
    "10": {"valor": 10.00, "dias": 2, "nome": "R$ 10,00 → 2 Dias VIP"},
    "30": {"valor": 30.00, "dias": 3, "nome": "R$ 30,00 → 3 Dias VIP"},
    "100": {"valor": 100.00, "dias": 30, "nome": "🎁 R$ 100,00 → 1 MÊS VIP"}
}

# ✅ FUNÇÃO IGUALZINHA DO SEU BOT — GARANTIDO QUE FUNCIONA!
def gerar_pix_mercadopago(valor: float, descricao: str = "Grupo WhatsApp"):
    url = "https://api.mercadopago.com/v1/payments"
    headers = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid4())
    }
    payload = {
        "transaction_amount": valor,
        "description": descricao,
        "payment_method_id": "pix",
        "payer": {
            "email": "flow@suporte.com",
            "first_name": "Usuario",
            "last_name": "Flow"
        }
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"[MP] Status: {resp.status_code} | Resposta: {resp.text[:400]}") # LOG COMPLETO NO RENDER!

        if resp.status_code == 201:
            dados = resp.json()
            codigo_pix = dados.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code")
            id_pagamento = dados.get("id")
            if codigo_pix and id_pagamento:
                return True, codigo_pix, id_pagamento, None
            else:
                return False, None, None, "Retorno da API não tem código PIX"
        else:
            return False, None, None, f"Erro API: Status {resp.status_code} — {resp.text[:200]}"

    except Exception as e:
        print(f"[MP] Erro conexão: {str(e)}")
        return False, None, None, f"Falha ao conectar: {str(e)}"

# ✅ FUNÇÃO TAMBÉM IGUAL AO BOT PARA VERIFICAR PAGAMENTO
def verificar_pagamento_mp(pag_id):
    url = f"https://api.mercadopago.com/v1/payments/{pag_id}"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            dados = resp.json()
            return dados.get("status") == "approved", dados.get("transaction_amount", 0)
        return False, 0
    except Exception as e:
        print(f"[MP] Erro verificar pagamento: {e}")
        return False, 0

# Conexão MongoDB com estabilidade extra
client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=20000,
    socketTimeoutMS=45000,
    retryWrites=True,
    retryReads=True
)
db = client["flow_db"]
grupos_col = db["grupos"]
grupos_pendentes_col = db["grupos_pendentes"]
denuncias_col = db["denuncias"]
cliques_col = db["cliques"]
pagamentos_col = db["pagamentos"]

try:
    cliques_col.create_index("chave", unique=True, name="idx_chave_unica", partialFilterExpression={"chave": {"$exists": True}})
    pagamentos_col.create_index("codigo_pix", unique=True)
except Exception:
    pass

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
        
        grupos = list(grupos_col.find(filtro).sort([
            ("ultimo_impulso", -1), ("vip", -1), ("criado_em", -1)
        ]))
        
        agora = datetime.utcnow()
        uid = request.headers.get("X-Usuario-ID", "").strip()[:64]
        
        for g in grupos:
            g["_id"] = str(g["_id"])
            dono_grupo = g.get("usuario_id", "")
            g["cliques"] = g.get("cliques", 0)

            if g.get("vip_ate") and agora < g["vip_ate"]:
                g["vip_ativo"] = True
                g["vip_restante_segundos"] = int((g["vip_ate"] - agora).total_seconds())
            else:
                g["vip_ativo"] = False
                g["vip_restante_segundos"] = 0
                g["vip"] = False

            if dono_grupo and uid and dono_grupo == uid:
                ultimo = g.get("ultimo_impulso")
                if ultimo:
                    proximo = ultimo + TEMPO_IMPULSIONAR
                    g["pode_impulsionar"] = agora >= proximo
                    g["tempo_restante_impulso"] = int((proximo - agora).total_seconds()) if not g["pode_impulsionar"] else 0
                else:
                    g["pode_impulsionar"] = True
                    g["tempo_restante_impulso"] = 0
            else:
                g["pode_impulsionar"] = None
                g["tempo_restante_impulso"] = None
        
        return jsonify(grupos)
    except Exception as e:
        print("ERRO grupos-dados:", str(e))
        return jsonify([]), 200

@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "").strip()[:64] or str(uuid4())
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    try:
        chave = f"{uid}||{grupo_id}"
        if not cliques_col.find_one({"chave": chave}):
            cliques_col.insert_one({"chave": chave, "data": datetime.utcnow()})
            grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
            return jsonify({"sucesso": True, "mensagem": "Clique contado!"})
        return jsonify({"sucesso": True, "mensagem": "Já contado antes"})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    try:
        if not MP_ACCESS_TOKEN:
            return jsonify({"erro": "❌ Mercado Pago NÃO CONFIGURADO! Verifique o token MP_ACCESS_TOKEN nas variáveis."}), 500

        dados = request.form
        link = dados.get("link", "").strip()[:256]
        nome = dados.get("nome", "").strip()[:100]
        categoria = dados.get("categoria", "Outros")[:50]
        foto = dados.get("foto_base64", "")[:200000]
        codigo = dados.get("codigo_adm", "").strip()[:64]
        uid = request.headers.get("X-Usuario-ID", "").strip()[:64] or str(uuid4())

        if not link or not nome:
            return jsonify({"erro": "Preencha link e nome!"}), 400
        if not link.startswith("https://chat.whatsapp.com/"):
            return jsonify({"erro": "Link só do WhatsApp!"}), 400
        if grupos_col.find_one({"link": link, "ativo": True}):
            return jsonify({"erro": "Esse grupo já está cadastrado!"}), 400

        agora = datetime.utcnow()
        
        # 🎁 Código VIP do dono: gratuito
        if CODIGO_VIP_SECRETO and codigo == CODIGO_VIP_SECRETO:
            grupos_col.insert_one({
                "link": link, "nome": nome, "categoria": categoria, "foto": foto,
                "usuario_id": uid, "cliques": 0, "ativo": True,
                "vip": True, "vip_ate": agora + timedelta(days=1),
                "ultimo_impulso": agora, "criado_em": agora
            })
            return jsonify({"sucesso": "✅ Grupo GRÁTIS publicado!", "sem_pix": True})

        # 💳 AGORA USA A FUNÇÃO DO BOT!
        plano = PLANOS_VIP.get(dados.get("plano", "5"))
        ok, codigo_pix, id_pagamento, erro = gerar_pix_mercadopago(plano["valor"], f"Grupo: {nome}")

        if not ok:
            return jsonify({"erro": f"❌ {erro}"}), 500

        # Salva pendente
        pendente = grupos_pendentes_col.insert_one({
            "link": link, "nome": nome, "categoria": categoria, "foto": foto,
            "usuario_id": uid, "plano": plano, "id_pagamento_mp": id_pagamento,
            "criado_em": agora
        })

        return jsonify({
            "pendente_id": str(pendente.inserted_id),
            "codigo_pix": codigo_pix,
            "valor": plano["valor"],
            "dias_vip": plano["dias"]
        })
    
    except Exception as e:
        print("ERRO GERAL envio:", str(e))
        return jsonify({"erro": f"Erro: {str(e)}"}), 500

@app.route("/verificar-pagamento/<pendente_id>", methods=["POST"])
def verificar_pagamento(pendente_id):
    try:
        if not MP_ACCESS_TOKEN:
            return jsonify({"erro": "Mercado Pago não configurado"}),500

        if not ObjectId.is_valid(pendente_id):
            return jsonify({"erro": "ID inválido"}), 400
        
        pendente = grupos_pendentes_col.find_one({"_id": ObjectId(pendente_id)})
        if not pendente:
            return jsonify({"erro": "Não encontrado"}), 404

        aprovado, valor_pago = verificar_pagamento_mp(pendente["id_pagamento_mp"])

        if aprovado:
            grupos_col.insert_one({
                "link": pendente["link"], "nome": pendente["nome"], "categoria": pendente["categoria"],
                "foto": pendente["foto"], "usuario_id": pendente["usuario_id"], "cliques": 0, "ativo": True,
                "vip": True, "vip_ate": datetime.utcnow() + timedelta(days=pendente["plano"]["dias"]),
                "ultimo_impulso": datetime.utcnow(), "criado_em": datetime.utcnow()
            })
            grupos_pendentes_col.delete_one({"_id": pendente["_id"]})
            return jsonify({"sucesso": True, "mensagem": "✅ Pagamento aprovado! Grupo publicado!"})
        
        elif valor_pago == -1: # Cancelado/expirado
            grupos_pendentes_col.delete_one({"_id": pendente["_id"]})
            return jsonify({"erro": "Pagamento cancelado/expirado"}), 400
        
        else:
            return jsonify({"status": "pendente", "mensagem": "Aguardando pagamento..."})
    
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route("/meus-grupos")
def meus_grupos():
    uid = request.headers.get("X-Usuario-ID", "").strip()[:64]
    if not uid:
        return jsonify([])
    try:
        agora = datetime.utcnow()
        grupos = list(grupos_col.find({"usuario_id": uid}).sort("ultimo_impulso", -1))
        pendentes = list(grupos_pendentes_col.find({"usuario_id": uid}))
        todos = []

        for g in grupos:
            g["_id"] = str(g["_id"])
            g["cliques"] = g.get("cliques", 0)
            g["vip_ativo"] = bool(g.get("vip_ate") and agora < g["vip_ate"])
            if g["vip_ativo"]:
                g["vip_restante_segundos"] = int((g["vip_ate"] - agora).total_seconds())
            
            ultimo = g.get("ultimo_impulso")
            g["pode_impulsionar"] = not ultimo or agora >= ultimo + TEMPO_IMPULSIONAR
            if not g["pode_impulsionar"]:
                g["proximo_impulso_segundos"] = int((ultimo + TEMPO_IMPULSIONAR - agora).total_seconds())
            
            todos.append(g)

        for p in pendentes:
            p["_id"] = str(p["_id"])
            p["status"] = "aguardando_pagamento"
            todos.append(p)

        return jsonify(todos)
    
    except Exception as e:
        return jsonify([])

@app.route("/impulsionar/<grupo_id>", methods=["POST"])
def impulsionar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "").strip()[:64]
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": uid})
    if not grupo:
        return jsonify({"erro": "Não é dono desse grupo!"}), 403
    
    ultimo = grupo.get("ultimo_impulso")
    if ultimo and datetime.utcnow() - ultimo < TEMPO_IMPULSIONAR:
        t = int((ultimo + TEMPO_IMPULSIONAR - datetime.utcnow()).total_seconds())
        return jsonify({"erro": f"Aguarde {t//3600}h {(t%3600)//60}min"}), 429
    
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"ultimo_impulso": datetime.utcnow()}})
    return jsonify({"sucesso": True, "mensagem": "✅ Impulsionado!"})

@app.route("/apagar-grupo/<grupo_id>", methods=["POST"])
def apagar_grupo(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "").strip()[:64]
    if not uid or not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "Dados inválidos"}), 400
    obj_id = ObjectId(grupo_id)
    res_grupo = grupos_col.delete_one({"_id": obj_id, "usuario_id": uid})
    grupos_pendentes_col.delete_one({"_id": obj_id, "usuario_id": uid})

    if res_grupo.deleted_count == 0:
        return jsonify({"erro": "Você não é o dono ou grupo não existe!"}), 403
    grupos_id_str = grupo_id
    cliques_col.delete_many({"chave": {"$regex": f"\\Q{grupos_id_str}\\E"}})
    denuncias_col.delete_many({"grupo_id": grupos_id_str})
    return jsonify({"sucesso": True, "mensagem": "✅ Grupo apagado com sucesso!"})


@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    dados = request.json or {}
    denuncias_col.insert_one({
        "grupo_id": grupo_id, "motivo": dados.get("motivo", "")[:250],
        "data": datetime.utcnow(), "lida": False
    })
    return jsonify({"sucesso": True})

def verificar_senha():
    recebida = (request.headers.get("X-Adm-Senha") or "").strip()
    return bool(SENHA_ADM and recebida == SENHA_ADM)

@app.route("/adm/grupos")
def adm_grupos():
    if not verificar_senha():
        return jsonify({"erro": "SENHA ERRADA!"}), 403
    todos = list(grupos_col.find().sort("criado_em", -1))
    for g in todos:
        g["_id"] = str(g["_id"])
        g["cliques"] = g.get("cliques", 0)
    return jsonify(todos)

@app.route("/adm/denuncias")
def adm_denuncias():
    if not verificar_senha():
        return jsonify({"erro": "SENHA ERRADA!"}), 403
    den = list(denuncias_col.find({"lida": False}).sort("data", -1))
    res = []
    for d in den:
        obj_grupo_id = ObjectId(d["grupo_id"])
        g = grupos_col.find_one({"_id": obj_grupo_id})
        if not g:
            denuncias_col.delete_one({"_id": d["_id"]})
            continue
        res.append({
            "_id": str(d["_id"]),
            "grupo_id": str(d["grupo_id"]),
            "grupo_nome": g.get("nome", "Apagado"),
            "grupo_link": g.get("link", ""),
            "grupo_foto": g.get("foto", ""),
            "motivo": d.get("motivo", ""),
            "data": d.get("data")
        })
    return jsonify(res)

@app.route("/adm/desativar/<grupo_id>", methods=["POST"])
def adm_desativar(grupo_id):
    if not verificar_senha():
        return jsonify({"erro": "SENHA ERRADA!"}), 403
    obj_id = ObjectId(grupo_id)
    grupos_col.delete_one({"_id": obj_id})
    denuncias_col.delete_many({"grupo_id": grupo_id})
    cliques_col.delete_many({"grupo_id": grupo_id})
    return jsonify({"sucesso": True, "mensagem": "✅ Grupo APAGADO completamente!"})

@app.route("/escolher-plano-vip/<grupo_id>", methods=["POST"])
def escolher_plano_vip(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "").strip()[:64]
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": uid})
    if not grupo:
        return jsonify({"erro": "Não é seu grupo!"}), 404
    
    if not MP_ACCESS_TOKEN:
        return jsonify({"erro": "Mercado Pago não configurado"}),500

    dados = request.json or {}
    plano = PLANOS_VIP.get(dados.get("plano", "5"))
    
    ok, codigo_pix, id_pagamento, erro = gerar_pix_mercadopago(plano["valor"], f"VIP {grupo['nome']}")
    if not ok:
        return jsonify({"erro": erro}), 500

    return jsonify({
        "codigo_pix": codigo_pix,
        "valor": plano["valor"],
        "dias_vip": plano["dias"]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
